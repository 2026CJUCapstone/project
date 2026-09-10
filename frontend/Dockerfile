FROM node:24-alpine@sha256:50c8e8ca1d27439048670df5883f32d57cf81cff6233222c893fd0d9884cbd81 AS build

WORKDIR /app

ARG VITE_API_URL=
ARG VITE_APP_BASE_PATH=/
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_APP_BASE_PATH=${VITE_APP_BASE_PATH}

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Keep V8's heap below the shared 2 GiB BuildKit budget, leaving room for
# native allocations, worker threads and BuildKit itself. This is build-only.
RUN NODE_OPTIONS=--max-old-space-size=1536 npm run build

FROM nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6

# The official image writes its PID and logs below /var by default and its
# entrypoint may try to edit conf.d.  This image runs Nginx directly as an
# unprivileged user on a read-only root filesystem, so keep every runtime
# write under the Compose-provided /tmp tmpfs instead.
RUN sed -i \
      -e 's!^user  nginx;!# user nginx;  # master already runs unprivileged!' \
      -e 's!^error_log  /var/log/nginx/error.log notice;!error_log  /dev/stderr warn;!' \
      -e 's!^pid        /run/nginx.pid;!pid        /tmp/nginx.pid;!' \
      /etc/nginx/nginx.conf \
    && grep -qx 'pid        /tmp/nginx.pid;' /etc/nginx/nginx.conf \
    && grep -qx 'error_log  /dev/stderr warn;' /etc/nginx/nginx.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
# Only two reviewed routes are supported; never interpolate an arbitrary
# build argument as executable shell or Nginx configuration.
ARG FRONTEND_API_UPSTREAM=backend:8000
RUN case "$FRONTEND_API_UPSTREAM" in \
      backend:8000) ;; \
      api-proxy:8080) sed -i 's/server backend:8000 resolve;/server api-proxy:8080 resolve;/' /etc/nginx/conf.d/default.conf ;; \
      *) exit 2 ;; \
    esac
COPY --from=build /app/dist /usr/share/nginx/html
ARG DEPLOY_SHA=
ARG ENVIRONMENT=development
RUN set -eu; \
    LC_ALL=C; export LC_ALL; \
    case "$ENVIRONMENT" in \
      production) \
        case "$DEPLOY_SHA" in \
          ''|*[!0-9a-f]*) echo 'Production frontend DEPLOY_SHA must contain only lowercase hexadecimal bytes' >&2; exit 2 ;; \
        esac; \
        [ "${#DEPLOY_SHA}" -eq 40 ] || { echo 'Production frontend DEPLOY_SHA must be 40 bytes' >&2; exit 2; }; \
        release_sha="$DEPLOY_SHA" ;; \
      development|test) release_sha="non-release" ;; \
      *) echo 'Frontend ENVIRONMENT must be production, development, or test' >&2; exit 2 ;; \
    esac; \
    mkdir -p /usr/share/nginx/html/.well-known; \
    printf '{"deployment_sha":"%s"}\n' "$release_sha" > /usr/share/nginx/html/.well-known/webcompiler-release.json

EXPOSE 8080

USER 10001:10001

# Do not inherit /docker-entrypoint.sh: it performs optional configuration
# rewrites that are incompatible with the read-only root filesystem.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
