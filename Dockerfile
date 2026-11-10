# --- UI build ------------------------------------------------------------------------------------
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- runtime -------------------------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

# Node is needed for the Claude Code CLI (npm package). Everything the CLIs need must exist in the image.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI. Pin a version you have tested: --build-arg CLAUDE_CODE_VERSION=2.1.310
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Other npm-distributed CLIs, e.g. --build-arg EXTRA_NPM_CLIS="@openai/codex @google/gemini-cli"
ARG EXTRA_NPM_CLIS=""
RUN if [ -n "$EXTRA_NPM_CLIS" ]; then npm install -g $EXTRA_NPM_CLIS; fi

# Antigravity CLI (agy): there is no install channel we could verify for Linux. Supply the install command from
# Google's documentation, e.g.  --build-arg AGY_INSTALL_CMD='curl -fsSL <url-from-google-docs> | sh'
# It must leave an `agy` binary on PATH. If empty, the agy provider simply reports "not installed".
ARG AGY_INSTALL_CMD=""
RUN if [ -n "$AGY_INSTALL_CMD" ]; then sh -c "$AGY_INSTALL_CMD"; else echo "agy not installed (no AGY_INSTALL_CMD)"; fi

RUN useradd --create-home --uid 10001 cliproxy
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY backend/run.py ./
COPY --from=ui /ui/dist /app/frontend-dist

ENV PROXY_FRONTEND_DIST=/app/frontend-dist PROXY_DATA_DIR=/data PROXY_HOST=0.0.0.0 PROXY_PORT=8000
RUN mkdir /data && chown cliproxy /data
USER cliproxy
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD curl -fs http://127.0.0.1:8000/healthz || exit 1
CMD ["python", "run.py"]
