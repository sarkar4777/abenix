# Signing keys

Abenix signs every access token with one RSA key pair, `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY`. The API signs and checks tokens with it, and the agent runtime signs short-lived tokens with the same private key so its calls back to the API count as the person who started the run.

## Where the key is used

| Who | What it signs or checks | What breaks without it |
|---|---|---|
| API | Login, refresh and SSO access tokens. Every request, the notifications WebSocket and the `?token=` on SSE streams are checked with the public key | Sign-in, and with `DEBUG=false` the API refuses to start |
| Agent runtime, `invoke_agent` | A 5-minute token for the person who started the run, so a sub-agent runs as that person. See [06-agent-to-agent](../02-runtime/06-agent-to-agent.md) | A lead agent cannot call its sub-agents. The tool answers `Could not sign a token for the calling user` |
| Agent runtime, `code_asset`, `ml_model` and the code runner reaper | Fetch tokens that can download one code asset or one model file and nothing else, checked by `/api/code-assets/{id}/...` and `/api/ml-models/{id}/...` | Code assets and uploaded models cannot be pulled into a runtime pod |

`JWT_ALGORITHM` defaults to `RS256`. With an `HS*` algorithm both sides use `SECRET_KEY` instead, which is simpler but means anything holding `SECRET_KEY` can mint tokens. Use RS256 outside a laptop.

The edge runtime has its own key for signing agent bundles. It is not this pair, see [05-edge-runtime](../06-deployment/05-edge-runtime.md).

## Where it comes from

| How you run Abenix | Where the pair is made |
|---|---|
| `scripts/deploy.sh local` | Generated with `openssl` on the first deploy into the `abenix-secrets` Secret, then every service that reads that Secret is restarted so it picks the pair up. Later deploys keep the existing pair |
| `scripts/deploy-azure.sh` | Generated into `abenix-secrets` the same way when missing |
| `scripts/dev-local.sh` | The API runs with `DEBUG=true` and makes a throwaway pair in memory, so a restart signs everyone out. Put a pair in `.env` to keep sessions across restarts |
| Your own cluster | Generate a pair and put it in `abenix-secrets` before the first install, as below |

Every pod that reads `abenix-secrets` through `envFrom` gets the pair: the API, every agent runtime pool, the worker and the cognify worker. A pool pod that KEDA starts from zero reads it when it starts, so scaled pods need nothing extra.

## Generating a pair by hand

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt-private.pem
openssl rsa -in jwt-private.pem -pubout -out jwt-public.pem
```

Into the cluster:

```bash
kubectl create secret generic abenix-secrets -n abenix \
  --from-file=JWT_PRIVATE_KEY=jwt-private.pem \
  --from-file=JWT_PUBLIC_KEY=jwt-public.pem \
  --dry-run=client -o yaml | kubectl apply -f -
```

If `abenix-secrets` already exists, patch the two keys in rather than replacing the Secret, since it holds the database password and provider keys too. In production keep the private key in your secret manager (Azure Key Vault, AWS Secrets Manager, Vault) and sync it into the Secret.

Into `.env` for `dev-local.sh`, with the newlines written as `\n` on one line:

```bash
JWT_PRIVATE_KEY="$(awk 'NF {printf "%s\\n", $0}' jwt-private.pem)"
JWT_PUBLIC_KEY="$(awk 'NF {printf "%s\\n", $0}' jwt-public.pem)"
```

Both the API and the runtime turn `\n` back into line breaks.

## Changing the pair

A new pair invalidates every token signed with the old one. Everyone is signed out, and a sub-agent call or a fetch that was in flight fails once and is retried by the model or the caller.

1. Put the new pair in `abenix-secrets`.
2. Restart everything that reads it, so no pod keeps the old key: `kubectl rollout restart deploy -n abenix -l app.kubernetes.io/instance=abenix`, or run the deploy script again.
3. Tell people they will need to sign in again.

There is no overlap period with two valid keys.

## Checking it

```bash
# the API and each runtime pool should both print 1
kubectl exec -n abenix deploy/abenix-api -- sh -c 'env | grep -c JWT_PRIVATE_KEY'
kubectl exec -n abenix deploy/abenix-agent-runtime-default -c agent-runtime -- sh -c 'env | grep -c JWT_PRIVATE_KEY'
```

A pod that prints 0 started before the key was added. Restart it. In the product the symptom is a lead agent answering that it could not reach its sub-agents, with `Could not sign a token` in the tool result on the run's Flight Recorder page.
