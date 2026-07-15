FROM redis:8.0-alpine

COPY redis.conf /usr/local/etc/redis/redis.conf
COPY scripts /opt/streaming/scripts

CMD ["redis-server", "/usr/local/etc/redis/redis.conf"]