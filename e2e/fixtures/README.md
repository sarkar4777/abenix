# UAT Fixtures

Binary fixtures driven by the three Abenix UAT specs in `e2e/`.

| File                       | Used by                                  | Purpose                                                                  |
|----------------------------|------------------------------------------|--------------------------------------------------------------------------|
| `uat_kb_doc.pdf`           | `uat_abenix_industrial.spec.ts`      | 1-page text PDF containing `QUANTUM_GIGAFACTORY_UAT_MARKER`. Knowledge upload + cognify + retrieval check. |
| `uat_python_app.zip`       | `uat_abenix_industrial.spec.ts`      | Tiny Python add-server. Code Runner upload + analysis test.              |
| `uat_ml_model.pkl`         | `uat_abenix_industrial.spec.ts`      | Pickled stub object; ML Models upload + listing test.                    |
| `mcp_server/`              | `uat_abenix_industrial.spec.ts`      | In-cluster MCP demo server (`uat_echo` tool) for MCP discovery test.     |

These three binaries (PDF, ZIP, PKL) are checked in so the test suite is hermetic. Regenerate them deterministically with:

```bash
python e2e/fixtures/build.py
```

## MCP demo server

The MCP fixture is a small Python + FastAPI server in `mcp_server/`. Build, push, and apply once per cluster:

```bash
az acr login -n your-acr
docker build -t your-acr.azurecr.io/uat-mcp:latest e2e/fixtures/mcp_server/
docker push your-acr.azurecr.io/uat-mcp:latest
kubectl apply -f e2e/fixtures/mcp_server/deployment.yaml
kubectl -n abenix rollout status deploy/uat-mcp --timeout=120s
```

The industrial spec resolves the server via Kubernetes DNS at `http://uat-mcp.abenix.svc.cluster.local:8080/mcp`. Override with `UAT_MCP_URL=...` if your environment uses a different cluster DNS.

## Why these fixtures live in the repo

The test suite is the deploy gate. Anything the gate depends on must be
reproducible from a fresh clone. External fixtures (random KB docs, drive
links, hosted MCP servers) drift; in-repo fixtures don't. Treat
`build.py` as the contract — if a test needs a new shape, extend
`build.py` and re-run it.
