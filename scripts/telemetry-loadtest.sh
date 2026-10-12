#!/usr/bin/env bash
# Telemetry load test against the local cluster, run as a Kubernetes Job on the API image.
#
#   bash scripts/telemetry-loadtest.sh t2            4 nodes x 400 msg/s, 60 s
#   bash scripts/telemetry-loadtest.sh t7            50 nodes x 200 msg/s over 3 workspaces,
#                                                    200 live viewers, one ingest replica killed
#   SECONDS_RUN=120 VIEWERS=200 KILL_AFTER=40 KEEP=1 bash scripts/telemetry-loadtest.sh t7
#   RATE=40 bash scripts/telemetry-loadtest.sh t7      t7 at a fifth of the rate, for a busy node
#
# t7 needs two ingest replicas first: TELEMETRY_INGEST_REPLICAS=2 bash scripts/deploy.sh chart
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-abenix}"
RELEASE_NAME="${RELEASE_NAME:-abenix}"
SCENARIO="${1:-t2}"
RUN_FOR="${SECONDS_RUN:-60}"
VIEWERS="${VIEWERS:-200}"
KILL_AFTER="${KILL_AFTER:-30}"
JOB="telemetry-loadtest-${SCENARIO}"
OUT_DIR="${ROOT_DIR}/logs/telemetry-loadtest"

case "${SCENARIO}" in t2|t7) ;; *) echo "usage: $0 {t2|t7}"; exit 1 ;; esac

image=$(kubectl -n "${NAMESPACE}" get deploy "${RELEASE_NAME}-api" \
  -o jsonpath='{.spec.template.spec.containers[0].image}')
pull=$(kubectl -n "${NAMESPACE}" get deploy "${RELEASE_NAME}-api" \
  -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}')
replicas=$(kubectl -n "${NAMESPACE}" get deploy "${RELEASE_NAME}-telemetry-ingest" \
  -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)
echo "[loadtest] image ${image}, ingest replicas ready: ${replicas:-0}"
if [ "${SCENARIO}" = "t7" ] && [ "${replicas:-0}" -lt 2 ]; then
  echo "[loadtest] t7 needs two ingest replicas, run: TELEMETRY_INGEST_REPLICAS=2 bash scripts/deploy.sh chart"
  exit 1
fi

args="\"${SCENARIO}\", \"--seconds\", \"${RUN_FOR}\", \"--viewers\", \"${VIEWERS}\", \"--kill-after\", \"${KILL_AFTER}\""
[ -n "${RATE:-}" ] && args="${args}, \"--rate\", \"${RATE}\""
[ -n "${KEEP:-}" ] && args="${args}, \"--keep\""

kubectl -n "${NAMESPACE}" delete job "${JOB}" --ignore-not-found >/dev/null
kubectl -n "${NAMESPACE}" apply -f - >/dev/null <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB}
  labels:
    app.kubernetes.io/component: telemetry-loadtest
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 600
  template:
    metadata:
      labels:
        app.kubernetes.io/component: telemetry-loadtest
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
      containers:
        - name: loadtest
          image: ${image}
          imagePullPolicy: ${pull:-IfNotPresent}
          command: ["python", "-m", "app.telemetry.loadtest", ${args}]
          env:
            - name: LOADTEST_API
              value: "http://${RELEASE_NAME}-api.${NAMESPACE}.svc.cluster.local:8000"
            - name: LOADTEST_EMAIL
              value: "${LOADTEST_EMAIL:-admin@abenix.dev}"
            - name: LOADTEST_PASSWORD
              value: "${LOADTEST_PASSWORD:-Admin123456}"
          envFrom:
            - secretRef:
                name: ${RELEASE_NAME}-secrets
            - configMapRef:
                name: ${RELEASE_NAME}-config
          resources:
            requests:
              cpu: "${LOADTEST_CPU_REQUEST:-400m}"
              memory: 512Mi
            limits:
              cpu: "4"
              memory: 2Gi
EOF

echo "[loadtest] job ${JOB} started"
pod=""
for _ in $(seq 1 60); do
  pod=$(kubectl -n "${NAMESPACE}" get pods -l job-name="${JOB}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  phase=$(kubectl -n "${NAMESPACE}" get pod "${pod}" -o jsonpath='{.status.phase}' 2>/dev/null || true)
  case "${phase}" in Running|Succeeded|Failed) break ;; esac
  sleep 2
done
if [ -z "${pod}" ] || ! case "${phase}" in Running|Succeeded|Failed) true ;; *) false ;; esac; then
  echo "[loadtest] the job pod did not start: $(kubectl -n "${NAMESPACE}" get events --field-selector involvedObject.name="${pod}" -o jsonpath='{.items[-1:].message}' 2>/dev/null)"
  kubectl -n "${NAMESPACE}" delete job "${JOB}" --ignore-not-found >/dev/null
  exit 1
fi

mkdir -p "${OUT_DIR}"
log="${OUT_DIR}/${SCENARIO}-$(date +%Y%m%d-%H%M%S).log"
killed=""
while :; do
  kubectl -n "${NAMESPACE}" logs "${pod}" > "${log}" 2>/dev/null || true
  if [ "${SCENARIO}" = "t7" ] && [ -z "${killed}" ] && grep -q "READY_FOR_KILL" "${log}"; then
    # a hard kill, no SIGTERM, so the leases have to lapse like a crashed node
    victim=$(kubectl -n "${NAMESPACE}" get pods -l app.kubernetes.io/name=telemetry-ingest \
      -o jsonpath='{.items[0].metadata.name}')
    echo "[loadtest] killing ingest replica ${victim} at $(date +%H:%M:%S)"
    kubectl -n "${NAMESPACE}" delete pod "${victim}" --grace-period=0 --force >/dev/null 2>&1 || true
    killed="${victim}"
  fi
  phase=$(kubectl -n "${NAMESPACE}" get pod "${pod}" -o jsonpath='{.status.phase}' 2>/dev/null || echo gone)
  case "${phase}" in Succeeded|Failed|gone) break ;; esac
  sleep 2
done
kubectl -n "${NAMESPACE}" logs "${pod}" > "${log}" 2>/dev/null || true
grep -v '^REPORT ' "${log}" | tail -20
report=$(grep '^REPORT ' "${log}" | tail -1 | sed 's/^REPORT //')
if [ -z "${report}" ]; then
  echo "[loadtest] no report, the job ${phase}, full log in ${log}"
  exit 1
fi
echo "${report}" > "${log%.log}.json"
python -c "import json,sys; print(json.dumps(json.loads(sys.argv[1]), indent=2))" "${report}" 2>/dev/null || echo "${report}"
echo "[loadtest] report saved to ${log%.log}.json"
kubectl -n "${NAMESPACE}" delete job "${JOB}" --ignore-not-found >/dev/null
