# CLI notes (captured from the real binaries)

Captured 2026-10-25 on macOS arm64. Where the task notes disagree with this output, **this output wins**.

## Versions
```
claude: 2.1.310 (Claude Code)
agy:    1.4.7
```

## `claude --help` (verbatim; `claude -p --help` prints the same text)
```
Usage: claude [options] [command] [prompt]

Claude Code - starts an interactive session by default, use -p/--print for
non-interactive output

Arguments:
  prompt                                Your prompt

Options:
  --add-dir <directories...>            Additional directories to allow tool
                                        access to
  --agent <agent>                       Agent for the current session. Overrides
                                        the 'agent' setting.
  --agents <json-or-file>               JSON object defining custom agents, or
                                        with --print the path to a file that
                                        holds one (e.g. '{"reviewer":
                                        {"description": "Reviews code",
                                        "prompt": "You are a code reviewer"}}')
  --allow-dangerously-skip-permissions  Enable bypassing all permission checks
                                        as an option, without it being enabled
                                        by default. Recommended only for
                                        sandboxes with no internet access.
  --allowedTools, --allowed-tools <tools...>
      Comma or space-separated list of tool names to allow (e.g. "Bash(git *)
      Edit")
  --append-system-prompt <prompt>       Append a system prompt to the default
                                        system prompt
  --autocompact <auto|tokens>           Auto-compact window size (auto, or
                                        100k–1M tokens)
  --ax-screen-reader                    Render screen-reader friendly output
                                        (flat text, no decorative borders or
                                        animations).
  --bg, --background                    Start the session in the background and
                                        return immediately. Prints the id that
                                        `claude attach`, `logs`, `stop` and `rm`
                                        take; `claude agents` lists them. With
                                        --resume <session-id>, continues that
                                        session in the background under the same
                                        ID, or starts a copy and says so when
                                        the session is already running
  --bare                                Minimal mode: skip hooks (those defined
                                        in settings and by installed plugins;
                                        features built into Claude Code are
                                        unaffected), LSP, plugin sync,
                                        attribution, auto-memory, background
                                        prefetches, keychain reads, and
                                        CLAUDE.md auto-discovery. Sets
                                        CLAUDE_CODE_SIMPLE=1. Anthropic auth is
                                        strictly ANTHROPIC_API_KEY or
                                        apiKeyHelper via --settings (OAuth and
                                        keychain are never read). 3P providers
                                        (Bedrock/Vertex/Foundry) use their own
                                        credentials. Skills still resolve via
                                        /skill-name. Explicitly provide context
                                        via: --system-prompt[-file],
                                        --append-system-prompt[-file], --add-dir
                                        (CLAUDE.md dirs), --mcp-config,
                                        --settings, --agents, --plugin-dir.
  --betas <betas...>                    Beta headers to include in API requests
                                        (API key users only)
  --brief                               Enable SendUserMessage tool for
                                        agent-to-user communication
  --chrome                              Enable Claude in Chrome integration
  --cloud [description|session_id|url]  Create a cloud session with the given
                                        description, or attach to an existing
                                        one by session ID or claude.ai/code URL
  -c, --continue                        Continue the most recent conversation in
                                        the current directory
  --dangerously-skip-permissions        Bypass all permission checks.
                                        Recommended only for sandboxes with no
                                        internet access.
  -d, --debug [filter]                  Enable debug mode with optional category
                                        filtering (e.g., --debug=hooks,mcp or
                                        --debug='!hooks,!mcp')
  --debug-file <path>                   Write debug logs to a specific file path
                                        (implicitly enables debug mode)
  --desktop                             Open in the Claude Desktop app instead
                                        of the terminal (with --continue or
                                        --resume <id> to pick the session)
  --disable-slash-commands              Disable all skills and commands
  --disallowedTools, --disallowed-tools <tools...>
      Comma or space-separated list of tool names to deny (e.g. "Bash(git *)
      Edit")
  --effort <level>                      Effort level for the current session
                                        (low, medium, high, xhigh, max)
  --environment <environment_id>        Create a new cloud session that runs on
                                        the given self-hosted environment
                                        (ccpool_...).
  --exclude-dynamic-system-prompt-sections
      Move per-machine sections (cwd, env info, memory paths, git status) from
      the system prompt into the first user message. Improves cross-user
      prompt-cache reuse. Only applies with the default system prompt (ignored
      with --system-prompt). (default: false)
  --fallback-model <model>              Enable automatic fallback to specified
                                        model(s) when the default model is
                                        overloaded or not available. Accepts a
                                        comma-separated list to try each in
                                        order. Re-tries the primary at the start
                                        of each user turn.
  --file <specs...>                     File resources to download at startup.
                                        Format: file_id:relative_path (e.g.,
                                        --file file_abc:doc.txt
                                        file_def:img.png)
  --fork-session                        When resuming, create a new session ID
                                        instead of reusing the original (use
                                        with --resume or --continue)
  --forward-subagent-text               Forward subagent text and thinking
                                        blocks as assistant/user messages with
                                        parent_tool_use_id set (only works with
                                        --print and --output-format=stream-json)
  --from-pr [value]                     Resume a session linked to a PR by PR
                                        number/URL, or open interactive picker
                                        with optional search term
  -h, --help                            Display help for command
  --ide                                 Automatically connect to IDE on startup
                                        if exactly one valid IDE is available
  --include-hook-events                 Include all hook lifecycle events in the
                                        output stream (only works with
                                        --output-format=stream-json)
  --include-partial-messages            Include partial message chunks as they
                                        arrive (only works with --print and
                                        --output-format=stream-json)
  --input-format <format>               Input format (only works with --print):
                                        "text" (default), or "stream-json"
                                        (realtime streaming input) (choices:
                                        "text", "stream-json")
  --json-schema <schema>                JSON Schema for structured output
                                        validation (only works with --print).
                                        Example:
                                        {"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}
  --max-budget-usd <amount>             Maximum dollar amount to spend on API
                                        calls (only works with --print)
  --mcp-config <configs...>             Load MCP servers from JSON files or
                                        strings (space-separated)
  --model <model>                       Model for the current session. Provide
                                        an alias for the latest model (e.g.
                                        'fable', 'opus', or 'sonnet') or a
                                        model's full name.
  -n, --name <name>                     Set a display name for this session
                                        (shown in the prompt box, /resume
                                        picker, and terminal title)
  --no-chrome                           Disable Claude in Chrome integration
  --no-session-persistence              Disable session persistence - sessions
                                        will not be saved to disk and cannot be
                                        resumed (only works with --print)
  --output-format <format>              Output format (only works with --print):
                                        "text" (default), "json" (single
                                        result), or "stream-json" (realtime
                                        streaming) (choices: "text", "json",
                                        "stream-json")
  --permission-mode <mode>              Permission mode to use for the session
                                        (choices: "acceptEdits", "auto",
                                        "bypassPermissions", "manual",
                                        "dontAsk", "plan")
  --permission-prompts <target>         Who answers permission prompts with
                                        --print: "host" (the SDK host or
                                        --permission-prompt-tool) or "none"
                                        (nobody: anything that would prompt is
                                        denied automatically; the permission
                                        mode still decides everything else)
                                        (choices: "host", "none", default:
                                        "host")
  --plugin-dir <path>                   Load a plugin from a directory or .zip
                                        for this session only; a folder of
                                        plugins loads each child (repeatable:
                                        --plugin-dir A --plugin-dir B.zip)
                                        (default: [])
  --plugin-url <url>                    Fetch a plugin .zip from a URL for this
                                        session only (repeatable: --plugin-url A
                                        --plugin-url B) (default: [])
  -p, --print                           Print response and exit (useful for
                                        pipes). Note: The workspace trust dialog
                                        is skipped when Claude is run in
                                        non-interactive mode (via -p, or when
                                        stdout is not a TTY, e.g. piped or
                                        redirected output). Only use this in
                                        directories you trust. Settings files
                                        that fail validation are silently
                                        ignored in this mode (no error dialog is
                                        shown).
  --prompt-suggestions [value]          Enable prompt suggestions. In print/SDK
                                        mode, emits a prompt_suggestion message
                                        after each turn with a predicted next
                                        user prompt (choices: "true", "false",
                                        "1", "0", "yes", "no", "on", "off",
                                        preset: "true")
  --remote-control [name]               Start an interactive session with Remote
                                        Control enabled (optionally named)
  --remote-control-session-name-prefix <prefix>
      Prefix for auto-generated Remote Control session names (default: hostname)
  --replay-user-messages                Re-emit user messages from stdin back on
                                        stdout for acknowledgment (only works
                                        with --input-format=stream-json and
                                        --output-format=stream-json)
  --restricted                          Restricted mode: removes the built-in
                                        tools that run commands or code (Bash,
                                        PowerShell and the other code-running
                                        tools) and WebFetch unless --tools names
                                        them, and ignores user, project and
                                        local settings files (managed settings
                                        and --settings still apply; add
                                        --strict-mcp-config to skip MCP servers
                                        too). Also confines the file tools to
                                        the working directories (--add-dir
                                        included), refuses bypassPermissions,
                                        and lets only a person or the configured
                                        permission handler approve writes to
                                        settings, git and tool-configuration
                                        files.
  -r, --resume [value]                  Resume a conversation by session ID or
                                        name, or open interactive picker with
                                        optional search term
  --safe-mode                           Start with all customizations
                                        (CLAUDE.md, skills, installed plugins,
                                        hooks, MCP servers, custom commands and
                                        agents, output styles, workflows, custom
                                        themes, keybindings, and more) disabled
                                        — useful for troubleshooting a broken
                                        configuration. Admin-managed (policy)
                                        settings still apply. Auth, model
                                        selection, built-in tools and plugins,
                                        and permissions work normally. Sets
                                        CLAUDE_CODE_SAFE_MODE=1.
  --session-id <uuid>                   Use a specific session ID for the
                                        conversation (must be a valid UUID)
  --setting-sources <sources>           Comma-separated list of setting sources
                                        to load (user, project, local).
  --settings <file-or-json>             Path to a settings JSON file or a JSON
                                        string to load additional settings from
  --strict-mcp-config                   Only use MCP servers from --mcp-config,
                                        ignoring all other MCP configurations
  --system-prompt <prompt>              System prompt to use for the session
  --system-prompt-snapshot <on|off>     Record the system prompt once per
                                        conversation and reuse it verbatim on
                                        every request and resume. on (the
                                        default, except under --bare outside
                                        cloud and background sessions): the
                                        prompt is rendered on the conversation's
                                        first request — a --system-prompt or
                                        --append-system-prompt included — sent,
                                        and recorded; every later request and
                                        resume sends the record as-is, even when
                                        a later launch passes different text,
                                        until the conversation is compacted.
                                        off: never record; the prompt is
                                        rendered fresh every request (for
                                        iterating on prompt text). (choices:
                                        "on", "off")
  --teleport [session]                  Resume a teleport session, optionally
                                        specify session ID
  --tmux                                Create a tmux session for the worktree
                                        (requires --worktree). Uses iTerm2
                                        native panes when available; use
                                        --tmux=classic for traditional tmux.
  --tools <tools...>                    Specify the list of available tools from
                                        the built-in set. Use "" to disable all
                                        tools, "default" to use the default set,
                                        or specify tool names (e.g.
                                        "Bash,Edit,Read").
  --verbose                             Override verbose mode setting from
                                        config
  -v, --version                         Output the version number
  -w, --worktree [name]                 Create a new git worktree for this
                                        session (optionally specify a name)

Commands:
  agents [options]                      Manage background agents
  attach <id|name>                      Open a background session in this
                                        terminal. <id> is the short id that
                                        `claude --bg` prints and `claude agents`
                                        lists. Part of the session name works
                                        too
  auth                                  Manage authentication
  auto-mode                             Inspect or reset auto mode classifier
                                        configuration
  doctor                                Check the health of your Claude Code
                                        installation. Reads settings files in
                                        the current directory without a trust
                                        prompt. For a full checkup that can also
                                        fix issues, run /doctor in a session.
  gateway [options]                     Run the enterprise auth/telemetry
                                        gateway
  import [options] [source]             Import config from another AI coding
                                        agent into Claude Code
  install [options] [target]            Install Claude Code native build. Use
                                        [target] to specify version (stable,
                                        latest, or specific version)
  logs <id|name>                        Print a background session's recent
                                        terminal output
  mcp                                   Configure and manage MCP servers
  plugin|plugins                        Manage Claude Code plugins
  purge [options] [path]                Delete all Claude Code state for a
                                        project (transcripts, tasks, file
                                        history, config entry)
  respawn [options] [id]                Restart a background session, or all of
                                        them with --all, so it runs the current
                                        Claude Code version
  rm <id>                               Delete a background session, and its
                                        worktree when that is safe. Works on
                                        sessions that have already exited
  setup-token                           Set up a long-lived authentication token
                                        (requires Claude subscription)
  stop|kill <id>                        Stop a background session. Its
                                        conversation is kept: `claude attach
                                        <id>` opens it again, `claude --resume`
                                        works once it is stopped
  ultrareview [options] [target]        Run a cloud-hosted multi-agent code
                                        review of the current branch (or a PR
                                        number / base branch) and print the
                                        findings
  update|upgrade                        Check for updates and install if
                                        available; package-manager installs
                                        update through the package manager
```

## `agy --help` (verbatim)
```
Usage of agy:
  --add-dir                       Add a directory to the workspace (repeatable) (default [])
  --agent                         Agent for the current CLI session
  -c                              Short alias for --continue
  --continue                      Continue the most recent conversation
  --conversation                  Resume a previous conversation by ID
  --dangerously-skip-permissions  Auto-approve all tool permission requests without prompting
  --disable-slash-commands        Disable slash command and skill expansion in print mode
  --effort                        Reasoning effort for the current CLI session (low|medium|high|xhigh|max)
  -i                              Short alias for --prompt-interactive
  --input-format                  Input format for print mode (text, stream-json). stream-json reads one NDJSON message per line from stdin and runs a turn for each; it requires --output-format stream-json (default text)
  --json-schema                   Optional JSON schema string or path to a schema file to enforce structured output (for stream-json, only applicable to the final result)
  --log-file                      Override CLI log file path
  --mode                          Set the agent execution mode for this session (accept-edits, auto, plan)
  --model                         Model for the current CLI session
  --new-project                   Create a new project for this session
  --output-format                 Output format for print mode (text, json, stream-json) (default text)
  -p                              Short alias for --print
  --print                         Run a single prompt non-interactively and print the response
  --print-timeout                 Optional time limit for print mode; 0 waits until the turn completes (default 0s)
  --project                       Project ID or project name for the current CLI session
  --prompt                        Alias for --print
  --prompt-interactive            Run an initial prompt interactively and continue the session
  --remote-control                Create a remote connection for the CLI session on start up
  --sandbox                       Run in a sandbox with terminal restrictions enabled

Available subcommands:
  agent           List available agents
  agents          List available agents
  changelog       Show changelog and release notes
  help            Show help for subcommands
  install         Configure environment paths and shell settings
  mcp             Manage MCP servers (add, remove, list, enable, disable)
  mic-serve       Serve this machine's microphone to a CLI on another host
  models          List available models
  plugin          Manage plugins (install, uninstall, list, enable, disable)
  plugins         Alias for plugin
  remote-control  Manage the remote-control background daemon (start, status, stop)
  update          Update CLI
```

## `agy models`
```
Fetching available models...
gemini-3.8-flash-high	Gemini 3.8 Flash (High)
gemini-3.8-flash-medium	Gemini 3.8 Flash (Medium)
gemini-3.8-flash-low	Gemini 3.8 Flash (Low)
claude-sonnet-4-6	Claude Sonnet 4.6 (Thinking)
claude-opus-4-6-thinking	Claude Opus 4.6 (Thinking)
gpt-oss-120b-medium	GPT-OSS 120B (Medium)
```

## `agy mcp add --help`
```
Usage: agy mcp add [flags] <name> <commandOrUrl> [args...]

Add or update an MCP server configuration

Flags:
  -H        Short alias for --header (default [])
  -e        Short alias for --env (default [])
  --env     Environment variable KEY=value (repeatable) (default [])
  -h        Show help
  --header  HTTP header Key: Value (repeatable) (default [])
  --help    Show help
  -t        Short alias for --type (default stdio)
  --type    Server type: 'stdio' or 'http' (default stdio)

Arguments:
  <name>          Unique name for the server.
  <commandOrUrl>  Executable for a stdio server, or the URL for an http server.
  [args...]       Arguments passed to the stdio command.

Notes:
  Flags must come before <name>; a flag placed after it is rejected.
  http/https URLs are detected automatically, so --type is usually unnecessary.
  Use -- before the command to pass a command or args that begin with '-'.

Examples:
  agy mcp add fs npx -y @modelcontextprotocol/server-filesystem /work
  agy mcp add --header "Authorization: Bearer TOKEN" api https://example.com/mcp
  agy mcp add --env GITHUB_TOKEN=xxx gh -- docker run -i ghcr.io/github/mcp
```

---

# Empirical findings (verified by running the CLIs)

## Differences from the task notes

| Topic | Task notes | What the binaries actually do |
|---|---|---|
| `claude --max-turns` | listed | **Absent from `--help`**, but still accepted (it parsed and the run reached the budget check). Treat as hidden/undocumented; we also bound cost with `--max-budget-usd` and disable tools. |
| `claude` stdin | – | Prints `Warning: no stdin data received in 3s` unless stdin is explicitly redirected. The runner always passes `stdin=DEVNULL`. |
| `claude --bare` | – | Exists, but **only** authenticates with `ANTHROPIC_API_KEY`/apiKeyHelper (never OAuth, never keychain). Raw mode therefore uses `--setting-sources ""` + `--strict-mcp-config` instead, so it works with both auth modes. |
| `agy --print-timeout` default | 5m | **0s** = wait until the turn completes. We pass our own timeout and kill the process group. |
| `agy --mode` | `accept-edits\|plan` | `accept-edits`, `auto`, `plan` |
| **"agy -p drops stdout without a TTY"** | reported bug | **Not reproducible on agy 1.4.5.** `text`, `json` and `stream-json` all captured correctly over a plain pipe *and* a PTY (PTY adds `\r\n`). The adapter still supports `use_pty` (default on for agy, as a safety net for other versions); `scripts/smoke_test.py` runs both modes and reports which one worked. |
| agy system prompt via `<workdir>/.antigravity/system_instructions.md` | third-party claim | **Does NOT work** (model ignored a `ZEBRA7` instruction; replied "I am Antigravity, an AI coding assistant…"). |
| agy workspace instructions | – | **`<workdir>/AGENTS.md`, `GEMINI.md` and `.agents/rules/*.md` DO work** (reply started with `ZEBRA7` and said "I am Gemini, a large language model trained by Google"). These are injected *on top of* Antigravity's built-in system prompt, so they steer but do not replace it. |
| agy MCP config | `<workdir>/.antigravity/settings.json` | Not verified; MCP is managed with `agy mcp add/list/remove/enable/disable`. `agy mcp list` on a fresh state says "No MCP servers configured", so an empty MCP set is the default in a fresh isolated HOME. |
| agy tools | "restrict if documented" | No flag restricts tools. The `init` event of stream-json lists **60 built-in tools** (browser_*, run_command, write_to_file, call_mcp_tool …) regardless of `--mode plan`. Raw mode for agy is best-effort only. Baseline cost is ~7.6k input tokens per call. |
| agy models | gemini only | `agy models` returns gemini-3.8-flash-{high,medium,low}, claude-sonnet-4-6, claude-opus-4-6-thinking, gpt-oss-120b-medium |
| agy auth | OAuth or env keys | Binary strings show OAuth with a localhost callback (`http://localhost:%d/auth/callback`), a manual "Enter the redirect URL (if redirect failed)" fallback, device-code grant strings, and keyring token storage (`keyringAuth: failed to load stored token`). There is **no `agy auth`/`login` subcommand**; login happens on interactive start. Still to confirm in a throwaway HOME. |

## claude stream-json (raw-mode invocation) — sample in `backend/tests/fixtures/claude_raw_stream.ndjson`
Command: `claude -p PROMPT --output-format stream-json --verbose --include-partial-messages --system-prompt … --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources "" --no-session-persistence --permission-prompts none --max-turns 1 --max-budget-usd 0.5 --model haiku` (stdin = /dev/null).

* `system/init` reports `"tools": []`, `"mcp_servers": []` — raw mode genuinely removes tools and MCP.
* Event order: `system(init)`, `system(status)`, `stream_event`(message_start, content_block_start, content_block_delta*N, content_block_stop, message_delta, message_stop), a whole `assistant` message, `rate_limit_event`, `result`.
* Text delta: `{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}}`.
* `result`: `subtype`, `is_error`, `result`, `stop_reason`, `session_id`, `total_cost_usd`, `usage{input_tokens,output_tokens,cache_creation_input_tokens,cache_read_input_tokens,…}`, `modelUsage`, `terminal_reason`.
* `--model haiku` resolved to `claude-haiku-5-5`.

## agy stream-json — sample in `backend/tests/fixtures/agy_stream.ndjson`
`agy -p PROMPT --output-format stream-json --model gemini-3.8-flash-low --mode plan`

* `{"event":"init","conversation_id":…,"init":{model,cwd,tools[60],permission_mode,expanded_commands}}`
* `{"event":"step_update","step_update":{step_index,state:"ACTIVE|DONE",step_type:"user_input|agent_response|…","text_delta":"…","usage":{…}}}`
* `{"event":"result","result":{conversation_id,status:"SUCCESS",response,duration_seconds,num_turns,usage{input_tokens,output_tokens,thinking_tokens,cache_read_tokens,total_tokens}}}`
* `--output-format json` returns the single `result` object; no cost field (tokens only).

## Login flows (verified with an isolated, empty HOME under a PTY; never completed)

* **claude**: `claude auth login [--claudeai|--console|--sso|--email]`. Prints `Opening browser to sign in…`, then
  `If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?…` (single line), then `Paste code here if prompted >` and reads the code from stdin.
  `claude auth status [--json|--text]` prints JSON with `loggedIn`; with an empty `CLAUDE_CONFIG_DIR` it says `loggedIn:false`, so per-user isolation via `CLAUDE_CONFIG_DIR` works on macOS.
  It tries to open a browser on the server; the proxy sets `BROWSER=true` to neutralise that.
* **agy**: no login subcommand. Starting `agy` with no args and no session shows a TUI: `You are currently not signed in` / `1. Google OAuth` / `2. Use a Google Cloud project`.
  Enter selects option 1, which prints an `https://accounts.google.com/o/oauth2/auth?…` URL (redirect_uri = `https://antigravity.google/oauth-callback`) and waits at `authorization code...`.
  Because the redirect is a hosted page, not localhost, the code is pasted back through the terminal, which is exactly what the UI's code box relays. The TUI hard-wraps long URLs unless the PTY is very wide, so login PTYs use 1500 columns and the server also re-joins wrapped URLs (`extract_urls`). Fixture: `backend/tests/fixtures/agy_login_screen.txt`.
  `agy models` is a usable auth probe: it prints `Please sign in to view available models` when signed out and a tab-separated model list when signed in. An empty `HOME` is enough to be signed out on macOS, so per-user isolation by `HOME` works there.
  Not verified: where agy stores tokens on Linux (the binary mentions a keyring and a file fallback).

## Other things observed
* `agy` auto-updates itself while you use it (1.4.5 → 1.4.7 during this work, binary replaced in place). Output formats were identical across both versions. Pin/disable updates in production images.
* `claude --restricted`, `--safe-mode`, `--bare` exist; the proxy deliberately uses explicit flags (`--tools ""`, `--strict-mcp-config`, `--setting-sources ""`) so behaviour doesn't depend on those umbrella modes.

## Codex CLI (`codex exec`) — verified on codex-cli 0.167.0

`echo PROMPT | codex exec --json --skip-git-repo-check --ephemeral -s read-only -C <workdir> -`

* Output is JSONL. Sample in `backend/tests/fixtures/codex_stream.ndjson`:
  `{"type":"thread.started","thread_id":…}`, `{"type":"turn.started"}`,
  `{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"51"}}`,
  `{"type":"turn.completed","usage":{input_tokens,cached_input_tokens,cache_write_input_tokens,output_tokens,reasoning_output_tokens}}`.
* The answer arrives as whole `agent_message` items, not token deltas, so streaming clients get it in one chunk.
* `usage.input_tokens` already includes `cached_input_tokens`. A one-line prompt used 15–18k input tokens (about
  13k cached). No dollar cost is reported, so the ledger estimates it from `app/pricing.py`.
* The prompt is read from stdin when the PROMPT argument is `-`. Images: `-i <file>` (verified: a red PNG was
  described as "Red").
* No system-prompt flag. `<workdir>/AGENTS.md` is honoured (verified with a "begin your reply with ZEBRA7" test).
* `--ignore-user-config` skips `$CODEX_HOME/config.toml` but auth still comes from `CODEX_HOME`.
* Auth: `codex login status` prints `Logged in using ChatGPT` or a not-logged-in message; `codex login
  --with-api-key` reads a key from stdin. For API-key mode the adapter sets `CODEX_API_KEY` and `OPENAI_API_KEY`
  for the run; **that path was not exercised against the live API.**
* Typical latency for a trivial prompt: 7–9 s.

## Gemini CLI (`gemini`) — NOT verified against a real binary

Built from the public docs only (`docs/cli/headless.md`, `docs/cli/cli-reference.md`): `-p/--prompt`, `-m/--model`
(`auto`, `pro`, `flash`, `flash-lite` or a concrete name), `--output-format text|json|stream-json`,
`--approval-mode default|auto_edit|yolo|plan`, `--sandbox`. stream-json events: `init`, `message`, `tool_use`,
`tool_result`, `error` (non-fatal), `result` (with statistics). Exit codes: 0, 1 (error), 42 (input error),
53 (turn limit). The docs give no field names, so `adapters/gemini.py` accepts several spellings for message text
and token counts. `GEMINI_API_KEY` and `GEMINI_SYSTEM_MD` are assumed from general knowledge of the CLI. Run
`scripts/smoke_test.py --only gemini` after installing it and correct the adapter if anything differs.

## agy 1.5.x — later findings

* `--mode plan` together with `--disable-slash-commands` prints `warning: --mode plan has no effect while slash
  command expansion is disabled.` Raw mode now uses `--sandbox` (verified to work) and no `--mode`.
* Where the ~20 s goes for a trivial prompt: about 7 s until the `init` event (process start), about 8 s more until
  the `user_input` step (conversation set-up on Google's side), about 3 s for the model.
* `--input-format stream-json` keeps a process open and reads `{"event":"user","message":{"content":"…"}}` lines from
  stdin (`-p`/`--print` must be given as `--print=` with the other flags before it). A process started 25 s in advance
  still took about 14 s per turn, because the per-turn set-up is not skipped. A warm pool would save about 6 of 20
  seconds and each process keeps conversation state, so it was not built. For low latency use the direct API backend.
* Baseline input is now about 8.4k tokens per call.
