FROM node:22-bookworm-slim AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY docs/ /src/docs/
ENV NODE_OPTIONS=--max-old-space-size=3072 \
    VITE_APP_TITLE=TradingAgents-CN VITE_APP_VERSION=3.0.0 VITE_API_BASE_URL=""
RUN npm run build

FROM nginx:stable-alpine
COPY --from=build /src/frontend/dist /usr/share/nginx/html
COPY docker/frontend.conf /etc/nginx/conf.d/default.conf
