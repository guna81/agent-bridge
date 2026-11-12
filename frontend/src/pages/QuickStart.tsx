import { useEffect, useState } from "react";
import { admin, Provider } from "../api";
import type { Tab } from "../App";
import { Code } from "../components/ui";

export default function QuickStart({ go }: { go: (t: Tab) => void }) {
  const [model, setModel] = useState("claude/haiku");
  const base = location.origin;

  useEffect(() => {
    admin<Provider[]>("GET", "/providers")
      .then((ps) => {
        const p = ps.find((x) => x.enabled);
        if (p) setModel(`${p.name}/${p.default_model || p.models[0]}`);
      })
      .catch(() => {});
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>API quick start</h1>
          <p className="muted">
            Point any OpenAI- or Anthropic-compatible client at this server. Use an API key from the API keys & users page; examples use <code>{model}</code>.
          </p>
        </div>
      </div>

      <section className="card">
        <h2>Get started</h2>
        <ol><li><button className="link" onClick={() => go("providers")}>Connect and enable a provider</button>.</li><li><button className="link" onClick={() => go("keys")}>Add a user, credits, and an API key</button>.</li><li><button className="link" onClick={() => go("playground")}>Test a request in Playground</button>, then connect your client using the examples below.</li></ol>
      </section>
      <section className="card">
        <h2>OpenAI-compatible</h2>
        <p className="muted">
          Base URL <code>{base}/v1</code>. Supports streaming, images (as base64 <code>data:</code> URLs) and function calling via <code>tools</code>.
        </p>
        <h3>curl</h3>
        <Code>{`export KEY=sk-proxy-…
curl ${base}/v1/chat/completions \\
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \\
  -d '{"model": "${model}", "messages": [{"role": "user", "content": "Name a prime number."}]}'`}</Code>
        <h3>Python (openai)</h3>
        <Code>{`from openai import OpenAI

client = OpenAI(base_url="${base}/v1", api_key="sk-proxy-…")
reply = client.chat.completions.create(
    model="${model}",
    messages=[{"role": "user", "content": "Name a prime number."}],
)
print(reply.choices[0].message.content)`}</Code>
        <h3>Function calling</h3>
        <Code>{`tools = [{"type": "function", "function": {
    "name": "get_weather", "description": "Current weather for a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}}]
reply = client.chat.completions.create(model="${model}", tools=tools,
    messages=[{"role": "user", "content": "What's the weather in Paris?"}])
call = reply.choices[0].message.tool_calls[0]   # run it yourself, then send a {"role": "tool"} message back`}</Code>
        <p className="muted small">
          Function calling is emulated in the prompt (the CLIs have no native input for it), so replies that use <code>tools</code> arrive in one piece even
          when streaming, and a model can occasionally ignore the format.
        </p>
      </section>

      <section className="card">
        <h2>Anthropic-compatible</h2>
        <p className="muted">
          Base URL <code>{base}</code> (the SDK adds <code>/v1/messages</code>). Send the proxy key as <code>x-api-key</code>. Works with any enabled provider, not
          only Claude.
        </p>
        <h3>curl</h3>
        <Code>{`curl ${base}/v1/messages \\
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" -H "Content-Type: application/json" \\
  -d '{"model": "${model}", "max_tokens": 256, "messages": [{"role": "user", "content": "Name a prime number."}]}'`}</Code>
        <h3>Python (anthropic)</h3>
        <Code>{`import anthropic

client = anthropic.Anthropic(base_url="${base}", api_key="sk-proxy-…")
msg = client.messages.create(model="${model}", max_tokens=256,
    messages=[{"role": "user", "content": "Name a prime number."}])
print(msg.content[0].text)`}</Code>
      </section>

      <section className="card">
        <h2>Other endpoints</h2>
        <div className="table-wrap">
          <table>
            <tbody>
              <tr><td><code>GET /v1/models</code></td><td>Models this key may use.</td></tr>
              <tr><td><code>GET /v1/me</code></td><td>Credits left, usage, and the key's own budget if it has one.</td></tr>
              <tr><td><code>GET /metrics</code></td><td>Prometheus metrics. Needs the admin token as a Bearer token.</td></tr>
              <tr><td><code>GET /docs</code></td><td>Interactive API reference, including the admin API.</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
