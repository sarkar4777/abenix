# Code runner

Warm runners for code assets. Each tenant and asset version gets its own Deployment, built once and then called over NATS. A warm call adds a few milliseconds on top of the code's own run time, against roughly 4.6 seconds for a one-off Job.

## How a call flows

1. The `code_asset` tool works out the runner revision (`v<version>-<hash of image, commands, archive>`) and sends a NATS request to `code.<tenant>.<asset>.<revision>`, or `....net` when the call asks for network.
2. A runner pod answers from queue group `coderun-<tenant8>-<asset8>-<revision>`.
3. With nobody listening the tool runs the old Job path and starts the runner in the background. The next calls go warm once the pod is ready.

`CODE_RUNNER_MODE` picks the behaviour. `auto` falls back to the Job, `warm` returns the error instead, `job` never tries NATS.

## Inside a runner pod

| Container | User | Job |
|---|---|---|
| `prepare` (init) | per-tenant uid | fetches the archive with a scoped token, unpacks it to `/tmp/app`, runs the build command once |
| `exec` | per-tenant uid | runs the code for each request, workspace mounted read-only |
| `gateway` | 10001 | holds the NATS login, forwards requests to `exec` over a unix socket, serves `/healthz` and `/metrics` on 9464 |

All three run non-root with a read-only root filesystem and every capability dropped. User code never shares a process or a uid with the NATS login.

Each run gets a private `HOME` and `TMPDIR`, the input on stdin and in `$ABENIX_INPUT_FILE`, its own process group (killed at the timeout and after exit), rlimits on CPU seconds, address space, process count and file size, and an environment that holds only the caller's env plus `PATH`, `HOME`, `TMPDIR` and a few language paths.

Code that reads the shared `/tmp/input.json` is detected at start and run one request at a time.

## Process and handler mode

Process mode is the default and starts the entrypoint for every request.

Handler mode keeps one process per slot alive. Opt in with `abenix-runner.json` at the project root.

```json
{"mode": "handler", "handler_command": "python handler.py", "concurrency": 2}
```

The handler reads one JSON line per request on stdin and answers with one JSON line on stdout.

```
in:  {"id": "<id>", "input": {...}}
out: {"id": "<id>", "output": <any JSON>}
out: {"id": "<id>", "error": "message"}
```

Any other stdout line counts as a log line. A handler that times out or exits is restarted on the next request. The process is also restarted when the request env changes, so rotated secrets reach it.

## Other manifest keys

| Key | Effect |
|---|---|
| `risk_tier` | low, medium, high or critical, sets the minimum warm replicas through `codeRunners.minWarmByTier` |
| `min_warm` | minimum warm replicas, never below what the tier asks for |
| `network` | the reaper pre-warms the `-net` variant instead of the closed one |
| `concurrency` | parallel runs per pod |

## Scaling and versions

- With KEDA each runner scales on `abenix_coderunner_load` (in-flight plus queued). Without it a CPU HPA does the same job above one replica.
- The reaper CronJob (`python -m engine.code_runners reap`) scales idle runners to zero after `idleSeconds`, keeps tier or hot runners warm, refreshes fetch tokens and pre-warms assets that ask for it.
- A new asset version gets a new runner. The old one stops getting requests, and the reaper deletes it after `drainSeconds` without traffic. A deleted pod finishes in-flight runs before it exits.

## Adding a pool

1. Add `Dockerfile.<lang>` here. Base it on the official image for that language, add `python3` and `nats-py` if the image has no Python, set `CODERUN_PATH`, run as uid 10001 and use `runner.py` as the entrypoint. `Dockerfile.node` is the pattern.
2. Make sure `pool_for_image` in `runner.py` and `engine/code_runners.py` maps the asset image to the pool name, for example `golang:1.22-alpine` to `go-1.22`. A test keeps both copies equal.
3. Add the pool to `codeRunners.pools` in the Helm values, `{name: go-1.22, image: code-runner-go}`.
4. Build it. `scripts/deploy.sh` picks up every `Dockerfile.*` here on its own. `scripts/deploy-azure.sh` needs the image in `DOCKERFILES`, `BUILD_CONTEXTS` and the build list.

Runtimes that reserve a lot of address space up front (V8, Go, the JVM) skip the address-space rlimit. The container memory limit still applies.

## Tests

```
cd apps/code-runner && python -m pytest -q
```

The process tests need Linux. On Windows run them in a `python:3.12-slim` container.
