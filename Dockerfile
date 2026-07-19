# Local Agents Studio — app image (pair with docker-compose.yml for Ollama)
# Stage 1: build the React frontend
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --silent
COPY frontend/ ./
# vite.config outputs to ../static/dist relative to frontend/
RUN mkdir -p /static && sed -i "s#outDir: \"../static/dist\"#outDir: \"/static/dist\"#" vite.config.js \
    && npm run build

# Node binaries for the runtime image (the `browser` MCP tool spawns `npx`).
FROM node:22-slim AS node

# Stage 2: runtime
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    RUNNING_IN_DOCKER=1 \
    OLLAMA_URL=http://ollama:11434 \
    AGENTS_DB=/app/data/agents.db \
    AGENTS_WORKSPACES=/app/data/workspaces

# Node 22 — the only runtime reason for Node here is the `browser` tool, which
# runs the Playwright MCP server via `npx`. Copied from the official node image
# (no NodeSource/apt churn); npm/npx symlinks are relative, so we recreate them.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node -v && npm -v

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium + its OS libraries, so the `browser` tool works out of the
# box in-container. This adds ~400MB; if you don't use the browser tool, delete
# this block and the tool will just report itself unavailable. The MCP server
# itself is fetched by npx on first use.
RUN npx -y playwright@latest install --with-deps chromium \
    && rm -rf /root/.npm

COPY *.py ./
COPY custom_tools/ ./custom_tools/
COPY --from=frontend /static/dist ./static/dist

EXPOSE 5860
VOLUME ["/app/data"]

CMD ["gunicorn", "--bind", "0.0.0.0:5860", "--workers", "1", "--threads", "16", \
     "--timeout", "0", "--graceful-timeout", "5", "app:app"]
