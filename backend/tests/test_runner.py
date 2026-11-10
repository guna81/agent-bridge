import asyncio
import os
import sys
import time

import pytest

from app.adapters.base import Command
from app.runner.process import RunResult, RunTimeout, stream_lines
from app.runner.queue import LocalJobQueue, QueueTimeout

ENV = {"PATH": os.environ["PATH"]}


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


async def collect(cmd, timeout=10):
    res, out = RunResult(), []
    async for ln in stream_lines(cmd, ENV, timeout, res):
        out.append(ln)
    return out, res


async def test_streams_lines_and_exit_code(tmp_path):
    out, res = await collect(Command([sys.executable, "-c", "print('a'); print('b')"], cwd=tmp_path))
    assert out == ["a", "b"] and res.returncode == 0


async def test_stdin_data_is_delivered(tmp_path):
    out, _ = await collect(Command([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], cwd=tmp_path, stdin_data="abc"))
    assert out == ["ABC"]


async def test_nonzero_exit_and_stderr_tail(tmp_path):
    out, res = await collect(Command([sys.executable, "-c", "import sys; print('x', file=sys.stderr); sys.exit(7)"], cwd=tmp_path))
    assert res.returncode == 7 and "x" in res.stderr_tail


async def test_timeout_kills_whole_process_group_including_grandchildren(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    script = f"sleep 60 & echo $! > {pidfile}; wait"
    t0 = time.monotonic()
    with pytest.raises(RunTimeout):
        await collect(Command(["sh", "-c", script], cwd=tmp_path), timeout=1.0)
    assert time.monotonic() - t0 < 6
    gc = int(pidfile.read_text())
    for _ in range(30):
        if not alive(gc):
            break
        await asyncio.sleep(0.1)
    assert not alive(gc), "grandchild survived the group kill"


async def test_cancellation_kills_process(tmp_path):
    pidfile = tmp_path / "p"
    cmd = Command([sys.executable, "-c", f"import os,time; open({str(pidfile)!r},'w').write(str(os.getpid())); print('up', flush=True); time.sleep(60)"], cwd=tmp_path)

    async def run():
        await collect(cmd, timeout=30)

    t = asyncio.create_task(run())
    for _ in range(50):
        if pidfile.exists() and pidfile.read_text():
            break
        await asyncio.sleep(0.1)
    pid = int(pidfile.read_text())
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    for _ in range(30):
        if not alive(pid):
            break
        await asyncio.sleep(0.1)
    assert not alive(pid)


TTY_ONLY = "import sys; print('visible' if sys.stdout.isatty() else '')"


async def test_pty_capture_works_where_pipe_capture_is_empty(tmp_path):
    """Models the reported `agy -p` failure mode (output only when stdout is a TTY) and proves the PTY runner fixes it."""
    piped, _ = await collect(Command([sys.executable, "-c", TTY_ONLY], cwd=tmp_path, use_pty=False))
    ptyd, res = await collect(Command([sys.executable, "-c", TTY_ONLY], cwd=tmp_path, use_pty=True))
    assert [l for l in piped if l] == []
    assert ptyd == ["visible"] and res.returncode == 0


async def test_pty_strips_ansi_and_crlf(tmp_path):
    out, _ = await collect(Command([sys.executable, "-c", "print('\\x1b[31mred\\x1b[0m')"], cwd=tmp_path, use_pty=True))
    assert out == ["red"]


async def test_pty_timeout(tmp_path):
    with pytest.raises(RunTimeout):
        await collect(Command([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path, use_pty=True), timeout=1.0)


# ---- queue -------------------------------------------------------------------------------------
async def test_queue_global_limit_and_timeout():
    q = LocalJobQueue(max_concurrency=1, per_user=5, queue_timeout=0.3)
    async with q.slot(1):
        assert q.stats()["running"] == 1
        with pytest.raises(QueueTimeout):
            async with q.slot(2):
                pass
    async with q.slot(2):  # released after the holder left
        pass
    assert q.stats()["running"] == 0 and q.stats()["waiting"] == 0


async def test_queue_per_user_limit_does_not_block_other_users():
    q = LocalJobQueue(max_concurrency=5, per_user=1, queue_timeout=0.3)
    async with q.slot(1):
        with pytest.raises(QueueTimeout):
            async with q.slot(1):
                pass
        async with q.slot(2):  # a different user is unaffected
            pass


async def test_queue_failed_acquire_leaks_nothing():
    q = LocalJobQueue(max_concurrency=1, per_user=2, queue_timeout=0.2)
    async with q.slot(1):
        for _ in range(3):
            with pytest.raises(QueueTimeout):
                async with q.slot(1):
                    pass
    # if the failed attempts had leaked user/global permits, these would time out
    for _ in range(3):
        async with q.slot(1):
            pass
