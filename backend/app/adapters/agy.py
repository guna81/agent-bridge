from __future__ import annotations

import json
import subprocess

from .base import (
    AuthStatus,
    CliAdapter,
    Command,
    Done,
    Error,
    Event,
    NormalizedRequest,
    RunContext,
    TextDelta,
    ToolEvent,
    Usage,
    resolve_binary,
)
from .claude import DEFAULT_RAW_PROMPT


class AgyAdapter(CliAdapter):
    """Google Antigravity CLI (`agy`).

    Verified on agy 1.4.5 (see docs/cli-notes.md):
      * there is no system-prompt flag, and `.antigravity/system_instructions.md` is ignored;
        `<workdir>/AGENTS.md` IS honoured (injected on top of the built-in prompt);
      * stdout capture works over a pipe and a PTY; we default to a PTY as the task requires.
    """

    name = "agy"

    def __init__(self) -> None:
        self._streamed = False

    def _system_text(self, req: NormalizedRequest, ctx: RunContext) -> str:
        if ctx.mode == "raw":
            return "\n\n".join(s for s in (ctx.raw_system_prompt or DEFAULT_RAW_PROMPT, req.system) if s)
        return req.system

    def prepare_workdir(self, req: NormalizedRequest, ctx: RunContext) -> None:
        text = self._system_text(req, ctx)
        if text:
            (ctx.workdir / "AGENTS.md").write_text(text + "\n", encoding="utf-8")

    def build_command(self, req: NormalizedRequest, ctx: RunContext) -> Command:
        argv = [
            ctx.binary,
            "-p", req.prompt,
            "--output-format", ctx.extra.get("output_format", "stream-json"),
            "--print-timeout", f"{int(ctx.extra.get('print_timeout_s', 300))}s",
            "--disable-slash-commands",
        ]  # fmt: skip
        if req.model:
            argv += ["--model", req.model]
        if ctx.extra.get("effort"):
            argv += ["--effort", str(ctx.extra["effort"])]
        if ctx.mode == "raw":
            # agy has no flag to remove its built-in tools (see docs/raw-mode.md). `--mode plan` is a no-op here:
            # agy 1.5 warns "--mode plan has no effect while slash command expansion is disabled", and we keep
            # --disable-slash-commands because a caller's prompt must never be expanded as a slash command.
            # The sandbox restricts what its terminal tool can do; the run's workdir is a throwaway temp dir.
            if ctx.extra.get("sandbox", True):
                argv += ["--sandbox"]
        else:
            argv += ["--mode", ctx.extra.get("agy_mode", "accept-edits")]
            if ctx.skip_permissions:
                argv += ["--dangerously-skip-permissions"]
            argv += ctx.extra_args
        env: dict[str, str] = {}
        if ctx.auth_mode == "api_key" and ctx.api_key:
            env["GEMINI_API_KEY"] = ctx.api_key
            env["ANTIGRAVITY_API_KEY"] = ctx.api_key
        if ctx.extra.get("base_url"):
            env["GOOGLE_GEMINI_BASE_URL"] = ctx.extra["base_url"]
        return Command(argv=argv, env=env, cwd=ctx.workdir, use_pty=bool(ctx.extra.get("use_pty", True)))

    def parse_line(self, line: str) -> list[Event]:
        line = line.strip()
        if not line.startswith("{"):
            return []
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            return []
        ev = o.get("event")
        if ev == "init":
            return [ToolEvent("init", o)]
        if ev == "step_update":
            su = o.get("step_update", {})
            if su.get("step_type") == "agent_response":
                d = su.get("text_delta")
                if d:
                    self._streamed = True
                    return [TextDelta(d)]
                return []
            return [ToolEvent(su.get("step_type", "step"), o)]
        if ev == "result":
            return self._result(o.get("result", {}))
        if ev is None and "status" in o:  # --output-format json
            return self._result(o)
        return []

    def _result(self, r: dict) -> list[Event]:
        out: list[Event] = []
        if r.get("status") != "SUCCESS":
            return [Error(str(r.get("error") or r.get("response") or r.get("status") or "agy failed"))]
        if not self._streamed and r.get("response"):
            out.append(TextDelta(r["response"]))
        u = r.get("usage") or {}
        out.append(Usage(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)), None))
        out.append(Done("stop"))
        return out

    def login_command(self, ctx: RunContext) -> Command | None:
        # No `auth login` subcommand: launching `agy` with no args starts a TUI sign-in menu
        # ("1. Google OAuth" / "2. Use a Google Cloud project"). We press Enter to pick Google OAuth; it then
        # prints an accounts.google.com URL and waits for the authorization code to be pasted.
        return Command(argv=[ctx.binary], env={"BROWSER": "true"}, cwd=ctx.workdir, use_pty=True, auto_input=[(4.0, "\r")])

    def auth_status(self, ctx: RunContext) -> AuthStatus:
        exe = resolve_binary(ctx.binary)
        if not exe:
            return AuthStatus(False, detail=f"{ctx.binary!r} not found")
        version = _run([exe, "--version"], ctx)
        if ctx.auth_mode == "api_key":
            return AuthStatus(True, version, bool(ctx.api_key), "API key configured" if ctx.api_key else "no API key set")
        # `agy models` needs a signed-in session: "Please sign in to view available models" otherwise.
        out = _run([exe, "models"], ctx, first_line_only=False)
        if "sign in" in out.lower():
            return AuthStatus(True, version, False, "not signed in")
        n = sum(1 for ln in out.splitlines() if "\t" in ln)
        return AuthStatus(True, version, n > 0, f"signed in ({n} models available)" if n else out[:200])


def _run(argv: list[str], ctx: RunContext, first_line_only: bool = True) -> str:
    from ..runner.env import build_env

    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL, env=build_env(ctx), cwd=ctx.workdir)
        text = (p.stdout + p.stderr).strip()
        return (text.splitlines()[0] if text else "") if first_line_only else text
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"
