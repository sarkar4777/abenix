// "Connect what you have": each kind of thing an organisation owns, the ways in, and where each one ends.
import type { Mapping } from './sources';

export type PathAction =
  | { kind: 'source'; transport: string; decoder?: string; name: string; mapping?: Partial<Mapping>; sample?: string; subject?: string; config?: Record<string, unknown> }
  | { kind: 'edge'; collector: string }
  | { kind: 'sdk' };

export interface GuidePath {
  id: string;
  title: string;
  text: string;
  // custom code runs somewhere, and why
  code?: string;
  action: PathAction;
}

export interface GuideCategory {
  id: string;
  title: string;
  examples: string;
  icon: 'truck' | 'factory' | 'sensor' | 'plug' | 'code';
  paths: GuidePath[];
}

const TELEMATICS = {
  vehicle_id: 'VAN-042',
  timestamp: '2026-10-11T09:30:00Z',
  location: { lat: 51.5072, lon: -0.1276 },
  speed_kmh: 48,
  odometer_km: 120344,
  fuel_pct: 63,
  ignition: true,
  engine: { rpm: 1650, coolant_c: 88 },
};

const TRACKER = { ts: 1760175000000, lat: 51.5072, lon: -0.1276, speed_kmh: 32, battery_v: 12.6, ignition: true };

const CHIRPSTACK = {
  deduplicationId: '3f1c7a52-6a0b-4c1e-9d1e-6f0a2b8c9e11',
  time: '2026-10-11T09:30:00Z',
  deviceInfo: { applicationName: 'site-sensors', deviceName: 'cold-room-3', devEui: '0004a30b001c1b2e' },
  object: { temperature: 4.2, humidity: 71, battery_v: 3.6 },
  rxInfo: [{ rssi: -97, snr: 7.5 }],
};

const TTS = {
  end_device_ids: { device_id: 'meter-12', application_ids: { application_id: 'water' } },
  received_at: '2026-10-11T09:30:00Z',
  uplink_message: { decoded_payload: { flow_lpm: 12.4, battery_v: 3.6 } },
};

const ZIGBEE = { temperature: 21.3, humidity: 45, battery: 97, linkquality: 120 };

const PRODUCT = { serial: 'SN-77812', model: 'HX-200', ts: 1760175000, metrics: { temp_c: 41.2, power_w: 180, door_open: false } };

const ORDER = { type: 'order.created', order_id: 'o-1001', service: 'checkout-api', amount: 42.5, currency: 'EUR', latency_ms: 113, ts: '2026-10-11T09:30:00Z' };

const pretty = (o: unknown) => JSON.stringify(o, null, 2);

const telematicsMapping: Partial<Mapping> = {
  group: 'fleet',
  node: '$.vehicle_id',
  timestamp: { path: '$.timestamp', format: 'iso' },
  signals: { include: [], exclude: ['$.vehicle_id'], flatten: true, units: { speed_kmh: 'km/h', odometer_km: 'km', fuel_pct: '%', 'engine/rpm': 'rpm', 'engine/coolant_c': '°C' } },
};

export const GUIDE: GuideCategory[] = [
  {
    id: 'vehicles',
    title: 'Trucks and vans',
    examples: 'Delivery vans, trucks, plant vehicles, trailers',
    icon: 'truck',
    paths: [
      {
        id: 'telematics-webhook',
        title: 'Your telematics provider already collects the data',
        text: 'Most fleets already have a tracking provider. Ask it to send its data feed to a webhook address. Abenix gives you the address and a token, and maps each message to a vehicle.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'Fleet telematics', mapping: telematicsMapping, sample: pretty(TELEMATICS) },
      },
      {
        id: 'telematics-stream',
        title: 'Your provider offers a data stream instead',
        text: 'Some providers publish to Kafka or MQTT rather than a webhook. Connect to that stream with the details they give you. The same vehicle mapping applies.',
        action: { kind: 'source', transport: 'kafka', decoder: 'json', name: 'Fleet telematics stream', mapping: telematicsMapping, sample: pretty(TELEMATICS) },
      },
      {
        id: 'trackers',
        title: 'Your trackers can send MQTT or HTTP themselves',
        text: 'Point each tracker at Abenix and give each one its own device key, made under Device keys. A key is tied to one device id, so each tracker shows up as itself and cannot send as another.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'Vehicle trackers', mapping: { group: 'fleet', node: '', timestamp: { path: '$.ts', format: 'epoch_ms' } }, sample: pretty(TRACKER) },
      },
      {
        id: 'vehicle-bus',
        title: 'You want engine data straight off the vehicle bus',
        text: 'For J1939 or OBD-II data such as engine speed, fuel rate and fault codes, a small gateway in the vehicle reads the CAN bus and sends it on. It keeps data while out of coverage and sends it when back.',
        code: 'This needs Abenix Edge on an in-vehicle Linux gateway with a CAN interface, because nothing in the cloud can read the bus. Abenix ships Edge and you install it with one command from the Edge page.',
        action: { kind: 'edge', collector: 'can' },
      },
    ],
  },
  {
    id: 'machinery',
    title: 'Machinery and PLCs',
    examples: 'Production lines, compressors, pumps, cranes, packaging machines',
    icon: 'factory',
    paths: [
      {
        id: 'opcua',
        title: 'OPC UA, straight from the server',
        text: 'If Abenix can reach the PLC or OPC UA server on the network, pick the nodes to watch and their values arrive as they change.',
        action: { kind: 'source', transport: 'opcua', name: 'Line 1 PLC' },
      },
      {
        id: 'modbus',
        title: 'Modbus TCP, read every few seconds',
        text: 'For meters and simpler controllers, list the registers to read with their type, scale and unit. Abenix polls them.',
        action: { kind: 'source', transport: 'modbus_tcp', name: 'Meter panel' },
      },
      {
        id: 'sparkplug',
        title: 'You already run SCADA or an MQTT stack',
        text: 'If your gateways speak Sparkplug B, connect the broker. Machines and their parts appear by themselves from their birth messages.',
        action: { kind: 'source', transport: 'mqtt', decoder: 'sparkplug_b', name: 'Site broker', config: { subjects: 'spBv1.0/#' } },
      },
      {
        id: 'site-edge',
        title: 'The machines are on a closed site network',
        text: 'Install a gateway on the site network. It reads OPC UA, Modbus TCP or RTU over serial, or CAN, and sends the data out over one secure connection.',
        code: 'This needs Abenix Edge on a small computer on the site network, because the cloud cannot reach the machines directly. Install it from the Edge page.',
        action: { kind: 'edge', collector: 'modbus' },
      },
    ],
  },
  {
    id: 'sensors',
    title: 'Sensors and IoT',
    examples: 'Temperature and humidity, water meters, air quality, door sensors',
    icon: 'sensor',
    paths: [
      {
        id: 'chirpstack',
        title: 'LoRaWAN through ChirpStack',
        text: 'Turn on the MQTT integration in ChirpStack and connect to its broker. Each sensor becomes an asset named after the device, with its decoded values.',
        action: { kind: 'source', transport: 'mqtt', decoder: 'json', name: 'LoRaWAN sensors', config: { subjects: 'application/+/device/+/event/up' }, subject: 'application/7d1f/device/0004a30b001c1b2e/event/up', mapping: { group: '$.deviceInfo.applicationName', node: '$.deviceInfo.deviceName', timestamp: { path: '$.time', format: 'iso' }, signals: { include: [], exclude: [], flatten: true, units: { temperature: '°C', humidity: '%', battery_v: 'V' }, root: '$.object' } }, sample: pretty(CHIRPSTACK) },
      },
      {
        id: 'tts',
        title: 'LoRaWAN through The Things Stack',
        text: 'Add a webhook integration in The Things Stack pointing at Abenix. Each uplink arrives with its decoded payload.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'LoRaWAN uplinks', mapping: { group: '$.end_device_ids.application_ids.application_id', node: '$.end_device_ids.device_id', timestamp: { path: '$.received_at', format: 'iso' }, signals: { include: [], exclude: [], flatten: true, units: { flow_lpm: 'L/min', battery_v: 'V' }, root: '$.uplink_message.decoded_payload' } }, sample: pretty(TTS) },
      },
      {
        id: 'zigbee',
        title: 'Zigbee or BLE hubs',
        text: 'Hubs like Zigbee2MQTT publish each sensor on its own MQTT topic. Connect to the hub broker and the topic names the sensor.',
        action: { kind: 'source', transport: 'mqtt', decoder: 'json', name: 'Zigbee hub', config: { subjects: 'zigbee2mqtt/+' }, subject: 'zigbee2mqtt/office-sensor', mapping: { group: 'building', node: '{subject.1}', signals: { include: [], exclude: ['linkquality'], flatten: true, units: { temperature: '°C', humidity: '%', battery: '%' } } }, sample: pretty(ZIGBEE) },
      },
      {
        id: 'cellular',
        title: 'Cellular sensors that post over HTTP',
        text: 'Sensors with their own SIM can post straight to Abenix. Give each one its own device key, and each shows up as its own asset.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'Cellular sensors', mapping: { group: 'sensors', node: '' }, sample: pretty({ ts: 1760175000000, temperature_c: 6.1, battery_v: 3.5 }) },
      },
    ],
  },
  {
    id: 'products',
    title: 'Electronics and connected products',
    examples: 'Appliances, chargers, kiosks, medical or lab equipment you make or run',
    icon: 'plug',
    paths: [
      {
        id: 'product-cloud',
        title: 'The product has its own cloud',
        text: 'Ask the product cloud for a webhook, Kafka or MQTT feed. Each unit becomes an asset by its serial number.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'Product fleet', mapping: { group: '$.model', node: '$.serial', timestamp: { path: '$.ts', format: 'epoch_s' }, signals: { include: [], exclude: [], flatten: true, units: { temp_c: '°C', power_w: 'W' }, root: '$.metrics' } }, sample: pretty(PRODUCT) },
      },
      {
        id: 'product-direct',
        title: 'The devices post directly',
        text: 'Devices you build can post JSON to Abenix over HTTPS, each with its own device key, so each shows up as itself.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'Devices', mapping: { group: 'devices', node: '' }, sample: pretty({ ts: 1760175000000, temp_c: 38.5, fan_rpm: 2100 }) },
      },
    ],
  },
  {
    id: 'software',
    title: 'Software systems',
    examples: 'Order and payment services, ERP, app events, logs with numbers',
    icon: 'code',
    paths: [
      {
        id: 'kafka',
        title: 'Kafka, Redpanda or Event Hubs',
        text: 'Read a topic your services already publish to. Each event can be kept whole, and its numbers become signals.',
        action: { kind: 'source', transport: 'kafka', decoder: 'json', name: 'Order events', mapping: { group: 'payments', node: '$.service', timestamp: { path: '$.ts', format: 'iso' }, event: { name: '$.type' }, signals: { include: ['amount', 'latency_ms'], exclude: [], flatten: true, units: { latency_ms: 'ms' } } }, sample: pretty(ORDER) },
      },
      {
        id: 'amqp',
        title: 'RabbitMQ',
        text: 'Read from a queue, bound to the exchange your services publish to.',
        action: { kind: 'source', transport: 'amqp', decoder: 'json', name: 'App events', mapping: { group: 'apps', node: '$.service', event: { name: '$.type' } }, sample: pretty(ORDER) },
      },
      {
        id: 'nats',
        title: 'NATS or JetStream',
        text: 'Read subjects from NATS. JetStream keeps your place across restarts.',
        action: { kind: 'source', transport: 'nats', decoder: 'json', name: 'NATS events', mapping: { group: 'apps', node: '{subject.0}' }, sample: pretty(ORDER) },
      },
      {
        id: 'webhook',
        title: 'A webhook or HTTP push',
        text: 'Any system that can call a URL can post to Abenix. JSON, one JSON per line, CSV and text all work.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'Webhook', sample: pretty(ORDER), mapping: { group: 'apps', node: '$.service', event: { name: '$.type' } } },
      },
      {
        id: 'sdk',
        title: 'From your own code',
        text: 'If a system has no feed at all, a few lines with the Abenix SDK or plain HTTP send its data. The snippet is ready to copy once a push source exists.',
        code: 'This needs a small piece of code in or next to that system, because it has no way to send data on its own.',
        action: { kind: 'source', transport: 'http_push', decoder: 'json', name: 'From code', sample: pretty({ asset: 'billing-worker', queue_depth: 12, ts: 1760175000000 }), mapping: { group: 'apps', node: '$.asset' } },
      },
    ],
  },
];

export function edgeHref(collector: string): string {
  return `/edge?add=gateway&collector=${encodeURIComponent(collector)}`;
}
