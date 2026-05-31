FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS python-base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app/market-watch-bot

COPY market-watch-bot/pyproject.toml market-watch-bot/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY market-watch-bot/ ./
RUN uv sync --frozen --no-dev

FROM python-base AS bot-worker

CMD ["uv", "run", "market-watch", "worker", "start"]

FROM python-base AS api-server

CMD ["uv", "run", "market-watch", "server", "start"]

FROM node:22-alpine AS dashboard-build

WORKDIR /app/dashboard
ARG VITE_API_BASE_URL
ARG VITE_API_AUTH_TOKEN
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_AUTH_TOKEN=$VITE_API_AUTH_TOKEN

COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

COPY dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine AS dashboard

COPY --from=dashboard-build /app/dashboard/dist /usr/share/nginx/html
EXPOSE 80
