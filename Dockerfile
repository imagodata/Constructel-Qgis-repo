FROM nginx:1.27-alpine

# git: git-http-backend for smart HTTP clone/pull/push
# fcgiwrap: CGI wrapper so nginx can proxy to git-http-backend
# python3: used by scripts/build_resource_zips.sh (rebuilds collection archives after each push)
# bash: required by scripts and post-receive hook
RUN apk add --no-cache git git-daemon fcgiwrap python3 bash

# Nginx vhost + container entrypoint
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/entrypoint.sh /entrypoint.sh

# Run as non-root user for security. uid 1001 matches host owner of the
# bind-mounted resource-repo* directories, so the post-receive hook can
# write to them.
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    chown -R appuser:appgroup /var/cache/nginx /var/log/nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && chown appuser:appgroup /var/run/nginx.pid && \
    chmod +x /entrypoint.sh

USER appuser

WORKDIR /usr/share/nginx/html

ENTRYPOINT ["/entrypoint.sh"]
