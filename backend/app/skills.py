"""Shared agent skills: read, validate, edit and link the skills in ~/.agentbridge/agents (see skills_home).

Layout of the skills directory:
    skills/<name>/SKILL.md        Agent Skills format (frontmatter: name, description)
    claude-agents/<name>.md       Claude Code subagent wrappers that point at a SKILL.md by absolute path

    instructions/global.md        Instructions every agent gets
    instructions/<agent>.md       Extra instructions for one agent (claude, codex, agy)

Linking mirrors agents/install.sh: every skill is symlinked into each agent's skills
directory and every wrapper into ~/.claude/agents. Existing symlinks are replaced and
real files are left alone. One skill can also be linked into, or unlinked from, chosen
agents; unlinking removes only links that point at that skill.

Instructions are combined (global, then the agent's own) and written into each agent's
global instructions file (~/.claude/CLAUDE.md, ~/.codex/AGENTS.md, ~/.gemini/GEMINI.md)
inside a marked block. Anything outside the block is the user's and is never changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
# Claude Code built-in slash commands; a skill with one of these names is shadowed.
BUILTIN_NAMES = frozenset({
    "agents", "clear", "code-review", "config", "help", "init", "loop", "memory",
    "review", "run", "schedule", "security-review", "simplify",
})
TARGETS = (("claude", "Claude Code"), ("codex", "Codex"), ("agy", "Antigravity"))
INSTRUCTION_NAMES = ("global", *(tid for tid, _ in TARGETS))
BLOCK_BEGIN = "<!-- BEGIN AgentBridge instructions"
BLOCK_END = "<!-- END AgentBridge instructions -->"
# The marker records a hash of what AgentBridge wrote, so a hand edit inside the block is detectable.
BLOCK_RE = re.compile(r"<!-- BEGIN AgentBridge instructions sha256:([0-9a-f]{12})[^\n]*-->\n(.*?)\n?<!-- END AgentBridge instructions -->\n?", re.S)
# ...and the folder it was written from.
SOURCE_RE = re.compile(r"\(Instructions\) or (.+?); changes made here are replaced")


class SkillsError(ValueError):
    """A request the skills directory can't satisfy (bad name, conflict, missing file)."""


# ---------------------------------------------------------------- frontmatter

def parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str, str | None]:
    """Minimal YAML frontmatter parser for `key: value`, quoted values and block scalars.

    Returns (fields, body, error)."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, "File must start with a `---` frontmatter block."
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None, text, "Frontmatter is not closed with `---`."
    fields: dict[str, str] = {}
    fm, i = lines[1:end], 0
    while i < len(fm):
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", fm[i])
        i += 1
        if not m:
            continue
        key, val = m.group(1), m.group(2).rstrip()
        if re.fullmatch(r"[>|][+-]?", val):
            block = []
            while i < len(fm) and (fm[i][:1] in (" ", "\t") or not fm[i].strip()):
                block.append(fm[i].strip())
                i += 1
            if val[0] == ">":  # folded: lines join with spaces, blank lines become newlines
                paras, cur = [], []
                for b in block:
                    if b:
                        cur.append(b)
                    elif cur:
                        paras.append(" ".join(cur))
                        cur = []
                if cur:
                    paras.append(" ".join(cur))
                fields[key] = "\n".join(paras)
            else:
                fields[key] = "\n".join(block).strip()
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            if val[0] == '"':
                try:
                    val = json.loads(val)
                except ValueError:
                    val = val[1:-1]
            else:
                val = val[1:-1].replace("''", "'")
        else:  # plain scalar, possibly continued on indented lines
            cont = []
            while i < len(fm) and fm[i][:1] in (" ", "\t") and fm[i].strip():
                cont.append(fm[i].strip())
                i += 1
            val = " ".join([val, *cont]).strip()
        fields[key] = val
    return fields, "\n".join(lines[end + 1:]), None


def _issue(level: str, msg: str) -> dict:
    return {"level": level, "message": msg}


def check_name(name: object, what: str = "Name") -> str:
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > MAX_NAME:
        raise SkillsError(f"{what} must be lowercase letters, digits and single hyphens (at most {MAX_NAME} characters).")
    return name


# ---------------------------------------------------------------- yaml helpers for templates

def _yaml_plain(s: str) -> str:
    safe = bool(s) and not re.search(r":\s|\s#|^[\s\-?:,\[\]{}#&*!|>'\"%@`]|\s$", s)
    return s if safe else json.dumps(s)


def _fold(s: str, width: int = 76) -> str:
    lines, cur = [], ""
    for w in s.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join("  " + line for line in lines)


@dataclass
class SkillsRepo:
    root: Path
    home: Path = field(default_factory=Path.home)
    codex_home: Path | None = None

    def __post_init__(self):
        self.root = Path(self.root).expanduser().resolve()
        self.home = Path(self.home)
        if self.codex_home is None:
            env = os.environ.get("CODEX_HOME")
            self.codex_home = Path(env) if env else self.home / ".codex"

    # -------------------------------------------------- paths
    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    @property
    def wrappers_dir(self) -> Path:
        return self.root / "claude-agents"

    @property
    def agents_link_dir(self) -> Path:
        return self.home / ".claude" / "agents"

    def target_dirs(self) -> dict[str, Path]:
        return {
            "claude": self.home / ".claude" / "skills",
            "codex": Path(self.codex_home) / "skills",
            "agy": self.home / ".gemini" / "config" / "skills",
        }

    @property
    def instructions_dir(self) -> Path:
        return self.root / "instructions"

    def instruction_targets(self) -> dict[str, Path]:
        return {
            "claude": self.home / ".claude" / "CLAUDE.md",
            "codex": Path(self.codex_home) / "AGENTS.md",
            "agy": self.home / ".gemini" / "GEMINI.md",
        }

    def instruction_file(self, name: str) -> Path:
        if name not in INSTRUCTION_NAMES:
            raise SkillsError(f"Instructions must be one of: {', '.join(INSTRUCTION_NAMES)}.")
        return self.instructions_dir / f"{name}.md"

    def skill_file(self, name: str) -> Path:
        return self.skills_dir / check_name(name, "Skill name") / "SKILL.md"

    def wrapper_file(self, name: str) -> Path:
        return self.wrappers_dir / f"{check_name(name, 'Wrapper name')}.md"

    # -------------------------------------------------- validation
    @staticmethod
    def _spaced_skill_path(text: str) -> str | None:
        """An existing absolute SKILL.md path that contains spaces (e.g. under "My Projects")."""
        for end in (m.end() for m in re.finditer(r"/SKILL\.md", text)):
            line_start = text.rfind("\n", 0, end) + 1
            for s in re.finditer(r"(?<![\w.~/-])/", text[line_start:end]):
                cand = text[line_start + s.start():end]
                if "\0" not in cand and Path(cand).is_file():
                    return cand
        return None

    def wrapper_skill(self, text: str) -> tuple[str | None, str | None]:
        """Returns (absolute SKILL.md path in the wrapper body, skill name if it is in this repo)."""
        m = re.search(r"(?<![\w.~/-])(/[^\s`\"')]+/SKILL\.md)", text)
        path = m.group(1) if m else None
        if not (path and Path(path).is_file()):
            path = self._spaced_skill_path(text) or path
        if not path:
            return None, None
        try:
            parts = Path(path).resolve().relative_to(self.skills_dir).parts
        except ValueError:
            return path, None
        return path, parts[0] if len(parts) == 2 else None

    def validate_wrapper(self, name: str, text: str) -> tuple[list[dict], str | None]:
        out: list[dict] = []
        fm, body, err = parse_frontmatter(text)
        if err:
            return [_issue("error", err)], None
        if not fm.get("name"):
            out.append(_issue("error", "Frontmatter is missing `name`."))
        elif fm["name"] != name:
            out.append(_issue("error", f"`name: {fm['name']}` doesn't match the file name `{name}.md`."))
        if not fm.get("description"):
            out.append(_issue("error", "Frontmatter is missing `description`."))
        path, skill = self.wrapper_skill(body)
        if not path:
            rel = re.search(r"(?<![\w/])((?:\.\.?/|~/)?[\w.-]+(?:/[\w.-]+)*/SKILL\.md)", body)
            out.append(_issue("error", f"`{rel.group(1)}` is a relative path; wrappers must use an absolute path."
                              if rel else "No absolute path to a SKILL.md found."))
        elif not Path(path).is_file():
            out.append(_issue("error", f"`{path}` does not exist."))
        elif skill is None:
            out.append(_issue("warn", f"`{path}` is outside {self.skills_dir}."))
        if "tools" not in fm:
            out.append(_issue("info", "No `tools:` list, so the subagent can use every tool."))
        return out, skill

    def validate_skill(self, name: str, text: str, wrapper_skills: set[str] | None = None) -> list[dict]:
        fm, body, err = parse_frontmatter(text)
        if err:
            return [_issue("error", err)]
        out: list[dict] = []
        fm_name, desc = fm.get("name", ""), fm.get("description", "")
        if not fm_name:
            out.append(_issue("error", "Frontmatter is missing `name`."))
        elif fm_name != name:
            out.append(_issue("error", f"`name: {fm_name}` doesn't match the folder name `{name}`."))
        elif not NAME_RE.match(fm_name) or len(fm_name) > MAX_NAME:
            out.append(_issue("error", f"`name` must be lowercase letters, digits and single hyphens (at most {MAX_NAME})."))
        if fm_name in BUILTIN_NAMES:
            out.append(_issue("warn", f"`{fm_name}` clashes with a Claude Code built-in command."))
        if not desc:
            out.append(_issue("error", "Frontmatter is missing `description`."))
        elif len(desc) > MAX_DESCRIPTION:
            out.append(_issue("error", f"`description` is {len(desc)} characters (limit {MAX_DESCRIPTION})."))
        elif "use when" not in desc.lower():
            out.append(_issue("warn", "`description` should say when to use the skill (\"Use when…\") so agents know when to load it."))
        if not body.strip():
            out.append(_issue("warn", "There are no instructions after the frontmatter."))
        if wrapper_skills is None:
            wrapper_skills = {w["skill"] for w in self._wrappers()}
        if name not in wrapper_skills:
            out.append(_issue("error", "No Claude Code wrapper in claude-agents/ points at this skill."))
        return out

    def validate_instructions(self, name: str, text: str) -> list[dict]:
        self.instruction_file(name)
        out: list[dict] = []
        if not text.strip():
            out.append(_issue("info", "Empty. Every agent gets nothing from here yet." if name == "global"
                              else "Empty. This agent gets only the global instructions."))
        if BLOCK_BEGIN in text or BLOCK_END in text:
            out.append(_issue("error", "Remove the AgentBridge block markers; AgentBridge adds them when it applies the instructions."))
        if text.lstrip().startswith("---") and parse_frontmatter(text)[2] is None:
            out.append(_issue("warn", "Instruction files don't use frontmatter; agents read it as plain text."))
        return out

    def validate(self, kind: str, name: str, text: str) -> dict:
        if kind == "instructions":
            return {"issues": self.validate_instructions(name, text)}
        if kind == "skill":
            return {"issues": self.validate_skill(name, text)}
        if kind == "wrapper":
            issues, skill = self.validate_wrapper(name, text)
            return {"issues": issues, "skill": skill}
        raise SkillsError("kind must be `skill`, `wrapper` or `instructions`.")

    # -------------------------------------------------- state
    @staticmethod
    def link_status(dst: Path, src: Path) -> str:
        if dst.is_symlink():
            try:
                return "linked" if dst.resolve() == src.resolve() else "stale"
            except OSError:
                return "stale"
        return "conflict" if dst.exists() else "missing"

    def _wrappers(self) -> list[dict]:
        out = []
        if not self.wrappers_dir.is_dir():
            return out
        for f in sorted(self.wrappers_dir.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            issues, skill = self.validate_wrapper(f.stem, text)
            out.append({
                "kind": "wrapper", "name": f.stem, "path": str(f), "text": text, "skill": skill,
                "linked": self.link_status(self.agents_link_dir / f.name, f), "issues": issues,
            })
        return out

    def state(self) -> dict:
        wrappers = self._wrappers()
        wrapper_skills = {w["skill"] for w in wrappers if w["skill"]}
        targets = self.target_dirs()
        skills = []
        dirs = sorted(p for p in self.skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")) if self.skills_dir.is_dir() else []
        for d in dirs:
            f = d / "SKILL.md"
            text = f.read_text(encoding="utf-8") if f.is_file() else ""
            skills.append({
                "kind": "skill", "name": d.name, "path": str(f), "text": text,
                "linked": {tid: self.link_status(targets[tid] / d.name, d) for tid, _ in TARGETS},
                "wrappers": [w["name"] for w in wrappers if w["skill"] == d.name],
                "files": sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and p.name != "SKILL.md"),
                "issues": self.validate_skill(d.name, text, wrapper_skills) if f.is_file()
                          else [_issue("error", "SKILL.md is missing.")],
            })
        known = {s["name"] for s in skills}
        for w in wrappers:
            if w["skill"] and w["skill"] not in known:
                w["issues"].append(_issue("error", f"Skill `{w['skill']}` doesn't exist."))
        return {
            "root": str(self.root),
            "skills_dir": str(self.skills_dir),
            "wrappers_dir": str(self.wrappers_dir),
            "user_home": str(Path.home()),  # only for showing paths as ~/...
            "exists": self.root.is_dir(),
            "instructions": self.instructions_state(),
            "targets": [{"id": tid, "label": label, "dir": str(targets[tid])} for tid, label in TARGETS],
            "agents_dir": str(self.agents_link_dir),
            "skills": skills,
            "wrappers": wrappers,
        }

    # -------------------------------------------------- instructions
    def _instruction_text(self, name: str) -> str:
        f = self.instruction_file(name)
        return f.read_text(encoding="utf-8") if f.is_file() else ""

    def composed(self, target: str) -> str:
        """What one agent receives: the global instructions, then its own."""
        parts = (self._instruction_text("global").strip("\n"), self._instruction_text(target).strip("\n"))
        return "\n\n".join(p for p in parts if p.strip())

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def _block(self, body: str) -> str:
        return (f"{BLOCK_BEGIN} sha256:{self._sha(body)}. Edit them in the AgentBridge dashboard (Instructions) or "
                f"{self.instructions_dir}; changes made here are replaced. -->\n{body}\n{BLOCK_END}\n")

    @staticmethod
    def _real(path: Path) -> Path:
        """Write through a symlinked CLAUDE.md/AGENTS.md instead of replacing the link."""
        return path.resolve() if path.is_symlink() else path

    def target_status(self, target: str) -> dict:
        path = self.instruction_targets()[target]
        text = self._real(path).read_text(encoding="utf-8") if path.exists() else ""
        m = BLOCK_RE.search(text)
        own = (text[:m.start()] + text[m.end():]) if m else text
        if not m:
            status = "missing"
        elif self._sha(m.group(2)) != m.group(1):
            status = "edited"  # someone changed the block by hand; applying would lose that
        elif m.group(2) != self.composed(target):
            status = "outdated"
        else:
            status = "applied"
        # The block header names the folder that wrote it, so another AgentBridge (say, a dev copy) can be told apart.
        src = SOURCE_RE.search(m.group(0).split("\n", 1)[0]) if m else None
        return {"status": status, "own_lines": sum(1 for line in own.splitlines() if line.strip()),
                "source": src.group(1) if src else None}

    def instructions_state(self) -> dict:
        targets = self.instruction_targets()
        labels = dict(TARGETS)
        files = []
        for name in INSTRUCTION_NAMES:
            text = self._instruction_text(name)
            files.append({"kind": "instructions", "name": name, "label": "All agents" if name == "global" else labels[name],
                          "path": str(self.instruction_file(name)), "text": text,
                          "issues": self.validate_instructions(name, text)})
        return {
            "dir": str(self.instructions_dir),
            "files": files,
            "targets": [{"id": tid, "label": label, "path": str(targets[tid]), **self.target_status(tid)} for tid, label in TARGETS],
        }

    def apply_instructions(self, only: list[str] | None = None, force: bool = False) -> list[dict]:
        """Write each agent's combined instructions into its block. Hand-edited blocks need force."""
        results = []
        for tid, path in self.instruction_targets().items():
            if only is not None and tid not in only:
                continue
            real = self._real(path)
            text = real.read_text(encoding="utf-8") if real.exists() else ""
            current = self.target_status(tid)["status"]
            body = self.composed(tid)
            if current == "missing" and not body:
                results.append({"path": str(path), "status": "unchanged", "detail": "No instructions for this agent yet."})
                continue
            if current == "applied":
                results.append({"path": str(path), "status": "unchanged"})
                continue
            if not body and current in ("outdated", "edited"):
                results.append({"path": str(path), "status": "skipped",
                                "detail": "These instructions are empty, so the block already there was left alone. Use Unlink to remove it."})
                continue
            if current == "edited" and not force:
                results.append({"path": str(path), "status": "skipped",
                                "detail": "The AgentBridge block was edited by hand. Copy anything you want to keep, then overwrite."})
                continue
            block = self._block(body)
            m = BLOCK_RE.search(text)
            if m:
                new = text[:m.start()] + block + text[m.end():]
            elif text.strip():
                new = text.rstrip("\n") + "\n\n" + block
            else:
                new = block
            self._atomic_write(real, new)
            results.append({"path": str(path), "status": "updated" if m else "added"})
        return results

    def remove_instructions(self, target: str) -> dict:
        """Take the AgentBridge block out of one agent's file and leave the rest as it was."""
        path = self.instruction_targets().get(target)
        if path is None:
            raise SkillsError(f"Unknown agent `{target}`.")
        real = self._real(path)
        text = real.read_text(encoding="utf-8") if real.exists() else ""
        m = BLOCK_RE.search(text)
        if not m:
            return {"path": str(path), "status": "unchanged"}
        before, after = text[:m.start()].rstrip("\n"), text[m.end():].lstrip("\n")
        rest = before + ("\n\n" if before and after else "") + after
        self._atomic_write(real, rest + ("\n" if rest and not rest.endswith("\n") else ""))
        return {"path": str(path), "status": "removed"}

    # -------------------------------------------------- writes
    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".skills-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            os.chmod(tmp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def save(self, kind: str, name: str, text: str, base: str | None = None) -> None:
        if not isinstance(text, str):
            raise SkillsError("`text` is required.")
        if kind == "instructions":
            path = self.instruction_file(name)
            if any(i["level"] == "error" for i in self.validate_instructions(name, text)):
                raise SkillsError("Remove the AgentBridge block markers before saving.")
        elif kind == "skill":
            path = self.skill_file(name)
            if not path.parent.is_dir():
                raise SkillsError(f"Skill `{name}` doesn't exist.")
        elif kind == "wrapper":
            path = self.wrapper_file(name)
            if not path.is_file():
                raise SkillsError(f"Wrapper `{name}` doesn't exist.")
        else:
            raise SkillsError("kind must be `skill`, `wrapper` or `instructions`.")
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if base is not None and current != base:
            raise SkillsError("This file changed on disk after you opened it. Reload to get the latest version, then reapply your edit.")
        if kind == "instructions":
            # Agents already using the shared instructions follow the edit; new or hand-edited ones wait for Apply.
            was = {tid: self.target_status(tid)["status"] for tid, _ in TARGETS}
            self._atomic_write(path, text)
            keep = [tid for tid, st in was.items() if st in ("applied", "outdated") and (name == "global" or tid == name)]
            if keep:
                self.apply_instructions(keep)
            return
        self._atomic_write(path, text)

    def skill_template(self, name: str, description: str) -> str:
        title = name.replace("-", " ").capitalize()
        return (f"---\nname: {name}\ndescription: >-\n{_fold(description)}\n---\n\n# {title}\n\n"
                "Describe the role the agent takes on and the goal.\n\n## Steps\n\n1. \n\n"
                "## Rules\n\n- \n\n## Output\n\nDescribe the final report.\n")

    def wrapper_template(self, name: str, description: str, tools: str, skill: str) -> str:
        tools_line = f"tools: {tools.strip()}\n" if tools.strip() else ""
        return (f"---\nname: {name}\ndescription: {_yaml_plain(description)}\n{tools_line}---\n\n"
                f"Read {self.skills_dir / skill / 'SKILL.md'} and follow it exactly.\n"
                "Return the final report as your response.\n")

    def create(self, name: str, description: str, wrapper_name: str | None, tools: str = "") -> None:
        check_name(name, "Skill name")
        description = " ".join((description or "").split())
        if not description:
            raise SkillsError("A description is required.")
        if len(description) > MAX_DESCRIPTION:
            raise SkillsError(f"The description is longer than {MAX_DESCRIPTION} characters.")
        if (self.skills_dir / name).exists():
            raise SkillsError(f"skills/{name} already exists.")
        if wrapper_name:
            if self.wrapper_file(wrapper_name).exists():
                raise SkillsError(f"claude-agents/{wrapper_name}.md already exists.")
        self._atomic_write(self.skill_file(name), self.skill_template(name, description))
        if wrapper_name:
            self._atomic_write(self.wrapper_file(wrapper_name), self.wrapper_template(wrapper_name, description, tools, name))

    @classmethod
    def _link(cls, src: Path, dst: Path, results: list[dict]) -> None:
        """Symlink dst to src. A link elsewhere is replaced; a real file or folder is left alone."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink():
            if cls.link_status(dst, src) == "linked":
                results.append({"path": str(dst), "status": "unchanged"})
                return
            dst.unlink()
            dst.symlink_to(src, target_is_directory=src.is_dir())
            results.append({"path": str(dst), "status": "relinked"})
        elif dst.exists():
            results.append({"path": str(dst), "status": "skipped", "detail": "A real file or folder is in the way."})
        else:
            dst.symlink_to(src, target_is_directory=src.is_dir())
            results.append({"path": str(dst), "status": "linked"})

    def link_all(self) -> list[dict]:
        """Symlink every skill and wrapper into the agents (same rules as install.sh)."""
        results: list[dict] = []

        def prune(tdir: Path) -> None:
            """Remove links into this repo whose source is gone (a renamed or deleted skill)."""
            if not tdir.is_dir():
                return
            roots = (self.root, self.root.resolve())
            for p in sorted(tdir.iterdir()):
                if not p.is_symlink() or p.exists():
                    continue
                src = Path(os.path.normpath(p.parent / os.readlink(p)))
                if any(src.is_relative_to(r) for r in roots):
                    p.unlink()
                    results.append({"path": str(p), "status": "removed"})

        skills = sorted(p for p in self.skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")) if self.skills_dir.is_dir() else []
        for tdir in self.target_dirs().values():
            prune(tdir)
            for s in skills:
                self._link(s, tdir / s.name, results)
        if self.wrappers_dir.is_dir():
            prune(self.agents_link_dir)
            for w in sorted(self.wrappers_dir.glob("*.md")):
                self._link(w, self.agents_link_dir / w.name, results)
        return results

    def _link_pairs(self, kind: str, name: str, targets: list[str] | None) -> list[tuple[Path, Path]]:
        """(source, link) for one skill in the chosen agents, or for one wrapper in ~/.claude/agents."""
        if kind == "skill":
            src = self.skill_file(name).parent
            if not src.is_dir():
                raise SkillsError(f"Skill `{name}` doesn't exist.")
            dirs = self.target_dirs()
            unknown = [t for t in (targets or []) if t not in dirs]
            if unknown:
                raise SkillsError(f"Unknown agent `{unknown[0]}`. Use one of: {', '.join(dirs)}.")
            return [(src, d / name) for tid, d in dirs.items() if targets is None or tid in targets]
        if kind == "wrapper":
            src = self.wrapper_file(name)
            if not src.is_file():
                raise SkillsError(f"Wrapper `{name}` doesn't exist.")
            return [(src, self.agents_link_dir / src.name)]
        raise SkillsError("kind must be `skill` or `wrapper`.")

    def link_one(self, kind: str, name: str, targets: list[str] | None = None) -> list[dict]:
        """Link one skill into the chosen agents (all when targets is None), or one wrapper into ~/.claude/agents."""
        results: list[dict] = []
        for src, dst in self._link_pairs(kind, name, targets):
            self._link(src, dst, results)
        return results

    def unlink_one(self, kind: str, name: str, targets: list[str] | None = None) -> list[dict]:
        """Remove the links to one skill or wrapper. Only links that point at it are removed; nothing else is touched."""
        results: list[dict] = []
        for src, dst in self._link_pairs(kind, name, targets):
            status = self.link_status(dst, src)
            if status == "linked":
                dst.unlink()
                results.append({"path": str(dst), "status": "removed"})
            elif status == "missing":
                results.append({"path": str(dst), "status": "unchanged"})
            else:
                results.append({"path": str(dst), "status": "skipped", "detail": "A real file or folder is there, not a link, so it was left alone."
                                if status == "conflict" else "This link points somewhere else, so it was left alone."})
        return results


SKILLS_SUBDIRS = ("skills", "claude-agents", "instructions")


def skills_home() -> Path:
    """The one skills folder: ~/.agentbridge/agents, or <AGENTBRIDGE_HOME>/agents.

    It can't be changed from the dashboard, so the installed app and the dev server always edit the
    same skills and instructions. Created on first use.
    """
    base = Path(os.environ.get("AGENTBRIDGE_HOME") or Path.home() / ".agentbridge").expanduser().resolve()
    return base / "agents"


def repo_from_settings() -> SkillsRepo:
    from .config import get_settings
    s = get_settings()
    root = Path(s.skills_dir).expanduser().resolve() if s.skills_dir else skills_home()  # skills_dir: tests only
    for sub in SKILLS_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    if s.agents_home:
        return SkillsRepo(root, home=s.agents_home, codex_home=s.agents_home / ".codex")
    return SkillsRepo(root)
