from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# ---- events produced by parse_line --------------------------------------------------------------
@dataclass
class TextDelta:
    text: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # only when the CLI reports it


@dataclass
class ToolEvent:
    """Tool use / result / system noise. Dropped from the output stream in raw mode."""

    name: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class Done:
    finish_reason: Literal["stop", "length"] = "stop"


@dataclass
class Error:
    message: str
    code: str = "cli_error"


Event = TextDelta | Usage | ToolEvent | Done | Error


# ---- request / run context ----------------------------------------------------------------------
@dataclass
class Image:
    media_type: str  # image/png | image/jpeg | image/gif | image/webp
    data: bytes

    @property
    def ext(self) -> str:
        return {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(self.media_type, "bin")


@dataclass
class NormalizedRequest:
    model: str  # bare model slug (provider prefix already stripped)
    system: str  # joined system messages ("" if none)
    turns: list[tuple[str, str]]  # (role, text) for non-system messages
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None
    images: list[Image] = field(default_factory=list)
    images_by_turn: dict[int, list[Image]] = field(default_factory=dict)  # indices into turns

    @property
    def prompt(self) -> str:
        return build_prompt(self.turns)


@dataclass
class RunContext:
    provider_name: str
    mode: Literal["raw", "agent"]
    auth_mode: Literal["api_key", "oauth_cli"]
    workdir: Path  # fresh temp dir, deleted after the run
    home: Path  # HOME for the CLI (isolated per user, or the host home if use_host_home)
    binary: str  # resolved executable
    raw_system_prompt: str
    api_key: str | None = None
    skip_permissions: bool = False
    use_host_home: bool = False
    max_budget_usd: float = 0.5
    extra: dict = field(default_factory=dict)
    scratch: Path | None = None  # temp dir for request files when workdir is a persistent project dir

    @property
    def extra_args(self) -> list[str]:
        """Agent mode only: extra CLI flags from provider.extra["extra_args"], e.g. ["--agent", "reviewer"]."""
        a = self.extra.get("extra_args") if self.mode == "agent" else None
        return [str(x) for x in a] if isinstance(a, list) else []


@dataclass
class Command:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)  # merged on top of the minimal base env
    cwd: Path | None = None
    use_pty: bool = False
    stdin_data: str | None = None  # written to stdin then closed; None => /dev/null
    auto_input: list[tuple[float, str]] = field(default_factory=list)  # login PTY only: (delay_s, text) keystrokes


@dataclass
class AuthStatus:
    installed: bool
    version: str | None = None
    authenticated: bool | None = None  # None = unknown
    detail: str = ""


def resolve_binary(binary: str) -> str | None:
    import os
    import shutil

    if os.sep in binary:
        return binary if os.access(binary, os.X_OK) else None
    return shutil.which(binary)


def write_images(req: "NormalizedRequest", ctx: "RunContext") -> list[Path]:
    """Save request images into the run's temp workdir (deleted with it) and return their paths."""
    paths = []
    for i, img in enumerate(req.images):
        f = (ctx.scratch or ctx.workdir) / f"image-{i + 1}.{img.ext}"
        f.write_bytes(img.data)
        paths.append(f)
    return paths


def build_prompt(turns: list[tuple[str, str]]) -> str:
    """Single user turn -> the text itself. Multi-turn -> a labelled transcript."""
    if len(turns) == 1 and turns[0][0] == "user":
        return turns[0][1]
    lines = [
        "Below is a conversation transcript. Reply only with the next assistant message, "
        "continuing from the final user turn. Do not repeat the transcript labels.",
        "",
    ]
    for role, text in turns:
        lines.append(f"[{role}]")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class CliAdapter(ABC):
    """One instance per run, so parse_line may keep per-run state."""

    name: str
    supports_images: bool = False  # can build_command pass req.images to the CLI?

    @abstractmethod
    def build_command(self, req: NormalizedRequest, ctx: RunContext) -> Command: ...

    def prepare_workdir(self, req: NormalizedRequest, ctx: RunContext) -> None:  # noqa: B027
        """Write any instruction/config files into ctx.workdir before the run."""

    @abstractmethod
    def parse_line(self, line: str) -> list[Event]: ...

    @abstractmethod
    def login_command(self, ctx: RunContext) -> Command | None: ...

    @abstractmethod
    def auth_status(self, ctx: RunContext) -> AuthStatus: ...

    def finish(self) -> list[Event]:
        """Called at process EOF; lets text-format adapters flush buffered output."""
        return []
