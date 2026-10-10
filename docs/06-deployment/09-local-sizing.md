# Sizing a local cluster

`bash scripts/deploy.sh local` runs everything inside one minikube node, and that node lives in a Docker container. How much memory it needs depends on which use-case apps you pick. The script works this out for you, but Docker has to have the room first.

## How much you need

The script sizes minikube from the apps you choose. The core platform needs 8 GB, and each app adds 0.75 GB. Docker needs about 1 GB on top of minikube for itself and for the web image builds that run beside it.

| What you run | `APPS=` | minikube | Docker at least | Machine RAM, typical |
|---|---|---|---|---|
| Core platform only | `none` | 8 GB, 4 CPUs | 10 GB | 16 GB |
| Core plus one or two apps | `contractiq` or `contractiq,wingman` | 8.75 to 9.5 GB, 4 CPUs | 11 to 12 GB | 16 to 24 GB |
| Core plus three or four apps | `contractiq,wingman,pharmavigil` | 10.25 to 11 GB, 6 CPUs | 12 to 13 GB | 24 GB |
| Everything | `all`, or press Enter at the prompt | 13.25 GB, 6 CPUs | 16 GB | 32 GB |

Disk: about 20 GB free for the core platform, about 40 GB for everything. Images build up across redeploys, so `docker system prune` now and then gets space back.

The core platform is the API, web app, agent runtime, worker, Postgres, Redis, Neo4j, NATS, TimescaleDB, KEDA, Prometheus, Grafana, LiveKit, the edge gateway and the dev catchers. The figures come from the memory each pod asks Kubernetes for, measured on a running cluster.

| App | Memory it asks for |
|---|---|
| ContractIQ | 768 MB |
| Mideast Tourism | 768 MB |
| ClaimsIQ | 768 MB |
| Industrial IoT | 640 MB |
| ResolveAI | 640 MB |
| PharmaVigil | 640 MB |
| Wingman | 512 MB |

## Giving Docker more memory

- **Docker Desktop on macOS, or on Windows with the Hyper-V backend.** Settings > Resources > Memory, then Apply & restart.
- **Docker Desktop on Windows with WSL 2**, the default. The Resources slider is not there. WSL gives Docker half of the machine's RAM unless you say otherwise. To give it 16 GB, put this in `%UserProfile%\.wslconfig`:

  ```ini
  [wsl2]
  memory=16GB
  processors=6
  ```

  Then run `wsl --shutdown` in PowerShell and start Docker Desktop again.
- **Docker Engine on Linux.** Containers can use all the machine's memory, so there is nothing to set.

Check what Docker has with `docker info --format "{{.MemTotal}}"`. The value is in bytes, so 17179869184 is 16 GB.

## What the script does with it

Before it starts minikube, `deploy.sh local` compares what your apps need with what Docker has. If they do not fit, it stops before anything is created. It then tells you how many apps your Docker can hold and what to change. Nothing is left half built.

It also tells Kubernetes how much memory minikube really has. With the Docker driver, Kubernetes inside minikube otherwise sees all of Docker's memory. It then places more pods than fit, and the node runs out of memory under load and stops answering. The script reserves the difference with `kubelet.kube-reserved`, so a pod that does not fit waits as Pending with a clear reason instead.

A cluster keeps the size it was created with. When you add apps to a running cluster that is too small for them, the deploy warns you and carries on.

## Overrides

| Variable | Default | Use |
|---|---|---|
| `MINIKUBE_MEMORY` | 8192 plus 768 per app, in MiB | Force a size. The memory check then only warns |
| `MINIKUBE_CPUS` | 4, or 6 with three or more apps | Never more than Docker has |
| `OBSERVABILITY=false` | `true` | Skips Prometheus and Grafana and saves about 600 MB |
| `DEV_CATCHERS=false` | `true` | Skips Mailpit, the webhook catcher and mock OIDC, about 200 MB |

## Growing or shrinking a cluster

minikube cannot be resized in place. To change the size, recreate it:

```bash
FRESH=true APPS=all bash scripts/deploy.sh local
```

`FRESH=true` deletes the local cluster and everything in it, including agents you built, runs, uploaded documents and settings. The seeds bring back the sample agents and the default logins, nothing else.

To free memory without recreating, remove an app you no longer need. A deploy with a smaller `APPS=` list does not remove the apps it leaves out. Each app is one manifest, so for ContractIQ:

```bash
kubectl delete -f contractiq/k8s/contractiq.yaml
```

The other manifests sit at `<app>/k8s/<app>.yaml` in the same way. Run the deploy again with that app in `APPS=` to bring it back.

## Signs the cluster is short of memory

- The deploy ends with "Some pods could not be placed because minikube is out of memory or CPU".
- `kubectl get pods -n abenix` shows pods as `Pending`, `Evicted` or `OOMKilled`, or restarting again and again.
- `kubectl get nodes` shows the node as `NotReady` for a while, and pages stop loading until it recovers.
- `kubectl describe node minikube` lists `MemoryPressure True`.

Any of these means: fewer apps, or a bigger cluster.

## Running without Kubernetes

`bash scripts/dev-local.sh` runs the platform as local processes with the data stores in docker compose. Docker then only holds the data stores, so it needs far less memory than a full cluster. It suits working on the code. See [08-howto/00-local-setup](../08-howto/00-local-setup.md).
