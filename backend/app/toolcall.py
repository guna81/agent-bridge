"""Client-side function calling, emulated in the prompt.

The CLIs we wrap have no "here are the caller's functions" input, so tool calling is done the way it was
before native tool APIs existed: the function schemas go into the system prompt, the model is told to
answer with <tool_call>{...}</tool_call> blocks, and we parse those back into OpenAI `tool_calls` /
Anthropic `tool_use` blocks. The caller runs the function and sends the result in the next request.

This is best-effort: a model can ignore the format. Responses that use tools are buffered and parsed as a
whole, so streaming with `tools` delivers the answer in one burst at the end.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


_BLOCK = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def instructions(tools: list[ToolSpec], choice: str = "auto") -> str:
    """System-prompt addendum. `choice` is auto | required | <function name>."""
    lines = [
        "# Functions",
        "The caller has defined the functions below. They are NOT your built-in tools: you cannot run them yourself. "
        "To call one, reply with a block in exactly this form and nothing after it:",
        "",
        '<tool_call>{"name": "<function name>", "arguments": {<JSON arguments matching the schema>}}</tool_call>',
        "",
        "Rules: the block must contain one valid JSON object. To call several functions, write several blocks. "
        "Do not wrap the block in code fences. Do not invent function names or results. "
        "The caller will run the function and send the result back as a <tool_result> message; then you continue.",
    ]
    if choice == "required":
        lines.append("You MUST call at least one function in this reply.")
    elif choice not in ("auto", ""):
        lines.append(f"You MUST call the function `{choice}` in this reply.")
    else:
        lines.append("Only call a function when it is needed; otherwise answer normally in plain text.")
    lines.append("")
    for t in tools:
        lines.append(f"## {t.name}")
        if t.description:
            lines.append(t.description)
        lines.append("Arguments JSON schema: " + json.dumps(t.parameters or {"type": "object", "properties": {}}, separators=(",", ":")))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_call(name: str, arguments: dict | str) -> str:
    """How a previous assistant tool call is shown back to the model in the transcript."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {"_raw": arguments}
    return "<tool_call>" + json.dumps({"name": name, "arguments": arguments}, separators=(",", ":")) + "</tool_call>"


def render_result(call_id: str, content: str, name: str = "") -> str:
    attrs = f' id="{call_id}"' + (f' name="{name}"' if name else "")
    return f"<tool_result{attrs}>\n{content}\n</tool_result>"


def parse(text: str, tools: list[ToolSpec]) -> tuple[str, list[ToolCall]]:
    """Split a model reply into (plain text, tool calls). Unknown functions / bad JSON stay in the text."""
    known = {t.name for t in tools}
    calls: list[ToolCall] = []

    def take(m: re.Match) -> str:
        raw = _FENCE.sub("", m.group(1).strip()).strip()
        try:
            o = json.loads(raw)
        except json.JSONDecodeError:
            return m.group(0)
        name = o.get("name") if isinstance(o, dict) else None
        if name not in known:
            return m.group(0)
        args = o.get("arguments", o.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                return m.group(0)
        if not isinstance(args, dict):
            return m.group(0)
        calls.append(ToolCall("call_" + uuid.uuid4().hex[:24], name, args))
        return ""

    rest = _BLOCK.sub(take, text)
    return (rest.strip() if calls else text), calls
