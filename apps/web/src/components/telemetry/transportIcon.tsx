'use client';

import { Cable, Factory, Gauge, Globe, Layers, Network, Plug, Rabbit, RadioTower, Rss, Webhook, Workflow } from 'lucide-react';

const ICONS: Record<string, typeof Plug> = {
  mqtt: RadioTower,
  http_push: Webhook,
  websocket: Globe,
  kafka: Layers,
  amqp: Rabbit,
  nats: Network,
  opcua: Factory,
  modbus_tcp: Gauge,
  can: Cable,
  sse: Rss,
  workflow: Workflow,
};

export function TransportIcon({ transport, className }: { transport: string | undefined; className?: string }) {
  const Icon = (transport && ICONS[transport]) || Plug;
  return <Icon className={className} aria-hidden />;
}
