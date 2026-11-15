"""Native Windows terminal regression tests, run by Windows CI and release builds."""
import os
import sys

import pytest

from app.runner.pty_runner import PtySession, strip_ansi

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='native Windows terminal')


async def test_interactive_terminal_input_resize_and_exit(tmp_path):
    session = PtySession(
        [sys.executable, '-u', '-c', "print('READY', flush=True); value=input(); print('RESULT='+value, flush=True); raise SystemExit(3)"],
        os.environ.copy(), str(tmp_path), interactive=True,
    )
    try:
        await session.start()
        session.resize(35, 120)
        import asyncio
        async with asyncio.timeout(15):
            output = ''
            while 'READY' not in output:
                chunk = await session.read()
                assert chunk is not None
                output += chunk.decode()
            session.write(b'hello\r\n')
            while True:
                chunk = await session.read()
                if chunk is None:
                    break
                output += chunk.decode()
        assert 'RESULT=hello' in strip_ansi(output)
        assert await session.wait(5) == 3
    finally:
        await session.close()


async def test_terminal_timeout_and_close_kills_child(tmp_path):
    import psutil
    session = PtySession([sys.executable, '-c', 'import time; time.sleep(60)'], os.environ.copy(), str(tmp_path), interactive=True)
    await session.start()
    pid = session._windows.pid
    try:
        assert await session.wait(0.1) is None
    finally:
        await session.close()
    assert not psutil.pid_exists(pid)
