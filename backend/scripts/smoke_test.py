#!/usr/bin/env python3
"""Run one real prompt through each installed CLI (via the proxy) and print PASS/FAIL.

    python scripts/smoke_test.py [--only claude|agy|codex|gemini] [--model-claude haiku] [--model-agy gemini-3.8-flash-low]

Starts its own proxy on a temp data dir. It reuses the *host's* CLI logins (use_host_home), which needs
PROXY_SINGLE_USER_PERSONAL_USE - set automatically for this throwaway server only. Each check sends a tiny
prompt, so it consumes a small amount of your real subscription quota.
"""
from __future__ import annotations

import argparse
import json
import os
import pty
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ADMIN = "smoke-admin-token"
results: list[tuple[str, bool, str]] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def agy_capture_probe(binary: str, model: str) -> None:
    """Does `agy -p` lose stdout when stdout is a pipe instead of a TTY? Report both."""
    argv = [binary, "-p", "Reply with exactly: pong", "--output-format", "text", "--model", model, "--mode", "plan"]
    wd = tempfile.mkdtemp()
    try:
        p = subprocess.run(argv, cwd=wd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        piped = p.stdout.strip()
    except subprocess.TimeoutExpired:
        piped = "<timeout>"
    master, slave = pty.openpty()
    proc = subprocess.Popen(argv, cwd=wd, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    out, t0 = b"", time.time()
    while time.time() - t0 < 120:
        r, _, _ = select.select([master], [], [], 0.5)
        if r:
            try:
                d = os.read(master, 4096)
            except OSError:
                break
            if not d:
                break
            out += d
        elif proc.poll() is not None:
            break
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
    ptyd = out.decode(errors="replace").strip()
    shutil.rmtree(wd, ignore_errors=True)
    report("agy stdout capture over pipe", "pong" in piped.lower(), repr(piped[:60]))
    report("agy stdout capture over PTY", "pong" in ptyd.lower(), repr(ptyd[:60]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["claude", "agy", "codex", "gemini"])
    ap.add_argument("--model-claude", default="haiku")
    ap.add_argument("--model-agy", default="gemini-3.8-flash-low")
    ap.add_argument("--model-codex", default="default")
    ap.add_argument("--model-gemini", default="default")
    args = ap.parse_args()

    tools = {k: shutil.which(k) for k in ("claude", "agy", "codex", "gemini")}
    todo = [k for k, v in tools.items() if v and (not args.only or args.only == k)]
    for k, v in tools.items():
        if not v:
            print(f"[SKIP] {k}: not installed")
    if not todo:
        print("nothing to test")
        return 1

    if "agy" in todo:
        agy_capture_probe(tools["agy"], args.model_agy)

    data = tempfile.mkdtemp(prefix="smoke-")
    port = free_port()
    env = {
        "PATH": os.environ["PATH"], "HOME": os.environ["HOME"],
        "PROXY_DATA_DIR": data, "PROXY_ADMIN_TOKEN": ADMIN, "PROXY_PORT": str(port),
        "PROXY_SECRET_KEY": "Hmb0qXbsQZ0cT4oNnVfm2xUe2m9N0m3m1x0yq0rB3dM=", "PROXY_SINGLE_USER_PERSONAL_USE": "true",
        "PROXY_REQUEST_TIMEOUT_S": "180",
    }  # fmt: skip
    srv = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            report("server start", False, (srv.stderr.read() or b"").decode()[-300:] if srv.poll() is not None else "timeout")
            return 1
        adm = {"Authorization": f"Bearer {ADMIN}"}

        def admin(m, path, **kw):
            r = httpx.request(m, base + "/admin" + path, headers=adm, timeout=60, **kw)
            r.raise_for_status()
            return r.json()

        uid = admin("POST", "/users", json={"name": "smoke", "credits_usd": 2.0})["id"]
        key = admin("POST", "/keys", json={"user_id": uid})["key"]
        hdr = {"Authorization": f"Bearer {key}"}
        models = {"claude": args.model_claude, "agy": args.model_agy, "codex": args.model_codex, "gemini": args.model_gemini}
        for name in todo:
            # reuse the host login, raw mode
            admin("PUT", f"/providers/{name}", json={"enabled": True, "mode": "raw", "auth_mode": "oauth_cli",
                                                      "use_host_home": True, "binary_path": tools[name], "max_budget_usd": 0.5,
                                                      "default_model": models[name], "models": [models[name]]})  # fmt: skip
            st = admin("GET", f"/providers/{name}/status")
            report(f"{name}: installed + version", bool(st["installed"] and st["version"]), str(st["version"]))
            if name == "claude":
                report("claude: authenticated", st["authenticated"] is True, st["detail"])
            model = f"{name}/{models[name]}"
            body = {"model": model, "messages": [{"role": "user", "content": "Reply with exactly the single word: pong"}]}
            try:
                t0 = time.time()
                r = httpx.post(base + "/v1/chat/completions", headers=hdr, json=body, timeout=200)
                txt = r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else r.text[:200]
                report(f"{name}: non-streaming", r.status_code == 200 and "pong" in txt.lower(), f"{time.time()-t0:.1f}s {txt.strip()[:60]!r}")
                u = r.json().get("usage") if r.status_code == 200 else None
                report(f"{name}: usage reported", bool(u and u["total_tokens"] > 0), str(u))
            except Exception as e:  # noqa: BLE001
                report(f"{name}: non-streaming", False, repr(e))
            try:
                t0 = time.time()
                chunks, saw_done, first_at = [], False, None
                with httpx.stream("POST", base + "/v1/chat/completions", headers=hdr, json={**body, "stream": True}, timeout=200) as r:
                    if r.status_code != 200:
                        raise RuntimeError(r.read().decode()[:200])
                    for ln in r.iter_lines():
                        if ln == "data: [DONE]":
                            saw_done = True
                        elif ln.startswith("data: "):
                            d = json.loads(ln[6:])
                            c = (d.get("choices") or [{}])[0].get("delta", {}).get("content")
                            if c:
                                first_at = first_at or time.time() - t0
                                chunks.append(c)
                txt = "".join(chunks)
                report(f"{name}: streaming", saw_done and "pong" in txt.lower(), f"{len(chunks)} chunks, first content at {first_at or 0:.1f}s, {txt.strip()[:40]!r}")
            except Exception as e:  # noqa: BLE001
                report(f"{name}: streaming", False, repr(e))
            # raw-mode identity (best effort, informational)
            try:
                r = httpx.post(base + "/v1/chat/completions", headers=hdr, timeout=200, json={"model": model, "messages": [{"role": "user", "content": "who are you? one short sentence."}]})
                ans = r.json()["choices"][0]["message"]["content"].strip()
                bad = any(w in ans.lower() for w in ("coding agent", "coding assistant", "software engineering", "claude code", "antigravity"))
                print(f"[INFO] {name} raw-mode identity: {'MENTIONS coding-agent identity' if bad else 'no coding-agent claim'}: {ans[:140]!r}")
            except Exception as e:  # noqa: BLE001
                print(f"[INFO] {name} identity check failed: {e!r}")
        me = httpx.get(base + "/v1/me", headers=hdr).json()
        report("ledger recorded real usage", me["requests"] >= 1 and me["spent_usd"] > 0, f"{me['requests']} requests, ${me['spent_usd']:.4f} spent")
    finally:
        srv.terminate()
        try:
            srv.wait(5)
        except subprocess.TimeoutExpired:
            srv.kill()
        shutil.rmtree(data, ignore_errors=True)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
