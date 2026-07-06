# Local Agents Studio — app image (pair with docker-compose.yml for Ollama)
# Stage 1: build the React frontend
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --silent
COPY frontend/ ./
# vite.config outputs to ../static/dist relative to frontend/
RUN mkdir -p /static && sed -i "s#outDir: \"../static/dist\"#outDir: \"/static/dist\"#" vite.config.js \
    && npm run build

# Stage 2: runtime
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    RUNNING_IN_DOCKER=1 \
    OLLAMA_URL=http://ollama:11434 \
    AGENTS_DB=/app/data/agents.db \
    AGENTS_WORKSPACES=/app/data/workspaces

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY custom_tools/ ./custom_tools/
COPY --from=frontend /static/dist ./static/dist

EXPOSE 5860
VOLUME ["/app/data"]

CMD ["gunicorn", "--bind", "0.0.0.0:5860", "--workers", "1", "--threads", "16", \
     "--timeout", "0", "--graceful-timeout", "5", "app:app"]
