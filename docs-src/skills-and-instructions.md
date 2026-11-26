# Skills and instructions

Manage shared skills and global instructions for **Claude Code**, **Codex**, and **Antigravity** from one folder in the dashboard.

## Where files live

AgentBridge reads from a single skills folder with this layout:

```text
<skills-folder>/
├── instructions/
│   ├── global.md          # Every agent gets this
│   ├── claude.md          # Extra instructions for Claude Code
│   ├── codex.md           # Extra instructions for Codex
│   └── agy.md             # Extra instructions for Antigravity
├── skills/
│   └── <name>/
│       └── SKILL.md       # Shared skill (YAML frontmatter: name, description)
└── claude-agents/
    └── <name>.md          # Claude Code subagent wrapper pointing at a SKILL.md
```

The folder is always `~/.agentbridge/agents` (or `$AGENTBRIDGE_HOME/agents`), created on first use. It can't be changed from the dashboard, so an installed AgentBridge and a dev server on the same machine edit the same skills and instructions.

## Instructions

Open **Instructions** to write rules every agent should follow once (`global.md`), plus optional per-agent additions (`claude.md`, `codex.md`, `agy.md`) appended after the global instructions.

When you click **Link to agents**, AgentBridge writes each agent's combined instructions into its global instructions file inside a marked block:

| Agent | Target file |
|---|---|
| Claude Code | `~/.claude/CLAUDE.md` |
| Codex | `~/.codex/AGENTS.md` (or `$CODEX_HOME/AGENTS.md`) |
| Antigravity | `~/.gemini/GEMINI.md` |

- **Your own text is preserved.** AgentBridge only touches content between `<!-- BEGIN AgentBridge instructions ... -->` and `<!-- END AgentBridge instructions -->`.
- **Automatic updates after linking.** Once an agent is linked, saving an edit to `global.md` or that agent's file updates its block automatically.
- **Hand-edit protection.** If you edit the AgentBridge block directly in `CLAUDE.md`, `AGENTS.md`, or `GEMINI.md`, AgentBridge detects the change and skips overwriting it until you move your edits into the dashboard and click **overwrite the block**.
- **Empty instructions never replace a block.** If the instructions here are empty, **Link** is hidden and AgentBridge leaves any existing block alone. Use **Unlink** to remove it.
- **Blocks from another folder.** If a block was written from a different instructions folder (for example, the dev server and an installed AgentBridge on one machine), the agent shows **linked from another folder** and names that folder. Linking from here replaces that block.
- **Unlinking.** Click **Unlink** next to any agent to strip only the AgentBridge block and leave the rest of the file unchanged.

## Skills

Open **Skills** to create, validate, edit, and link reusable `SKILL.md` skills and Claude Code subagent wrappers.

- **New skill:** creates `skills/<name>/SKILL.md` from a template, optionally creates a `claude-agents/<wrapper>.md` wrapper with an optional `tools:` list, and can link everything immediately.
- **Live checks:** validates YAML frontmatter (`name` matching the folder, `description` length and trigger guidance), warns when a skill name clashes with a Claude Code built-in slash command, flags a skill that no Claude Code wrapper points at, and checks that wrappers point to an existing absolute `SKILL.md` path.
- **Link to agents:** symlinks every skill and wrapper into each agent so saved edits reach all of them at once:

| Target | Symlink location |
|---|---|
| Claude Code skills | `~/.claude/skills/<name>` |
| Codex skills | `~/.codex/skills/<name>` (or `$CODEX_HOME/skills/<name>`) |
| Antigravity skills | `~/.gemini/config/skills/<name>` |
| Claude Code wrappers | `~/.claude/agents/<name>.md` |

Existing symlinks are updated, and broken links left behind by a renamed or deleted skill are removed. Real files or folders at a target path are never overwritten; AgentBridge skips them and reports the conflict.

To link or unlink one skill, select it and use the buttons next to each agent:

- **Link** or **Unlink** next to an agent adds or removes the link for that agent only. **Relink** fixes a link that points somewhere else.
- **Link to all agents** and **Unlink from all** act on every agent at once.
- A wrapper has the same buttons for `~/.claude/agents`.
- Unlinking removes only a link that points at that skill. The skill's files stay in your skills folder, and AgentBridge never removes a real file or folder or a link to somewhere else.
- **Link to agents** at the top of the page links everything again, including skills you unlinked.

## Editor

Both **Instructions** and **Skills** share the same editor:

- Switch between **Edit**, **Preview** (shows the combined output for per-agent instructions), and **Changes** (diff against disk).
- Press **Save** or `⌘S` / `Ctrl+S` to write changes, or **Revert** to drop them. Unsaved drafts stay in memory while you switch dashboard sections.
- If a file changes on disk while you have unsaved edits, saving is blocked so external changes aren't overwritten.
