"""Generic adapter configured from the UI.

provider.extra keys:
  args_template: list[str] | str   e.g. ["-p", "{prompt}", "--model", "{model}"]  ({system} also available)
  output_format: "text" | "json" | "ndjson"
  json_path:     JSONPath to the answer text (json: whole stdout; ndjson: applied to every line)
  stdin:         bool  - send the prompt on stdin (use when the template has no {prompt})
  use_pty:       bool
"""
from __future__ import annotations

import json
import shlex

from jsonpath_ng import parse as jp_parse

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
    resolve_binary,
)


class CustomAdapter(CliAdapter):
    name = "custom"

    def __init__(self) -> None:
        self._fmt = "text"
        self._path = None
        self._held: str | None = None
        self._buf: list[str] = []

    def _template(self, ctx: RunContext) -> list[str]:
        t = ctx.extra.get("args_template", ["{prompt}"])
        return shlex.split(t) if isinstance(t, str) else list(t)

    def build_command(self, req: NormalizedRequest, ctx: RunContext) -> Command:
        self._fmt = ctx.extra.get("output_format", "text")
        if ctx.extra.get("json_path"):
            self._path = jp_parse(ctx.extra["json_path"])
        system = req.system or (ctx.raw_system_prompt if ctx.mode == "raw" else "")
        subst = {"prompt": req.prompt, "model": req.model, "system": system}
        argv = [ctx.binary] + [_fill(a, subst) for a in self._template(ctx)]
        env = {"CLI_API_KEY": ctx.api_key} if ctx.api_key else {}
        use_stdin = bool(ctx.extra.get("stdin"))
        return Command(
            argv=argv, env=env, cwd=ctx.workdir, use_pty=bool(ctx.extra.get("use_pty", False)),
            stdin_data=req.prompt if use_stdin else None,
        )  # fmt: skip

    def _extract(self, obj) -> list[str]:  # noqa: ANN001
        if self._path is None:
            return [obj] if isinstance(obj, str) else []
        return [str(m.value) for m in self._path.find(obj) if m.value is not None]

    def parse_line(self, line: str) -> list[Event]:
        if self._fmt == "text":
            out: list[Event] = []
            if self._held is not None:
                out.append(TextDelta(self._held + "\n"))
            self._held = line
            return out
        if self._fmt == "json":
            self._buf.append(line)
            return []
        # ndjson
        line = line.strip()
        if not line.startswith(("{", "[")):
            return []
        try:
            return [TextDelta(t) for t in self._extract(json.loads(line))]
        except json.JSONDecodeError:
            return []

    def finish(self) -> list[Event]:
        if self._fmt == "text":
            out: list[Event] = [TextDelta(self._held)] if self._held else []
            self._held = None
            return out + [Done()]
        if self._fmt == "json":
            try:
                obj = json.loads("\n".join(self._buf))
            except json.JSONDecodeError:
                return [Error("custom CLI did not produce valid JSON", "bad_output")]
            texts = self._extract(obj)
            if not texts:
                return [Error(f"json_path matched nothing", "bad_output")]
            return [TextDelta("".join(texts)), Done()]
        return [Done()]

    def login_command(self, ctx: RunContext) -> Command | None:
        argv = ctx.extra.get("login_argv")
        return Command(argv=[ctx.binary, *argv], cwd=ctx.workdir, use_pty=True) if argv else None

    def auth_status(self, ctx: RunContext) -> AuthStatus:
        exe = resolve_binary(ctx.binary)
        return AuthStatus(bool(exe), None, None if exe else False, "" if exe else f"{ctx.binary!r} not found")


def _fill(arg: str, subst: dict[str, str]) -> str:
    for k, v in subst.items():
        arg = arg.replace("{" + k + "}", v)
    return arg
