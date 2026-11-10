# syntax=docker/dockerfile:1.7
# WinterPath web image — Vite static build served by unprivileged nginx (non-root, :8080).
# Build context: repository root.   docker build -f infra/docker/web.Dockerfile .
# Only public VITE_* values are accepted as build args; they end up in the JS bundle.

FROM node:24-slim AS build
WORKDIR /src
# The client is generated from the contract, so the contract must be in the context.
COPY docs/contracts/ docs/contracts/
COPY apps/web/package.json apps/web/package-lock.json apps/web/
RUN cd apps/web && npm ci --no-audit --no-fund
COPY apps/web/ apps/web/
ARG VITE_API_BASE_URL
ARG VITE_MAP_STYLE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_MAP_STYLE_URL=$VITE_MAP_STYLE_URL
RUN cd apps/web && npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY infra/docker/nginx-spa.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
