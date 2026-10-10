# The `--only` deploy trap

`--only` builds part of the image set but moves every core Deployment to the new tag. Read this before using it.

## The trap

`deploy-azure.sh deploy --only=<list>` and `redeploy --only=<list>` build only
the listed images, tagged with the current short git SHA. Then, if the list
names any core service (`api`, `web`, `worker`, `agent-runtime` or
`cognify-worker`), the Helm step runs and sets the image tag of **every** core
Deployment to that SHA: api, web, worker, every runtime pool, the cognify
worker, the code runner images, and the agent-runtime subchart where it is on
(the Azure values turn it off). The group `abenix` expands to all core images
plus `code-runner-python` and `code-runner-node`.

End state after `--only=web`:

- `abenix-web`: new SHA, image was just pushed, pods become Ready.
- `abenix-api`, `abenix-worker`, `abenix-cognify-worker`, `abenix-agent-runtime-<pool>`: new SHA, **image never built**, ACR has no such tag, pods go to `ImagePullBackOff`.
- Warm code runners created after the deploy hit the same missing tag.

The old ReplicaSets keep serving, so nothing is on fire, but every untouched
Deployment carries a ReplicaSet that will never become Ready, and the reconcile
step at the end of the deploy fails.

`deploy-azure.sh build --only=...` on its own is harmless. It runs no Helm step.

## How to spot it

```bash
kubectl get pods -n abenix | grep -E 'ImagePullBackOff|ErrImagePull'
```

Several services in that state right after an `--only` deploy means you hit it.

## How to recover

**Option 1 — Helm rollback.** Puts every Deployment back on the previous tag.

```bash
helm history abenix -n abenix
helm rollback abenix <previous-revision> -n abenix
```

**Option 2 — Finish the job.** Run the full deploy, which builds every image at
the SHA Helm already points at.

```bash
bash scripts/deploy-azure.sh redeploy
```

## How to avoid

Always run the full command:

```bash
bash scripts/deploy-azure.sh redeploy
```

That is the supported way to ship any change to AKS. Images that did not
change build quickly from the layer cache. A list with no core service in it
skips the Helm step and does not trip this trap, but the full run is still the
habit to keep, because the moment a core service joins the list the trap is
back.

## Why the tooling works this way

Every core Deployment at any point in time is pinned to one SHA, and the Helm
release is the source of truth for it. Per-Deployment tags would make
`--only` safe but would let the services drift onto different builds.
