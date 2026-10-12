# Run the Edge demo and the telemetry testbed

> Real brokers, simulated machines and an Abenix Edge gateway on your local cluster, so you can see telemetry and store-and-forward work without any hardware. Needs a running `deploy.sh local`.

---

## Before you start

- A local cluster from `bash scripts/deploy.sh local`. Both commands check that minikube is running and stop if it is not. They build their images on minikube's Docker, so they do not run against AKS.
- Room for them. The testbed asks for about 1.3 GB. The Edge demo is one pod with four small containers. Check [06-deployment/09-local-sizing](../06-deployment/09-local-sizing.md#running-something-beside-abenix) before you add them to a cluster that is already full.
- Install the testbed first. The Edge demo reads the testbed's Modbus meter and OPC UA PLC, and says so when they are missing.

## The testbed

```bash
bash scripts/deploy.sh testbed
```

It installs Redpanda, RabbitMQ, NATS, an OPC UA PLC, a Modbus energy meter, a WebSocket price feed and an HTTP pusher in the `abenix-testbed` namespace. Then it adds each one to Abenix as a connection named `Testbed · ...` with a sample mapping. Open Monitor, Telemetry, Connections to watch them stream. `TESTBED_CONNECT=false` skips adding them.

Running it again is safe. Passwords are made once and kept in the `testbed-credentials` Secret, so saved connections keep working.

| Command | What it does |
|---|---|
| `deploy.sh testbed` | Install or update the testbed, then add the connections |
| `deploy.sh testbed-connect` | Add or refresh only the connections |
| `deploy.sh testbed-forwards` | Testbed ports on localhost: 19092 Kafka, 5672 AMQP, 4222 NATS, 50000 OPC UA, 5020 Modbus, 8765 WebSocket |
| `deploy.sh testbed-chaos <svc>` | Kill one broker or simulator pod and time its return. `<svc>` is `redpanda`, `rabbitmq`, `nats`, `opc-plc`, `meter`, `prices`, or a simulator such as `payments` |
| `deploy.sh testbed-poison <sim>` | Make a simulator send one malformed message, for the dead-letter ring |
| `deploy.sh testbed-load <n> <rate>` | A one-off Kafka burst to `load.events` for throughput runs |
| `deploy.sh testbed-down` | Remove the namespace, its data and its passwords |

Addresses, sign-ins, the meter's register map and the HTTP pusher are in [infra/helm/testbed/README.md](../../infra/helm/testbed/README.md). How sources, mappings and dead letters work is in [17-telemetry](17-telemetry.md).

## The Edge demo

```bash
bash scripts/deploy.sh edge-demo
```

It builds the Edge image on minikube's Docker, then creates a gateway named `Edge demo yard` through the public API, the same way an admin does on the Edge page. The gateway runs as `edge-demo-0` in the `abenix-edge-demo` namespace. Beside it run a CAN bus served over socketcand, simulated ECUs on that bus and an uplink relay that the cut uses. It collects:

| Collector | Asset in group `edge-demo` |
|---|---|
| J1939 on the CAN bus | `truck-7` |
| OBD-II on the CAN bus | `truck-7-obd` |
| NMEA GPS | `truck-7`, part `gps` |
| Testbed Modbus meter | `meter-1`, part `main` |
| Testbed OPC UA PLC | `opc-plc`, part `plc` |

The command waits up to four minutes for the first heartbeat and the first readings, then lists the assets. The gateway shows on the Edge page (`/edge`) and its readings under Monitor, Telemetry. `SKIP_EDGE_BUILD=true` reuses the image already built.

To see one chart, open
`/telemetry?group=edge-demo&node=truck-7&device=engine&signals=Engine/Speed_rpm,Engine/CoolantTemp_C&range=15m`.

### Cut the uplink

```bash
bash scripts/deploy.sh edge-demo-cut 120
```

It cuts the gateway's link to Abenix for 120 seconds, or the number you give. Every 10 seconds it prints the buffer depth and the age of the oldest reading. When the link returns it waits for the buffer to drain, then prints a proof. The proof reads the gateway's `Edge/Seq` history over the cut and reports gaps, repeats and whether the readings arrived in order. A clean run shows `gap_count` 0 and `in_order` true. How the buffer works is in [18-connect-your-organisation](18-connect-your-organisation.md#store-and-forward).

### Remove it

```bash
bash scripts/deploy.sh edge-demo-down
```

It deletes the gateway and its source in Abenix, then the `abenix-edge-demo` namespace.

## When something is wrong

| You see | Do this |
|---|---|
| `minikube is not running, use 'deploy.sh local' first` | Start the platform first |
| The Modbus and OPC UA collectors say they cannot reach their target | Install the testbed, then run `edge-demo` again |
| `no running API pod` | `bash scripts/deploy.sh status`, then wait for the API to be ready |
| Testbed pods stay `Pending` | The cluster is out of memory. See [09-local-sizing](../06-deployment/09-local-sizing.md#running-something-beside-abenix) |
| `the buffer did not drain within 180 s` | Check the gateway on the Edge page and `kubectl -n abenix-edge-demo logs edge-demo-0 -c edge` |

## See also

- [17-telemetry](17-telemetry.md), sources, mappings and rules
- [18-connect-your-organisation](18-connect-your-organisation.md), real gateways and hardware
- [06-deployment/05-edge-runtime](../06-deployment/05-edge-runtime.md), the edge runtime images and charts
