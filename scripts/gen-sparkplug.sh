#!/usr/bin/env bash
# Rebuild sparkplug_b_pb2.py from the vendored Eclipse Tahu proto
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${ROOT_DIR}/apps/api/app/telemetry/sparkplug"
PY="${PYTHON:-python}"
"${PY}" -m grpc_tools.protoc -I"${DIR}" --python_out="${DIR}" "${DIR}/sparkplug_b.proto"
"${PY}" -m black -q "${DIR}/sparkplug_b_pb2.py"
echo "regenerated ${DIR}/sparkplug_b_pb2.py"
