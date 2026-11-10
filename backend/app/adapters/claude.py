from __future__ import annotations

import base64
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
    resolve_binary,
    TextDelta,
    ToolEvent,
    Usage,
)

DEFAULT_RAW_PROMPT = (
    "You are a helpful assistant. Answer directly. Do not mention being a coding agent. "
    "Do not use tools."
)


class ClaudeAdapter(CliAdapter):
    name = "claude"
    supports_images = True

    def __init__(self) -> None:
        self._streamed_this_message = False
        self._produced_text = False

    # ---- command ---------------------------------------------------------------------------
    def build_command(self, req: NormalizedRequest, ctx: RunContext) -> Command:
        argv = [
            ctx.binary,
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--no-session-persistence",
            "--max-budget-usd", f"{ctx.max_budget_usd:g}",
        ]  # fmt: skip
        if req.model:
            argv += ["--model", req.model]

        if ctx.mode == "raw":
            system = "\n\n".join(s for s in (ctx.raw_system_prompt or DEFAULT_RAW_PROMPT, req.system) if s)
            argv += [
                "--system-prompt", system,
                "--tools", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "",
                "--permission-prompts", "none",
                "--disable-slash-commands",
                "--max-turns", "1",
            ]  # fmt: skip
            # --dangerously-skip-permissions is never added in raw mode.
        else:
            if req.system:
                argv += ["--append-system-prompt", req.system]
            argv += ["--permission-prompts", "none"]
            argv += ["--max-turns", str(ctx.extra.get("max_turns", 10))]
            if ctx.extra.get("permission_mode"):
                argv += ["--permission-mode", ctx.extra["permission_mode"]]
            if ctx.extra.get("allowed_tools"):
                argv += ["--allowedTools", ",".join(ctx.extra["allowed_tools"])]
            if ctx.extra.get("disallowed_tools"):
                argv += ["--disallowedTools", ",".join(ctx.extra["disallowed_tools"])]
            if ctx.skip_permissions:  # explicit per-provider opt-in
                argv += ["--dangerously-skip-permissions"]
            argv += ctx.extra_args

        env: dict[str, str] = {"DISABLE_AUTOUPDATER": "1"}
        if ctx.auth_mode == "api_key":
            if ctx.api_key:
                env["ANTHROPIC_API_KEY"] = ctx.api_key
        if not ctx.use_host_home:
            env["CLAUDE_CONFIG_DIR"] = str(ctx.home / ".claude")
        # prompt goes over stdin: avoids argv length limits and leaking it into `ps`
        stdin = req.prompt
        if req.images:
            # images need structured input: one stream-json user message with image + text blocks
            argv += ["--input-format", "stream-json"]
            content = [{"type": "image", "source": {"type": "base64", "media_type": i.media_type,
                                                    "data": base64.b64encode(i.data).decode()}} for i in req.images]  # fmt: skip
            content.append({"type": "text", "text": req.prompt})
            stdin = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        return Command(argv=argv, env=env, cwd=ctx.workdir, use_pty=False, stdin_data=stdin)

    # ---- parsing ---------------------------------------------------------------------------
    def parse_line(self, line: str) -> list[Event]:
        line = line.strip()
        if not line.startswith("{"):
            return []
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            return []
        t = o.get("type")

        if t == "stream_event":
            ev = o.get("event", {})
            et = ev.get("type")
            if et == "message_start":
                self._streamed_this_message = False
            elif et == "content_block_delta":
                d = ev.get("delta", {})
                if d.get("type") == "text_delta" and d.get("text"):
                    self._streamed_this_message = True
                    self._produced_text = True
                    return [TextDelta(d["text"])]
            elif et == "content_block_start":
                cb = ev.get("content_block", {})
                if cb.get("type") == "tool_use":
                    return [ToolEvent(cb.get("name", "tool"), o)]
            return []

        if t == "assistant":
            out: list[Event] = []
            for block in o.get("message", {}).get("content", []):
                if block.get("type") == "text" and not self._streamed_this_message and block.get("text"):
                    self._produced_text = True
                    out.append(TextDelta(block["text"]))
                elif block.get("type") == "tool_use":
                    out.append(ToolEvent(block.get("name", "tool"), block))
            return out

        if t in ("system", "user", "rate_limit_event"):
            return [ToolEvent(t, o)]

        if t == "result":
            return self._parse_result(o)
        return []

    def _parse_result(self, o: dict) -> list[Event]:
        out: list[Event] = []
        u = o.get("usage") or {}
        prompt_tokens = (
            int(u.get("input_tokens", 0))
            + int(u.get("cache_creation_input_tokens", 0))
            + int(u.get("cache_read_input_tokens", 0))
        )
        out.append(Usage(prompt_tokens, int(u.get("output_tokens", 0)), o.get("total_cost_usd")))
        subtype = o.get("subtype", "")
        if o.get("is_error") or (subtype.startswith("error") and subtype != "error_max_turns"):
            msg = o.get("result") or o.get("error") or subtype or "claude reported an error"
            code = "budget_exceeded" if "budget" in subtype or "budget" in str(msg).lower() else "cli_error"
            out.append(Error(str(msg), code))
        else:
            out.append(Done("length" if o.get("stop_reason") == "max_tokens" else "stop"))
        return out

    # ---- auth ------------------------------------------------------------------------------
    def login_command(self, ctx: RunContext) -> Command | None:
        env = {"BROWSER": "true"}  # never try to open a browser on the server
        if not ctx.use_host_home:
            env["CLAUDE_CONFIG_DIR"] = str(ctx.home / ".claude")
        # prints an OAuth URL, then "Paste code here if prompted >" on stdin
        return Command(argv=[ctx.binary, "auth", "login"], env=env, cwd=ctx.workdir, use_pty=True)

    def auth_status(self, ctx: RunContext) -> AuthStatus:
        exe = resolve_binary(ctx.binary)
        if not exe:
            return AuthStatus(installed=False, detail=f"{ctx.binary!r} not found")
        version = _run([exe, "--version"], ctx)
        if ctx.auth_mode == "api_key":
            return AuthStatus(True, version, bool(ctx.api_key), "API key configured" if ctx.api_key else "no API key set")
        out = _run([exe, "auth", "status", "--json"], ctx)
        try:
            data = json.loads(out or "{}")
            ok = bool(data.get("loggedIn"))
            return AuthStatus(True, version, ok, data.get("email") or data.get("authMethod") or "")
        except json.JSONDecodeError:
            return AuthStatus(True, version, None, (out or "")[:200])


def _run(argv: list[str], ctx: RunContext) -> str:
    from ..runner.env import build_env

    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
            env=build_env(ctx, {"CLAUDE_CONFIG_DIR": str(ctx.home / ".claude")} if not ctx.use_host_home else {}),
            cwd=ctx.workdir,
        )  # fmt: skip
        return (p.stdout or p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"
