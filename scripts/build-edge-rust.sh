#!/usr/bin/env bash
# Build the Rust edge runtime in release mode and report binary size.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/apps/edge-runtime-rust"

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo not found — install rustup from https://rustup.rs and retry" >&2
  exit 1
fi

cd "${APP_DIR}"
cargo build --release --bin edge-runtime

bin="${APP_DIR}/target/release/edge-runtime"
if [ ! -f "${bin}" ]; then
  bin="${APP_DIR}/target/release/edge-runtime.exe"
fi

if command -v strip >/dev/null 2>&1; then
  strip "${bin}" || true
fi

size_bytes=$(wc -c < "${bin}" | tr -d ' ')
size_mb=$(awk -v b="${size_bytes}" 'BEGIN { printf "%.2f", b/1024/1024 }')

echo
echo "edge-runtime built: ${bin}"
echo "size: ${size_bytes} bytes (${size_mb} MiB)"
