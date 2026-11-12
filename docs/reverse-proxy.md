# Exposing the proxy beyond localhost

The server binds to `127.0.0.1` by default and the compose file publishes `127.0.0.1:8000` only. It speaks plain HTTP and
the admin UI carries the admin token. The login WebSocket authenticates in its first message. `agentbridge dashboard` opens a URL containing the token in a fragment, which the dashboard removes after loading; fragments are not sent to the server.
**Do not expose it without TLS.**

The examples use port 8000 for the standalone source server. For a packaged CLI gateway, use its configured port (43187 by default).

## Caddy (automatic HTTPS)
```
proxy.example.com {
    encode zstd
    request_body { max_size 512KB }
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1          # don't buffer SSE streams
    }
}
```
Caddy handles WebSocket upgrades automatically.

## nginx
```
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
        proxy_set_header Upgrade $http_upgrade;       # websocket (Connect account)
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;                          # SSE
        proxy_read_timeout 330s;                      # > PROXY_REQUEST_TIMEOUT_S
    }
    # strongly recommended: restrict the admin surface
    location /admin { allow 203.0.113.0/24; deny all; proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1;
                      proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection $connection_upgrade; }
}
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
```

## Checklist
* Set `PROXY_ADMIN_TOKEN` to a long random value; set `PROXY_KEY_PEPPER` and `PROXY_SECRET_KEY` and back them up (losing the Fernet key loses stored API keys).
* Keep `PROXY_SINGLE_USER_PERSONAL_USE=false` for anything other people use.
* The built-in rate limiter and queue are per process and in memory; put a real limiter at the proxy for multi-instance setups.
* Restrict `/admin` and the UI by IP or SSO at the reverse proxy if you can.
