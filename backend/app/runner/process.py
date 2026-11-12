"""Run a Command as a subprocess and stream its stdout lines; always kills the whole process group."""
from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from ..adapters.base import Command
from .pty_runner import PtySession, strip_ansi


class RunTimeout(Exception):
    pass


@dataclass
class RunResult:
    returncode: int | None = None
    stderr_tail: str = ""
    stdout_bytes: int = 0
    extra: dict = field(default_factory=dict)


def kill_group(pid: int, sig: int = signal.SIGTERM) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass  # already gone (a zombie group leader gives EPERM on macOS)


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        import psutil
        try:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.Error:
                    pass
            parent.kill()
        except psutil.Error:
            pass
        if proc.returncode is None:
            await proc.wait()
        return
    if proc.returncode is not None:
        # leader exited but children may linger in the group
        kill_group(proc.pid, signal.SIGKILL)
        return
    kill_group(proc.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), 2.0)
    except asyncio.TimeoutError:
        kill_group(proc.pid, signal.SIGKILL)
        await proc.wait()
    kill_group(proc.pid, signal.SIGKILL)


async def stream_lines(
    cmd: Command, env: dict[str, str], timeout: float, result: RunResult
) -> AsyncIterator[str]:
    """Yield stdout lines. Raises RunTimeout after `timeout` seconds total. Cleans up on cancel/close."""
    if cmd.use_pty:
        async for line in _pty_lines(cmd, env, timeout, result):
            yield line
        return

    deadline = time.monotonic() + timeout
    proc = await asyncio.create_subprocess_exec(
        *cmd.argv,
        stdin=asyncio.subprocess.PIPE if cmd.stdin_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cmd.cwd) if cmd.cwd else None,
        env=env,
        start_new_session=os.name != "nt",  # own process group on Unix
        limit=16 * 1024 * 1024,
    )
    tasks: list[asyncio.Task] = []
    try:
        if cmd.stdin_data is not None:
            tasks.append(asyncio.create_task(_feed_stdin(proc, cmd.stdin_data)))
        tasks.append(asyncio.create_task(_drain_stderr(proc, result)))
        assert proc.stdout is not None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RunTimeout(f"CLI exceeded {timeout:.0f}s")
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), remaining)
            except asyncio.TimeoutError:
                raise RunTimeout(f"CLI exceeded {timeout:.0f}s") from None
            if not raw:
                break
            result.stdout_bytes += len(raw)
            yield raw.decode("utf-8", "replace").rstrip("\r\n")
        try:
            await asyncio.wait_for(proc.wait(), max(1.0, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            raise RunTimeout(f"CLI exceeded {timeout:.0f}s") from None
        result.returncode = proc.returncode
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.shield(_terminate(proc))
        if result.returncode is None:
            result.returncode = proc.returncode


async def _feed_stdin(proc: asyncio.subprocess.Process, data: str) -> None:
    assert proc.stdin is not None
    try:
        proc.stdin.write(data.encode())
        await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass


async def _drain_stderr(proc: asyncio.subprocess.Process, result: RunResult) -> None:
    assert proc.stderr is not None
    buf = b""
    while True:
        chunk = await proc.stderr.read(4096)
        if not chunk:
            break
        buf = (buf + chunk)[-8192:]
        result.stderr_tail = buf.decode("utf-8", "replace")


async def _pty_lines(cmd: Command, env: dict[str, str], timeout: float, result: RunResult) -> AsyncIterator[str]:
    deadline = time.monotonic() + timeout
    sess = PtySession(cmd.argv, env, str(cmd.cwd) if cmd.cwd else None, interactive=False)
    await sess.start()
    pending = ""
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RunTimeout(f"CLI exceeded {timeout:.0f}s")
            try:
                chunk = await asyncio.wait_for(sess.read(), remaining)
            except asyncio.TimeoutError:
                raise RunTimeout(f"CLI exceeded {timeout:.0f}s") from None
            if chunk is None:
                break
            result.stdout_bytes += len(chunk)
            pending += strip_ansi(chunk.decode("utf-8", "replace"))
            *lines, pending = pending.split("\n")
            for ln in lines:
                yield ln.rstrip("\r")
        if pending.strip():
            yield pending.rstrip("\r")
        result.returncode = await sess.wait(max(1.0, deadline - time.monotonic()))
    finally:
        await asyncio.shield(sess.close())
        if result.returncode is None:
            result.returncode = sess.returncode
