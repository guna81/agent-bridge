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

DEFAULT_MODEL = "default"  # pseudo-slug: let the CLI pick (its own default is `auto`)


class GeminiAdapter(CliAdapter):
    """Google Gemini CLI (`gemini`).

    NOT verified against a real binary (it was not installed when this was written). Built from the public
    docs (docs/cli/headless.md, docs/cli/cli-reference.md): `-p/--prompt`, `-m/--model`,
    `--output-format text|json|stream-json`, `--approval-mode default|auto_edit|yolo|plan`; stream-json emits
    init / message / tool_use / tool_result / error / result events. The docs do not give field names, so the
    parser below accepts the common spellings. Run `scripts/smoke_test.py` after installing the CLI.

    System prompt: in raw mode a file is written to the workdir and passed as GEMINI_SYSTEM_MD, which replaces
    the CLI's built-in system prompt. In agent mode the caller's system message goes into GEMINI.md instead
    (project context, added on top of the built-in prompt).
    """

    name = "gemini"

    def __init__(self) -> None:
        self._streamed = False
        self._last_error = ""

    def prepare_workdir(self, req: NormalizedRequest, ctx: RunContext) -> None:
        if ctx.mode == "raw":
            text = "\n\n".join(s for s in (ctx.raw_system_prompt or DEFAULT_RAW_PROMPT, req.system) if s)
            (ctx.workdir / "system.md").write_text(text + "\n", encoding="utf-8")
        elif req.system:
            (ctx.workdir / "GEMINI.md").write_text(req.system + "\n", encoding="utf-8")

    def build_command(self, req: NormalizedRequest, ctx: RunContext) -> Command:
        argv = [ctx.binary, "--output-format", ctx.extra.get("output_format", "stream-json")]
        if req.model and req.model != DEFAULT_MODEL:
            argv += ["-m", req.model]
        if ctx.mode == "raw":
            # `default` approval: in headless mode nothing can approve a tool, so tools that need approval are refused
            argv += ["--approval-mode", ctx.extra.get("approval_mode", "default")]
        elif ctx.skip_permissions:
            argv += ["--approval-mode", "yolo"]
        else:
            argv += ["--approval-mode", ctx.extra.get("approval_mode", "auto_edit")]
        if ctx.extra.get("sandbox"):
            argv += ["--sandbox"]
        argv += ctx.extra_args
        argv += ["-p", req.prompt]
        env: dict[str, str] = {}
        if ctx.auth_mode == "api_key" and ctx.api_key:
            env["GEMINI_API_KEY"] = ctx.api_key
        if ctx.mode == "raw":
            env["GEMINI_SYSTEM_MD"] = str(ctx.workdir / "system.md")
        return Command(argv=argv, env=env, cwd=ctx.workdir, use_pty=bool(ctx.extra.get("use_pty", False)))

    def parse_line(self, line: str) -> list[Event]:
        line = line.strip()
        if not line.startswith("{"):
            return []
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            return []
        t = o.get("type")
        if t == "message":
            if o.get("role") not in (None, "assistant", "model"):
                return []
            text = o.get("content") if isinstance(o.get("content"), str) else o.get("text")
            if not text:
                return []
            if o.get("delta") is False and self._streamed:
                return []  # full message repeated after its deltas
            self._streamed = True
            return [TextDelta(text)]
        if t == "error":
            self._last_error = str(o.get("message") or o.get("error") or "")
            return [ToolEvent("error", o)]  # documented as non-fatal; the result event decides
        if t == "result":
            return self._result(o)
        if t is None and ("response" in o or "error" in o):  # --output-format json: one object
            return self._result(o)
        return [ToolEvent(t or "event", o)]

    def _result(self, o: dict) -> list[Event]:
        err = o.get("error")
        status = str(o.get("status") or ("error" if err else "success")).lower()
        if status not in ("success", "ok", "completed"):
            msg = (err.get("message") if isinstance(err, dict) else err) or self._last_error or f"gemini reported {status}"
            return [Error(str(msg))]
        out: list[Event] = []
        if not self._streamed and isinstance(o.get("response"), str) and o["response"]:
            out.append(TextDelta(o["response"]))
        out.append(_usage(o.get("stats") or o.get("usage") or {}))
        out.append(Done("stop"))
        return out

    def login_command(self, ctx: RunContext) -> Command | None:
        # No login subcommand: starting the CLI interactively shows its sign-in menu.
        return Command(argv=[ctx.binary], env={"BROWSER": "true", "NO_BROWSER": "true"}, cwd=ctx.workdir, use_pty=True)

    def auth_status(self, ctx: RunContext) -> AuthStatus:
        exe = resolve_binary(ctx.binary)
        if not exe:
            return AuthStatus(False, detail=f"{ctx.binary!r} not found")
        version = _version(exe, ctx)
        if ctx.auth_mode == "api_key":
            return AuthStatus(True, version, bool(ctx.api_key), "API key configured" if ctx.api_key else "no API key set")
        from ..runner.env import host_home
        from pathlib import Path

        home = Path(host_home()) if ctx.use_host_home else ctx.home
        ok = (home / ".gemini" / "oauth_creds.json").exists()
        return AuthStatus(True, version, ok, "Google sign-in found" if ok else "no saved Google sign-in")


def _usage(stats: dict) -> Usage:
    """Token counts from a `stats` object. Accepts flat counts or the per-model breakdown."""

    def pick(d: dict, *names: str) -> int:
        return next((int(d[n]) for n in names if isinstance(d.get(n), (int, float))), 0)

    tin = pick(stats, "input_tokens", "prompt_tokens", "promptTokenCount", "input")
    tout = pick(stats, "output_tokens", "candidates_tokens", "candidatesTokenCount", "output")
    if not (tin or tout) and isinstance(stats.get("models"), dict):
        for m in stats["models"].values():
            tok = m.get("tokens", m) if isinstance(m, dict) else {}
            tin += pick(tok, "input_tokens", "prompt", "input")
            tout += pick(tok, "output_tokens", "candidates", "output") + pick(tok, "thoughts")
    return Usage(tin, tout, None)


def _version(exe: str, ctx: RunContext) -> str:
    from ..runner.env import build_env

    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL, env=build_env(ctx), cwd=ctx.workdir)
        text = (p.stdout + p.stderr).strip()
        return text.splitlines()[0] if text else ""
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"
