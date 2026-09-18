# syntax=docker/dockerfile:1
# ---- build ----------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile --network-timeout 600000

COPY . .

# CRA inlines env vars at build time, so the backend URL is a build arg.
ARG REACT_APP_BACKEND_URL=http://localhost:8000
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
RUN yarn build

# ---- serve ----------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -qO- http://localhost:3000/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
