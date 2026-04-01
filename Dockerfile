FROM nginx:1.27-alpine

# Copy nginx configuration
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

# The repos are mounted as volumes at runtime
WORKDIR /usr/share/nginx/html
