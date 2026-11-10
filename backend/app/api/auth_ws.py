"""Connect-account flow: run the adapter's login command in a PTY and relay it over a websocket.

Protocol (JSON text frames)
  server -> client: {"type":"output","data":str}  {"type":"url","url":str}  {"type":"exit","code":int|null,"auth":{...}}
                    {"type":"error","message":str}
  client -> server: {"type":"input","data":str}   {"type":"resize","rows":int,"cols":int}
Auth: browsers cannot set headers on a WebSocket, and a ?token= query string ends up in access logs, so the
client's FIRST frame must be {"type":"auth","token":"<admin token>"}. Anything else closes the socket (4401).
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..adapters.registry import new_adapter
from ..db import session_scope
from ..models import Provider
from ..runner.env import build_env
from ..runner.pty_runner import PtySession, extract_urls, strip_ansi
from ..runner.workdir import fresh_workdir
from ..security import constant_time_eq
from .admin import _ctx_for_status

router = APIRouter()
AUTH_TIMEOUT_S = 10.0


@router.websocket("/admin/ws/login/{name}")
async def login_ws(ws: WebSocket, name: str, user_id: int = 0):
    await ws.accept()
    expected = ws.app.state.admin_token
    try:
        first = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT_S)
        token = str(first.get("token", "")) if isinstance(first, dict) and first.get("type") == "auth" else ""
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError):
        token = ""
    if not expected or not token or not constant_time_eq(token, expected):
        with contextlib.suppress(Exception):
            await ws.close(code=4401)
        return
    with session_scope() as s:
        p = s.scalar(select(Provider).where(Provider.name == name))
        if p is not None:
            s.expunge(p)
    if p is None:
        await ws.send_json({"type": "error", "message": f"unknown provider {name!r}"})
        await ws.close()
        return

    with fresh_workdir() as wd:
        adapter = new_adapter(p.kind)
        ctx = _ctx_for_status(p, wd, user_id)
        cmd = adapter.login_command(ctx)
        if cmd is None:
            await ws.send_json({"type": "error", "message": "this provider has no login command"})
            await ws.close()
            return
        sess = PtySession(cmd.argv, build_env(ctx, cmd.env, pty=True), str(cmd.cwd or wd), interactive=True, rows=40, cols=1500)
        try:
            await sess.start()
        except OSError as e:
            await ws.send_json({"type": "error", "message": f"cannot start {cmd.argv[0]!r}: {e}"})
            await ws.close()
            return

        seen_urls: set[str] = set()
        tail = ""

        async def scan_urls():
            for u in extract_urls(tail):
                if u not in seen_urls:
                    seen_urls.add(u)
                    await ws.send_json({"type": "url", "url": u})

        async def pump_out():
            nonlocal tail
            while True:
                try:
                    chunk = await asyncio.wait_for(sess.read(), 0.4)
                except asyncio.TimeoutError:
                    await scan_urls()  # only scan when output is idle, so a URL split across reads isn't reported truncated
                    continue
                if chunk is None:
                    await scan_urls()
                    return
                text = chunk.decode("utf-8", "replace")
                await ws.send_json({"type": "output", "data": text})
                tail = (tail + strip_ansi(text))[-6000:]

        async def pump_in():
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "input":
                    sess.write(str(msg.get("data", "")).encode())
                elif msg.get("type") == "resize":
                    with contextlib.suppress(Exception):
                        sess.resize(int(msg["rows"]), int(msg["cols"]))

        async def auto():
            for delay, text in cmd.auto_input:
                await asyncio.sleep(delay)
                sess.write(text.encode())

        auto_t = asyncio.create_task(auto())
        out_t, in_t = asyncio.create_task(pump_out()), asyncio.create_task(pump_in())
        try:
            await asyncio.wait({out_t, in_t}, return_when=asyncio.FIRST_COMPLETED)
            code = await sess.wait(2.0)
            if out_t.done() and not in_t.done():
                st = await asyncio.to_thread(adapter.auth_status, ctx)
                await ws.send_json({"type": "exit", "code": code, "auth": {
                    "installed": st.installed, "version": st.version, "authenticated": st.authenticated, "detail": st.detail}})  # fmt: skip
        except WebSocketDisconnect:
            pass
        finally:
            for t in (out_t, in_t, auto_t):
                t.cancel()
            await sess.close()
            with contextlib.suppress(Exception):
                await ws.close()
