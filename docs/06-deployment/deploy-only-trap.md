# The `--only` deploy trap

A subtle bite that catches every new contributor on this codebase exactly once. This document exists so it catches you zero times.

## The trap

Image tags in the helm chart are derived from the current git commit SHA. The `scripts/deploy-azure.sh build --only=<service>` command rebuilds **only** the named service. But the helm-templating step that follows rewrites the image tag on **every** deployment to the new SHA.

End state:
- `abenix-api` and `abenix-web`: new SHA tag, image was just pushed — pods pull, become Ready.
- `abenix-agent-runtime-*`, `abenix-worker`, `abenix-cognify-worker`: new SHA tag, **image was NOT rebuilt**, ACR doesn't have that tag — pods enter `ImagePullBackOff`.

The old replicas keep serving traffic so nothing is on fire, but you have a ghost ReplicaSet behind every untouched deployment that will never become Ready.

## How to spot it

```bash
kubectl get pods -n abenix | grep -E 'ImagePullBackOff|ErrImagePull'
```

If you see multiple services in that state right after a `--only=X` build, you've hit the trap.

## How to recover (in order of preference)

**Option 1 — Build the missing services with the same SHA.**

```bash
bash scripts/deploy-azure.sh build --only=agent-runtime,worker,cognify-worker
# Then re-point the deployments at the new tag they just got built for:
NEW_SHA=$(git rev-parse --short HEAD)
kubectl set image deploy/abenix-agent-runtime-default \
  '*=your-acr.azurecr.io/agent-runtime:'"$NEW_SHA" -n abenix
# Repeat for the other agent-runtime pools, worker, cognify-worker.
```

**Option 2 — Roll back to the previous working tag.**

```bash
kubectl rollout undo deploy/abenix-agent-runtime-default -n abenix
```

**Option 3 — Helm rollback (if you used the chart's release path).**

```bash
helm rollback abenix <previous-revision> -n abenix
```

## How to avoid

- For any change that touches Dockerfiles, shared code, or `packages/`: do a full `bash scripts/deploy-azure.sh build` (no `--only`).
- For a docs-only or web-only iteration, `--only=web` is safe because the web deployment is the only one using the `web` image.
- **Never use `--only=` on a service that shares an image** (e.g. `worker` and `cognify-worker` both use the `worker` image).

## Why we haven't fixed the tooling

It's a one-line change in `scripts/deploy-azure.sh` to make `--only` *not* rewrite tags on untouched deployments. The reason we haven't is that the current behaviour, while painful, makes the SHA-pinning invariant simple to reason about: every deployment at any point in time is pinned to one SHA, and `helm template` is the source of truth. Splitting that into per-deployment SHAs is a different model and adds drift surface.

A planned alternative is to switch to `imagePullPolicy: IfNotPresent` and tag-by-content-hash. Until that lands, this trap is real. Don't fall in.
