FROM rust:1.86-alpine AS builder

RUN apk add --no-cache musl-dev pkgconfig openssl-dev openssl-libs-static

WORKDIR /build
COPY Cargo.toml Cargo.lock* ./
COPY src ./src
COPY tests ./tests

ENV CARGO_NET_GIT_FETCH_WITH_CLI=true \
    RUSTFLAGS="-C target-feature=-crt-static"

RUN cargo build --release --bin edge-runtime \
    && strip /build/target/release/edge-runtime


FROM alpine:3.20

RUN apk add --no-cache python3 ca-certificates \
    && addgroup -g 1001 edge \
    && adduser -D -u 1001 -G edge edge \
    && mkdir -p /var/edge/agents /etc/edge \
    && chown -R edge:edge /var/edge /etc/edge

COPY --from=builder /build/target/release/edge-runtime /usr/local/bin/edge-runtime

USER edge
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/usr/local/bin/edge-runtime"]
