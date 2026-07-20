FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir \
      pytest==8.4.1 \
      bandit==1.8.6 \
      fastapi==0.116.1 \
      httpx==0.28.1 \
      pydantic==2.11.7 \
      sqlalchemy==2.0.41

RUN npm install --global \
      next@16.0.10 \
      react@19.2.0 \
      react-dom@19.2.0 \
      typescript@5.9.3 \
      @types/node@24.10.1 \
      @types/react@19.2.7 \
      @playwright/test@1.57.0 \
      @axe-core/playwright@4.11.0 \
    && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright npx playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

ENV PATH="/opt/venv/bin:/usr/local/bin:${PATH}" \
    NODE_PATH="/usr/local/lib/node_modules" \
    PLAYWRIGHT_BROWSERS_PATH="/ms-playwright"

RUN useradd --uid 10001 --create-home sandbox
USER 10001:10001

WORKDIR /workspace
