# API reference

The gateway speaks two dialects. The examples use the packaged CLI's default address, `http://127.0.0.1:43187`. The standalone source server uses port `8000`; substitute your configured port.

## Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /v1/chat/completions` | `Authorization: Bearer <key>` | OpenAI-compatible chat |
| `POST /v1/messages` | `x-api-key: <key>` | Anthropic-compatible messages |
| `GET /v1/models` | key | Models this key may use |
| `GET /v1/me` | key | Credits, usage and key budget |
| `GET /v1/estimate` | key | Cost estimate: `model`, `input_tokens`, `output_tokens` |
| `GET /healthz` | none | Liveness check |
| `GET /metrics` | admin token | Prometheus metrics |
| `/admin/*` | admin token | Administration (see below) |

Interactive API documentation is served at `/docs` on the gateway.

## Examples

=== "OpenAI dialect"

    ```sh
    export KEY=sk-proxy-...

    curl -s http://127.0.0.1:43187/v1/chat/completions \
      -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d '{
      "model": "claude/haiku",
      "messages": [
        {"role":"system","content":"Be terse."},
        {"role":"user","content":"Name a prime number."}
      ]
    }'
    ```

=== "Anthropic dialect"

    Works with every provider, not only Claude.

    ```sh
    curl -s http://127.0.0.1:43187/v1/messages \
      -H "x-api-key: $KEY" -H 'Content-Type: application/json' -d '{
      "model": "codex/default", "max_tokens": 256,
      "messages": [{"role":"user","content":"Name a prime number."}]
    }'
    ```

=== "Python"

    ```python
    from openai import OpenAI
    c = OpenAI(base_url="http://127.0.0.1:43187/v1", api_key="sk-proxy-...")
    print(c.chat.completions.create(
        model="claude/haiku",
        messages=[{"role": "user", "content": "hi"}],
    ).choices[0].message.content)

    import anthropic
    a = anthropic.Anthropic(base_url="http://127.0.0.1:43187", api_key="sk-proxy-...")
    print(a.messages.create(
        model="claude/haiku", max_tokens=256,
        messages=[{"role": "user", "content": "hi"}],
    ).content[0].text)
    ```

Check your balance and key budget:

```sh
curl -s http://127.0.0.1:43187/v1/me -H "Authorization: Bearer $KEY"
```

## Behaviour to know

- **Streaming** is supported on both dialects.
- **Stateless.** `messages` becomes a system prompt plus a transcript; nothing is remembered between requests.
- **Function calling is emulated.** The CLIs have no input for caller-defined functions, so schemas go into the system prompt and the model answers with `<tool_call>` blocks that the gateway turns into `tool_calls` (OpenAI) or `tool_use` blocks (Anthropic). Replies to requests that include `tools` are parsed whole, so they arrive in one piece even with `stream: true`, and a model can occasionally ignore the format.
- **Images** must be inline base64 (`data:` URLs, or Anthropic `base64` sources). Remote URLs are never fetched. Supported by `claude` and `codex` through the CLI, and by the direct-API backend; other providers return 400. CLI providers accept images only in the **final** user message; earlier images are rejected rather than silently moved.
- **Ignored parameters.** `temperature` and `max_tokens` are ignored by the CLIs and listed in the `X-Proxy-Ignored-Params` response header. Direct API providers honour them.
- **Response headers.** `X-Proxy-Model` names the model used. After a fallback, `X-Proxy-Requested-Model` names the one you asked for.
- A client disconnect kills the CLI's whole process group.

## Errors

| Route | Shape |
|---|---|
| OpenAI routes | `{"error": {"message", "type", "code"}}` |
| `/v1/messages` | `{"type": "error", "error": {"type", "message"}}` |

Common codes: `429 key_budget_exhausted` (over budget), `403 model_not_allowed`, `401` (expired or invalid key), `400` (unsupported input such as images on a provider that can't take them).

## Admin API

Bearer admin token. Main routes:

- `GET|POST /admin/users`, `POST /admin/users/{id}/topup`
- `GET|POST /admin/keys`, `PATCH|DELETE /admin/keys/{id}`
- `GET /admin/ledger`, `GET /admin/usage/daily`
- `GET|POST|PUT|DELETE /admin/providers...`
- `GET /admin/reservations`, `DELETE /admin/reservations/{request_id}`
- `GET|POST /admin/skills`, `PUT /admin/skills/{kind}/{name}`, `POST /admin/skills/{kind}/{name}/validate`
- `POST /admin/skills/link`, `POST /admin/skills/{kind}/{name}/link`, `POST /admin/skills/{kind}/{name}/unlink`
- `POST /admin/skills/instructions/apply`, `POST /admin/skills/instructions/remove`

New ledger rows include duration, failure code where available, and the resolved model and rates used for estimated charges. Historical rows may not have these details.

## Using your own agents

- **Your own agent loop** (OpenAI Agents SDK, LangChain, a hand-written loop): point it at `/v1` and pass `tools`.
- **A CLI's own agents:** put the provider in agent mode, set `workdir`, and select the agent with `extra_args`. See [Raw vs agent mode](raw-vs-agent-mode.md).
- **Any other agent program:** register it as a [custom CLI](providers.md#custom-clis).
