FROM node:22-bookworm-slim AS console
WORKDIR /src
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && groupadd -g 10001 compartment && useradd --no-log-init -u 10001 -g compartment -d /tmp compartment && mkdir -p /data/artifacts /backup /lab && chown -R compartment:compartment /data /backup /lab
COPY compartment/ compartment/
COPY playbooks/ playbooks/
COPY --from=console /src/dist web/dist
USER compartment
CMD ["uvicorn","compartment.api:app","--host","0.0.0.0","--port","8080","--no-access-log"]

FROM runtime AS lab
USER root
RUN apt-get update && apt-get install -y --no-install-recommends chromium && rm -rf /var/lib/apt/lists/*
USER compartment
CMD ["uvicorn","compartment.lab:app","--host","0.0.0.0","--port","8091","--no-access-log"]
