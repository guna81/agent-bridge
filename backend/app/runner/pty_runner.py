"""PTY-backed subprocess. Used (a) to run CLIs that misbehave without a TTY, (b) for interactive login."""
from __future__ import annotations

import asyncio
import os
import re
import signal
import struct
import subprocess

try:
    import fcntl
    import pty
    import termios
except ImportError:
    fcntl = None  # type: ignore
    pty = None  # type: ignore
    termios = None  # type: ignore

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


_URL = re.compile(r"https?://[^\s\"'<>\x00-\x1f]+")


def extract_urls(text: str) -> list[str]:
    """URLs in terminal output (ANSI already stripped). Re-joins a URL that a TUI hard-wrapped mid-token."""
    lines = text.replace("\r", "").split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        for m in _URL.finditer(line):
            url = m.group(0)
            if m.end() == len(line.rstrip()):  # URL runs to the end of the line: it may continue below
                j = i + 1
                while j < len(lines) and (cont := lines[j].strip()) and not re.search(r"\s", cont) and "://" not in cont:
                    url += cont
                    j += 1
            url = url.rstrip(".,)")
            if url not in out:
                out.append(url)
    return out


class PtySession:
    def __init__(self, argv: list[str], env: dict[str, str], cwd: str | None, *, interactive: bool, rows: int = 30, cols: int = 120):
        self.argv, self.env, self.cwd, self.interactive = argv, env, cwd, interactive
        self.rows, self.cols = rows, cols
        self._proc: subprocess.Popen | None = None
        self._master = -1
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.returncode: int | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
        stdin = slave if self.interactive else subprocess.DEVNULL
        try:
            self._proc = subprocess.Popen(
                self.argv, stdin=stdin, stdout=slave, stderr=slave, cwd=self.cwd, env=self.env,
                start_new_session=True, close_fds=True,
            )  # fmt: skip
        finally:
            os.close(slave)
        self._master = master
        os.set_blocking(master, False)
        self._loop.add_reader(master, self._on_readable)

    def _on_readable(self) -> None:
        try:
            data = os.read(self._master, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:  # EIO: slave side closed
            data = b""
        if data:
            self._q.put_nowait(data)
        else:
            self._remove_reader()
            self._q.put_nowait(None)

    def _remove_reader(self) -> None:
        if self._loop and self._master >= 0:
            try:
                self._loop.remove_reader(self._master)
            except Exception:  # noqa: BLE001
                pass

    async def read(self) -> bytes | None:
        return await self._q.get()

    def write(self, data: bytes) -> None:
        if self._master >= 0:
            try:
                os.write(self._master, data)
            except OSError:
                pass

    def resize(self, rows: int, cols: int) -> None:
        if self._master >= 0:
            fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def wait(self, timeout: float = 5.0) -> int | None:
        assert self._proc is not None
        loop = asyncio.get_running_loop()
        try:
            self.returncode = await asyncio.wait_for(loop.run_in_executor(None, self._proc.wait), timeout)
        except asyncio.TimeoutError:
            return None
        return self.returncode

    async def close(self) -> None:
        self._remove_reader()
        p = self._proc
        if p is not None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    if hasattr(os, "killpg"):
                        os.killpg(p.pid, sig)
                    else:
                        os.kill(p.pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
                if sig == signal.SIGTERM:
                    await asyncio.sleep(0.2)
            loop = asyncio.get_running_loop()
            try:
                self.returncode = await asyncio.wait_for(loop.run_in_executor(None, p.wait), 3)
            except asyncio.TimeoutError:
                pass
        if self._master >= 0:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = -1
