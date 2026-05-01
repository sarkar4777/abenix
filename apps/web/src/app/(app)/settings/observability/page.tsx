'use client';

import { useState, useEffect } from 'react';
import { Activity, Server, Database, Wifi, AlertTriangle, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface HealthStatus {
  status: string;
  postgres: string;
  redis: string;
  neo4j: string;
  llm_provider: string;
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'ok') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
        <CheckCircle className="w-3 h-3" aria-hidden="true" />
        Healthy
      </span>
    );
  }
  if (status === 'unavailable') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20">
        <XCircle className="w-3 h-3" aria-hidden="true" />
        Down
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">
      <AlertTriangle className="w-3 h-3" aria-hidden="true" />
      {status}
    </span>
  );
}

export default function ObservabilityPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [metricsUrl, setMetricsUrl] = useState('');

  const fetchHealth = async () => {
    setLoading(true);
    const res = await apiFetch<HealthStatus>('/api/health/ready', { silent: true });
    if (res.data) setHealth(res.data);
    setLoading(false);
  };

  useEffect(() => {
    fetchHealth();
    setMetricsUrl(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/metrics`);
  }, []);

  const services = health
    ? [
        { name: 'PostgreSQL', key: 'postgres', icon: Database, status: health.postgres },
        { name: 'Redis', key: 'redis', icon: Server, status: health.redis },
        { name: 'Neo4j', key: 'neo4j', icon: Wifi, status: health.neo4j },
        { name: 'LLM Provider', key: 'llm', icon: Activity, status: health.llm_provider },
      ]
    : [];

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">System Health & Observability</h1>
          <p className="text-sm text-slate-400 mt-1">Monitor infrastructure health, metrics, and SLOs</p>
        </div>
        <button
          onClick={fetchHealth}
          disabled={loading}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-700/50 border border-slate-600 text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-50 transition-colors"
          aria-label="Refresh health status"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          Refresh
        </button>
      </div>

      {/* Overall Status */}
      {health && (
        <div className={`rounded-xl border p-4 ${
          health.status === 'ok'
            ? 'border-emerald-500/20 bg-emerald-500/5'
            : 'border-yellow-500/20 bg-yellow-500/5'
        }`} role="status" aria-label="Overall system status">
          <div className="flex items-center gap-3">
            {health.status === 'ok' ? (
              <CheckCircle className="w-6 h-6 text-emerald-400" aria-hidden="true" />
            ) : (
              <AlertTriangle className="w-6 h-6 text-yellow-400" aria-hidden="true" />
            )}
            <div>
              <p className="text-sm font-semibold text-white">
                System Status: {health.status === 'ok' ? 'All Systems Operational' : 'Degraded'}
              </p>
              <p className="text-xs text-slate-400">
                {services.filter((s) => s.status === 'ok').length}/{services.length} services healthy
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Service Health Grid */}
      <div>
        <h2 className="text-sm font-semibold text-slate-300 mb-3">Infrastructure Services</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {services.map((svc) => {
            const Icon = svc.icon;
            return (
              <div
                key={svc.key}
                className="flex items-center justify-between rounded-lg border border-slate-700/50 bg-slate-800/50 p-4"
              >
                <div className="flex items-center gap-3">
                  <Icon className="w-5 h-5 text-slate-400" aria-hidden="true" />
                  <span className="text-sm text-white">{svc.name}</span>
                </div>
                <StatusBadge status={svc.status} />
              </div>
            );
          })}
        </div>
      </div>

      {/* SLO Targets */}
      <div>
        <h2 className="text-sm font-semibold text-slate-300 mb-3">SLO Targets</h2>
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 overflow-hidden">
          <table className="w-full text-sm" aria-label="Service Level Objectives">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="text-left py-2.5 px-4 text-slate-400 font-medium">Objective</th>
                <th className="text-right py-2.5 px-4 text-slate-400 font-medium">Target</th>
                <th className="text-right py-2.5 px-4 text-slate-400 font-medium">Window</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-slate-700/30">
                <td className="py-2.5 px-4 text-white">API Availability</td>
                <td className="py-2.5 px-4 text-right text-emerald-400">99.9%</td>
                <td className="py-2.5 px-4 text-right text-slate-400">30 days</td>
              </tr>
              <tr className="border-b border-slate-700/30">
                <td className="py-2.5 px-4 text-white">API Latency (p95)</td>
                <td className="py-2.5 px-4 text-right text-emerald-400">&lt; 500ms</td>
                <td className="py-2.5 px-4 text-right text-slate-400">30 days</td>
              </tr>
              <tr className="border-b border-slate-700/30">
                <td className="py-2.5 px-4 text-white">Execution Latency (p95)</td>
                <td className="py-2.5 px-4 text-right text-emerald-400">&lt; 30s</td>
                <td className="py-2.5 px-4 text-right text-slate-400">30 days</td>
              </tr>
              <tr>
                <td className="py-2.5 px-4 text-white">SSE Connection Success</td>
                <td className="py-2.5 px-4 text-right text-emerald-400">99.0%</td>
                <td className="py-2.5 px-4 text-right text-slate-400">30 days</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Quick Links */}
      <div>
        <h2 className="text-sm font-semibold text-slate-300 mb-3">Quick Links</h2>
        <div className="flex flex-wrap gap-3">
          <a
            href={metricsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-700/50 border border-slate-600 text-sm text-slate-300 hover:bg-slate-700 transition-colors"
          >
            <Activity className="w-4 h-4" aria-hidden="true" />
            Prometheus Metrics
          </a>
          <a
            href="/api/health/ready"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-700/50 border border-slate-600 text-sm text-slate-300 hover:bg-slate-700 transition-colors"
          >
            <Server className="w-4 h-4" aria-hidden="true" />
            Health Check JSON
          </a>
        </div>
      </div>
    </div>
  );
}
