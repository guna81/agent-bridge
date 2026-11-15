# Models

Model IDs have the form **`provider/model`**, for example `claude/haiku` or `codex/default`. `GET /v1/models` lists what a key is allowed to use.

## Choosing models

Each provider has a **Models offered** list, a default model and a default mode. Callers pick a model per request with the `model` field.

Per-key model allow-lists accept exact IDs or globs, such as `claude/haiku` or `codex/*`. See [Keys, users and budgets](keys-and-users.md).

## Codex model discovery

An enabled Codex provider that uses the **shared host CLI login** discovers the models visible to your account:

- at startup, and then **every 30 minutes**, from Codex's app-server;
- immediately when you press **Refresh discovered models** on the provider card.

Discovered models appear in key suggestions and in `/v1/models`, and can be routed like models you configured by hand. Notes:

- The discovered list is separate from **Models offered**.
- A failed refresh keeps the last successful list.
- Discovery needs an authenticated host login. It does **not** run for API-key or isolated per-user logins; configure those models manually.
- Discovery is not a guarantee of access. Codex and your account decide what is available.

## Model picker

The dashboard's model pickers (Playground, key creation) draw on the models offered plus discovered models.

## Cost estimates

Use `GET /v1/estimate` (parameters `model`, `input_tokens`, `output_tokens`) to see the rates and an estimate for a model. See [API reference](api.md).
