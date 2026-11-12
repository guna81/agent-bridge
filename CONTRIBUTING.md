# Contributing

Thanks for helping. Bug reports, new CLI adapters and documentation fixes are all welcome.

## Setup

```bash
cd backend && uv sync --python 3.12 --all-extras
cd ../frontend && npm install
```

Run the server with `uv run python run.py` (from `backend/`, after setting `PROXY_SECRET_KEY`; see the README) and
the UI dev server with `npm run dev` (from `frontend/`; set `VITE_BACKEND` if the proxy is not on port 8000).

## Before you open a pull request

```bash
(cd backend && uv run pytest)          # must pass; needs no provider accounts
(cd frontend && npm run build)         # type-checks and builds the UI
```

- Add or update tests for behaviour you change. The suite drives a real server against `tests/fake_cli.py`, a
  scriptable stand-in for the CLIs, so most features can be tested without any login.
- Keep prompts, API keys and tokens out of logs, URLs and error messages.
- Never commit `.env`, `data/`, `*.log` or anything containing a real key.

## Adding a CLI adapter

1. Capture the CLI's real non-interactive output and put a sample in `backend/tests/fixtures/`.
2. Write `backend/app/adapters/<name>.py` implementing `CliAdapter`, and register it in `adapters/registry.py`.
3. Add a flavor to `tests/fake_cli.py` that prints the same shapes, and tests for the command line and the parser.
4. Write what you verified (version, flags, quirks) in `docs/cli-notes.md`. Say plainly what you could not verify.

Raw mode should switch off the CLI's own tools and replace its system prompt where the CLI allows it, and must
never pass a "skip permissions" flag.

## Terms of service

This project is for use with your own provider API keys. Please do not send changes whose purpose is to share or
resell consumer-subscription logins; see the note at the top of the README.
