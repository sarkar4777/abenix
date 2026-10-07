export interface MLDeployment {
  id: string;
  deployment_type: string;
  status: string;
  endpoint_url: string | null;
  replicas?: number;
}

export interface MLModel {
  id: string;
  name: string;
  version: string;
  framework: string;
  description: string | null;
  status: string;
  status_message?: string | null;
  is_active: boolean;
  file_size_bytes: number | null;
  original_filename: string | null;
  input_schema: any;
  output_schema: any;
  training_metrics: any;
  tags: string[] | null;
  deployments: MLDeployment[];
  created_at: string;
}

// file types the API can actually run
export const RUNNABLE_EXTENSIONS = ['.joblib', '.pkl', '.onnx', '.pt', '.pth'];
export const UNRUNNABLE_HINTS: Record<string, string> = {
  '.h5': 'TensorFlow/Keras files cannot run on Abenix yet. Convert the model to ONNX (for example with tf2onnx) and upload the .onnx file.',
  '.keras': 'TensorFlow/Keras files cannot run on Abenix yet. Convert the model to ONNX (for example with tf2onnx) and upload the .onnx file.',
};

export const FRAMEWORK_LABELS: Record<string, string> = {
  sklearn: 'scikit-learn', xgboost: 'XGBoost', onnx: 'ONNX', pytorch: 'PyTorch', tensorflow: 'TensorFlow', custom: 'Custom',
};

export function fileExt(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i).toLowerCase() : '';
}

function parseVersion(v: string): number[] | null {
  const parts = v.replace(/^[vV]/, '').split('.');
  if (!parts.length || !parts.every(p => /^\d+$/.test(p))) return null;
  return parts.map(Number);
}

// mirrors _next_version in the API so the placeholder matches what the server picks
export function nextVersion(existing: string[]): string {
  const parsed = existing.map(parseVersion).filter((p): p is number[] => !!p);
  let cand: number[];
  if (!parsed.length) {
    cand = [1, 0, 0];
  } else {
    const top = parsed.reduce((a, b) => {
      for (let i = 0; i < Math.max(a.length, b.length); i++) {
        const x = a[i] ?? -1;
        const y = b[i] ?? -1;
        if (x !== y) return x > y ? a : b;
      }
      return a;
    });
    cand = [top[0], (top[1] ?? 0) + 1, 0];
  }
  const taken = new Set(existing);
  while (taken.has(cand.join('.'))) cand = [cand[0], cand[1] + 1, 0];
  return cand.join('.');
}

export function featureNames(m: MLModel | null): string[] {
  const s = m?.input_schema;
  if (s && Array.isArray(s.features)) return s.features.map(String);
  const order = s?.properties?.input_data?.['x-feature-order'];
  if (Array.isArray(order)) return order.map(String);
  const tm = m?.training_metrics;
  if (tm && Array.isArray(tm.feature_names)) return tm.feature_names.map(String);
  return [];
}

export function featureCount(m: MLModel | null): number | null {
  const names = featureNames(m);
  if (names.length) return names.length;
  const n = m?.input_schema?.properties?.input_data?.items?.minItems ?? m?.training_metrics?.n_features;
  return typeof n === 'number' ? n : null;
}

export function defaultInputFor(m: MLModel | null): string {
  if (!m) return '{"features": []}';
  const ex = m.input_schema?.example;
  if (Array.isArray(ex)) return JSON.stringify({ features: ex });
  if (ex && typeof ex === 'object') return JSON.stringify(ex);
  const n = featureCount(m);
  if (n) return JSON.stringify({ features: Array(n).fill(0) });
  return '{"features": []}';
}

export function fmtBytes(bytes: number | null): string {
  if (!bytes) return '—';
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`;
  return `${bytes} B`;
}

export const INPUT_SCHEMA_TEMPLATE = '{\n  "features": ["feature_1", "feature_2", "feature_3"],\n  "example": [0, 0, 0]\n}';
