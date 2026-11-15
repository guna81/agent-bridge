# Deployment

## Packaged CLI (recommended)

For personal use, `agentbridge start` is all you need, and after the first successful start AgentBridge starts at login on its own. See [Command line](cli.md#autostart).

The rest of this page covers the optional source-checkout setups and exposing the gateway to other machines.

## Always-running service (source checkout)

The service scripts operate on a source checkout and are separate from `agentbridge start`. They can stop an existing process on the configured port, so check the port first, and don't run two gateways on the same port. Set `PROXY_PORT` explicitly in `backend/.env`; the scripts' health checks fall back to 8765.

=== "macOS"

    A `launchd` LaunchAgent with `KeepAlive` and `RunAtLoad`.

    ```sh
    ./manage-service.sh install     # install and start
    ./manage-service.sh status
    ./manage-service.sh logs
    ./manage-service.sh restart
    ./manage-service.sh stop
    ./manage-service.sh uninstall
    ```

    Plist: `~/Library/LaunchAgents/com.ai-credit-proxy.plist`. Logs: `~/Library/Logs/ai-credit-proxy/`.

=== "Linux"

    A `systemd` **user** service, no root needed.

    ```sh
    ./manage-service.sh install     # also tries `loginctl enable-linger`
    ./manage-service.sh status
    systemctl --user status ai-credit-proxy.service
    journalctl --user -u ai-credit-proxy.service -f
    ```

    Linger keeps the service alive after you log out; enabling it may need administrator authorisation, so verify it. Unit file: `~/.config/systemd/user/ai-credit-proxy.service`.

=== "Windows"

    A Scheduled Task that starts at login, runs silently and restarts on failure.

    ```powershell
    powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 install
    powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 status
    powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 logs
    ```

    Logs: `%USERPROFILE%\.ai-credit-proxy\logs\server.log`. WSL2 works well for Linux-first CLIs: run `./manage-service.sh install` inside it. For a true system service that runs before logon, use NSSM.

!!! note
    The service names keep the historical `ai-credit-proxy` identifier.

If the service can't find your CLIs, check they are on the user `PATH`. The scripts include `~/.local/bin`, `/usr/local/bin`, `/opt/homebrew/bin`, `/usr/bin` and `/bin`.

## Docker

```sh
cp .env.example .env     # set PROXY_SECRET_KEY, PROXY_KEY_PEPPER (and PROXY_ADMIN_TOKEN)
docker compose up -d --build     # published on 127.0.0.1:8000 only
docker compose logs -f
```

The compose file uses `restart: unless-stopped`. The image installs Claude Code from npm. Add other npm CLIs with `EXTRA_NPM_CLIS='@openai/codex @google/gemini-cli' docker compose build`, and pass an `agy` install command as `AGY_INSTALL_CMD='...'`.

Containers are isolated: to reuse CLI logins, mount the CLI credential folders into the container, use API keys, or deploy natively.

## PM2

```sh
npm install -g pm2
pm2 start ecosystem.config.cjs
pm2 save && pm2 startup
```

## Health and metrics

```sh
curl -s http://127.0.0.1:8000/healthz     # {"ok": true}
curl -s http://127.0.0.1:8000/metrics     # needs the admin token unless PROXY_METRICS_PUBLIC=true
```

Use port `43187` for the packaged CLI.

## Exposing beyond localhost

The server binds to `127.0.0.1`, speaks plain HTTP, and the admin UI carries the admin token. **Do not expose it without TLS.**

??? example "Caddy (automatic HTTPS)"

    ```text
    proxy.example.com {
        encode zstd
        request_body { max_size 512KB }
        reverse_proxy 127.0.0.1:8000 {
            flush_interval -1          # don't buffer SSE streams
        }
    }
    ```

    Caddy handles WebSocket upgrades automatically.

??? example "nginx"

    ```text
    server {
        listen 443 ssl http2;
        server_name proxy.example.com;
        ssl_certificate     /etc/letsencrypt/live/proxy.example.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/proxy.example.com/privkey.pem;
        client_max_body_size 512k;

        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_buffering off;                 # SSE
            proxy_read_timeout 330s;             # > PROXY_REQUEST_TIMEOUT_S
        }
        # strongly recommended: restrict the admin surface
        location /admin {
            allow 203.0.113.0/24; deny all;
            proxy_pass http://127.0.0.1:8000;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
        }
    }
    map $http_upgrade $connection_upgrade { default upgrade; '' close; }
    ```

### Checklist

- Set `PROXY_ADMIN_TOKEN` to a long random value; set and back up `PROXY_KEY_PEPPER` and `PROXY_SECRET_KEY`.
- Keep `PROXY_SINGLE_USER_PERSONAL_USE=false` for anything other people use.
- The built-in rate limiter and queue are per process and in memory; use a real limiter at the proxy for multi-instance setups.
- Restrict `/admin` and the UI by IP or SSO at the reverse proxy if you can.
