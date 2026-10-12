export interface DeviceRow {
  group: string;
  node: string;
  // empty for the node itself
  device: string;
  online: boolean;
  last_seen: string | number | null;
  birth_at: string | number | null;
  msgs_per_sec: number;
  // values a second, a batch of many readings counts as one message
  readings_per_sec?: number | null;
  seq_gaps: number;
  metric_count: number;
  connection_id?: string | null;
  team_id?: string | null;
  team_name?: string | null;
  offline_at?: string | number | null;
}

export type MetricValue = number | string | boolean | null;

export interface Metric {
  name: string;
  value: MetricValue;
  type?: string;
  ts?: string | number | null;
  quality?: string | number | null;
  unit?: string | null;
  writable?: boolean;
}

export interface NodeDetail {
  group: string;
  node: string;
  online?: boolean;
  last_seen?: string | number | null;
  metrics?: Metric[];
  devices: Array<DeviceRow & { metrics?: Metric[] }>;
}

export type ConnectionStatus = 'connected' | 'connecting' | 'error' | 'disabled';

export interface Connection {
  id: string;
  name: string;
  broker_url: string;
  topics: string[];
  raw_topics?: string[] | null;
  username?: string | null;
  // masked on read, never the real value
  password?: string | null;
  has_password?: boolean;
  protocol?: string;
  enabled: boolean;
  status?: ConnectionStatus;
  last_error?: string | null;
  messages_per_second?: number | null;
  last_message_at?: string | null;
  created_by?: string | null;
  created_by_name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  team_id?: string | null;
  team_name?: string | null;
  share_count?: number | null;
  can_manage?: boolean;
  can_edit?: boolean;
  dropped?: number | null;
}

export interface ConnectionTest {
  ok: boolean;
  connected: boolean;
  messages: number;
  topics_seen: string[];
  error: string | null;
}

export interface Quota {
  max_connections?: number | null;
  max_devices?: number | null;
  max_msgs_per_sec?: number | null;
  retention_days?: number | null;
  used?: { connections?: number; devices?: number; msgs_per_sec?: number };
}

export interface Health {
  messages_per_second?: number | null;
  ingest_latency_ms_p50?: number | null;
  ingest_latency_ms_p99?: number | null;
  ingest_latency_ms?: { p50?: number | null; p99?: number | null } | null;
  ingest_up?: boolean;
  replicas?: number;
  messages_per_second_by_node?: Array<{ group: string; node: string; messages_per_second: number }>;
  throttled_messages?: number | null;
  seq_gaps?: number | null;
  dropped?: number | null;
  throttled?: boolean;
  throttle_reason?: string | null;
  nodes_online?: number | null;
  nodes_total?: number | null;
  quota?: Quota | null;
}

export interface HistoryPoint { t: number; v: number }

export interface CommandRequest {
  group: string;
  node: string;
  device: string;
  metric: string;
  value: MetricValue;
  reason: string;
}
