FROM alpine:3.20

ENV BUNDLE_DIR=/var/edge/agents \
    SIGNING_PUBKEY_PATH=/etc/edge/signing_pub.pem \
    PORT=8080

WORKDIR /app

COPY Makefile /app/Makefile
COPY src /app/src

RUN apk add --no-cache \
        ca-certificates \
        libcurl \
        json-c \
        libmicrohttpd \
        mosquitto-libs \
        openssl \
        python3 \
        zlib \
    && apk add --no-cache --virtual .build-deps \
        gcc \
        musl-dev \
        make \
        pkgconf \
        curl-dev \
        json-c-dev \
        libmicrohttpd-dev \
        mosquitto-dev \
        openssl-dev \
        zlib-dev \
    && make release \
    && install -m 0755 build/release/edge-runtime-c /usr/local/bin/edge-runtime-c \
    && apk del .build-deps \
    && rm -rf /app/build /app/src /app/Makefile \
    && addgroup -g 1001 edge \
    && adduser -D -u 1001 -G edge edge \
    && mkdir -p /var/edge/agents /etc/edge \
    && chown -R edge:edge /var/edge /etc/edge

USER edge

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/health >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/usr/local/bin/edge-runtime-c"]
