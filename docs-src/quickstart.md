# Quick start

About five minutes from install to your first API call.

## 1. Start AgentBridge

```sh
agentbridge start
agentbridge dashboard
```

`start` launches the gateway (default `http://127.0.0.1:43187`) and the status indicator. `dashboard` opens the web UI already signed in.

To sign in manually instead, run `agentbridge dashboard --show-token` and keep the token private.

## 2. Enable a provider

In the dashboard open **Providers**:

1. Switch on the providers you want. Existing settings are never overwritten.
2. Choose how each one signs in:
    - **CLI login:** reuse the login of the CLI already on this machine, or click **Connect account** to run the CLI's login and finish it in your browser. New built-in providers default to reusing local CLI logins.
    - **API key:** paste the provider's key. It is encrypted at rest and injected only for that run.
3. Open the provider card and press **Run test**. Test runs are logged but not charged.

## 3. Check your usage

- **Subscription usage** shows available limits and reset times.
- **Status indicator** controls the menu bar or tray display. See [Status indicator](status-indicator.md).

## 4. Create an API key

In **API keys & users**:

1. Add a user.
2. Add credits.
3. Create a key. It is shown **once** and stored hashed, so copy it now.

## 5. Make a request

Use a `provider/model` ID such as `claude/haiku`.

=== "curl"

    ```sh
    export KEY=sk-proxy-...
    curl -s http://127.0.0.1:43187/v1/chat/completions \
      -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
      -d '{"model":"claude/haiku","messages":[{"role":"user","content":"Name a prime number."}]}'
    ```

=== "OpenAI Python SDK"

    ```python
    from openai import OpenAI

    client = OpenAI(base_url="http://127.0.0.1:43187/v1", api_key="sk-proxy-...")
    reply = client.chat.completions.create(
        model="claude/haiku",
        messages=[{"role": "user", "content": "hi"}],
    )
    print(reply.choices[0].message.content)
    ```

=== "Anthropic Python SDK"

    ```python
    import anthropic

    client = anthropic.Anthropic(base_url="http://127.0.0.1:43187", api_key="sk-proxy-...")
    reply = client.messages.create(
        model="claude/haiku", max_tokens=256,
        messages=[{"role": "user", "content": "hi"}],
    )
    print(reply.content[0].text)
    ```

You can also chat from the dashboard's **Playground**, and **API quick start** has copy-paste code for your setup.

## Next steps

- [Providers](providers.md) and [Models](models.md)
- [API reference](api.md)
- [Budgets and limits](keys-and-users.md)
- Start automatically at login: [Command line](cli.md#autostart)
