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
    write_images,
)
from .claude import DEFAULT_RAW_PROMPT

DEFAULT_MODEL = "default"  # pseudo-slug: let the CLI use whatever model its own config selects


class CodexAdapter(CliAdapter):
    """OpenAI Codex CLI (`codex exec`).

    Verified on codex-cli 0.167.0 (see docs/cli-notes.md):
      * `codex exec --json` prints JSONL: thread.started, turn.started, item.completed{item.type=agent_message,text},
        turn.completed{usage}. The answer arrives as whole messages, not token deltas.
      * the prompt is read from stdin when the PROMPT argument is `-`;
      * there is no system-prompt flag; `<workdir>/AGENTS.md` is read as project instructions (added on top of
        Codex's built-in prompt, so raw mode is best-effort, like agy);
      * no cost is reported, only tokens, so cost is estimated from app/pricing.py.
    """

    name = "codex"
    supports_images = True

    def __init__(self) -> None:
        self._n_messages = 0
        self._failed = False

    def _system_text(self, req: NormalizedRequest, ctx: RunContext) -> str:
        if ctx.mode == "raw":
            return "\n\n".join(s for s in (ctx.raw_system_prompt or DEFAULT_RAW_PROMPT, req.system) if s)
        return req.system

    def prepare_workdir(self, req: NormalizedRequest, ctx: RunContext) -> None:
        text = self._system_text(req, ctx)
        if text:
            (ctx.workdir / "AGENTS.md").write_text(text + "\n", encoding="utf-8")

    def _env(self, ctx: RunContext) -> dict[str, str]:
        env: dict[str, str] = {}
        if ctx.auth_mode == "api_key" and ctx.api_key:
            env["CODEX_API_KEY"] = ctx.api_key
            env["OPENAI_API_KEY"] = ctx.api_key
        if not ctx.use_host_home:
            home = ctx.home / ".codex"
            home.mkdir(parents=True, exist_ok=True)
            env["CODEX_HOME"] = str(home)
        return env

    def build_command(self, req: NormalizedRequest, ctx: RunContext) -> Command:
        argv = [ctx.binary, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--color", "never", "-C", str(ctx.workdir)]
        if req.model and req.model != DEFAULT_MODEL:
            argv += ["-m", req.model]
        if ctx.mode == "raw":
            # read-only sandbox: shell commands cannot write or reach the network. User config (MCP servers,
            # profiles) is ignored so the run does not depend on the server user's ~/.codex/config.toml.
            argv += ["-s", "read-only", "--ignore-user-config"]
        elif ctx.skip_permissions:  # explicit per-provider opt-in, agent mode only
            argv += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            argv += ["-s", ctx.extra.get("sandbox", "workspace-write")]
        argv += ctx.extra_args
        for k, v in (ctx.extra.get("config") or {}).items():  # e.g. {"model_reasoning_effort": "low"}
            argv += ["-c", f"{k}={json.dumps(v)}"]
        for path in write_images(req, ctx):
            argv += ["-i", str(path)]
        argv.append("-")  # prompt over stdin: no argv length limit, not visible in `ps`
        return Command(argv=argv, env=self._env(ctx), cwd=ctx.workdir, use_pty=False, stdin_data=req.prompt)

    def parse_line(self, line: str) -> list[Event]:
        line = line.strip()
        if not line.startswith("{"):
            return []
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            return []
        t = o.get("type")
        if t == "item.completed":
            item = o.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                self._n_messages += 1
                return [TextDelta(("\n\n" if self._n_messages > 1 else "") + item["text"])]
            return [ToolEvent(item.get("type", "item"), o)]
        if t == "turn.completed":
            u = o.get("usage") or {}
            # input_tokens already includes cached_input_tokens
            out = int(u.get("output_tokens", 0)) + int(u.get("reasoning_output_tokens", 0))
            return [Usage(int(u.get("input_tokens", 0)), out, None), Done("stop")]
        if t == "turn.failed":
            self._failed = True
            return [Error(str((o.get("error") or {}).get("message") or "codex turn failed"))]
        if t == "error":
            # also emitted for transient "reconnecting" notices; only fatal if no turn completes (non-zero exit)
            return [ToolEvent("error", o)]
        return [ToolEvent(t or "event", o)]

    def login_command(self, ctx: RunContext) -> Command | None:
        argv = [ctx.binary, "login", *ctx.extra.get("login_args", [])]  # e.g. ["--device-auth"] on a headless server
        return Command(argv=argv, env={"BROWSER": "true", **self._env(ctx)}, cwd=ctx.workdir, use_pty=True)

    def auth_status(self, ctx: RunContext) -> AuthStatus:
        exe = resolve_binary(ctx.binary)
        if not exe:
            return AuthStatus(False, detail=f"{ctx.binary!r} not found")
        version = _run([exe, "--version"], ctx, self._env(ctx))
        if ctx.auth_mode == "api_key":
            return AuthStatus(True, version, bool(ctx.api_key), "API key configured" if ctx.api_key else "no API key set")
        out = _run([exe, "login", "status"], ctx, self._env(ctx))
        low = out.lower()
        if "not logged in" in low:
            return AuthStatus(True, version, False, "not logged in")
        if "logged in" in low:
            return AuthStatus(True, version, True, out[:200])
        return AuthStatus(True, version, None, out[:200])


def _run(argv: list[str], ctx: RunContext, env: dict[str, str]) -> str:
    from ..runner.env import build_env

    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL, env=build_env(ctx, env), cwd=ctx.workdir)
        text = (p.stdout + p.stderr).strip()
        return text.splitlines()[0] if text else ""
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"
