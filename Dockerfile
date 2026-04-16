FROM nginx:1.27-alpine

# Copy nginx configuration
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

# Run as non-root user for security
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    chown -R appuser:appgroup /var/cache/nginx /var/log/nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && chown appuser:appgroup /var/run/nginx.pid

USER appuser

# The repos are mounted as volumes at runtime
WORKDIR /usr/share/nginx/html
