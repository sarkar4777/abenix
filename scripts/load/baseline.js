// k6 baseline smoke load test for Abenix. See
// docs/06-deployment/load-test-baseline.md for the reading guide.
//
//   BASE=http://localhost:8000 k6 run scripts/load/baseline.js
//
// Optional env:
//   EMAIL    (default admin@abenix.dev)
//   PASSWORD (default Admin123456)
//   LOGIN_RPS (default 4, a bcrypt check costs about a quarter of a CPU second, so size this to the API)

import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE || 'http://localhost:8000';
const EMAIL = __ENV.EMAIL || 'admin@abenix.dev';
const PASSWORD = __ENV.PASSWORD || 'Admin123456';

export const options = {
  scenarios: {
    health_ready: {
      executor: 'constant-arrival-rate',
      rate: 100, timeUnit: '1s', duration: '60s',
      preAllocatedVUs: 10, maxVUs: 20,
      exec: 'healthReady',
    },
    auth_login: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.LOGIN_RPS || 4), timeUnit: '1s', duration: '30s',
      preAllocatedVUs: 10, maxVUs: 20,
      startTime: '70s',
      exec: 'authLogin',
    },
    list_agents: {
      executor: 'constant-arrival-rate',
      rate: 50, timeUnit: '1s', duration: '60s',
      preAllocatedVUs: 20, maxVUs: 40,
      startTime: '110s',
      exec: 'listAgents',
    },
  },
  thresholds: {
    'http_req_duration{scenario:health_ready}': ['p(99)<100'],
    'http_req_duration{scenario:auth_login}':   ['p(95)<400'],
    'http_req_duration{scenario:list_agents}':  ['p(99)<400'],
    'http_req_failed': ['rate<0.01'],
  },
};

// signs in once, a login per VU would land in the list_agents numbers
export function setup() {
  const r = http.post(`${BASE}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  return { token: r.json('data.access_token') };
}

export function healthReady() {
  const r = http.get(`${BASE}/api/health/ready`);
  check(r, { 'status 200': (x) => x.status === 200 });
}

export function authLogin() {
  const r = http.post(`${BASE}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(r, {
    'status 200': (x) => x.status === 200,
    'has access_token': (x) => !!x.json('data.access_token'),
  });
}

export function listAgents(data) {
  const t = data.token;
  const r = http.get(`${BASE}/api/agents`,
    { headers: { Authorization: `Bearer ${t}` } },
  );
  check(r, { 'status 200': (x) => x.status === 200 });
  sleep(0.05);
}
