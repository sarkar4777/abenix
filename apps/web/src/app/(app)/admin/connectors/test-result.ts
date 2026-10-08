export interface TestResult {
  ok: boolean;
  blocked?: boolean;
  latency_ms: number;
  status_code: number | null;
  sample_response_excerpt: string | null;
  message?: string | null;
  error: string | null;
}

// what a test found, in words
export function describeTest(t: TestResult): string {
  if (t.message) return t.message;
  if (t.error) return `Could not reach it: ${t.error.replace(/^connector test failed:\s*/i, '')}`;
  if (t.status_code == null) return 'No answer came back.';
  if (t.status_code < 300) return `Reached it, HTTP ${t.status_code} in ${t.latency_ms} ms.`;
  if (t.status_code < 400) return `Reached it, it answered with a redirect (HTTP ${t.status_code}).`;
  if (t.status_code === 401 || t.status_code === 403) return `The service refused the credentials (HTTP ${t.status_code}). Check the secret and the auth type.`;
  if (t.status_code === 404) return 'It answered HTTP 404. The host is up but nothing is at that address, check the base URL.';
  if (t.status_code < 500) return `It answered HTTP ${t.status_code}, so it did not accept the request.`;
  return `It answered HTTP ${t.status_code}, an error on its side.`;
}
