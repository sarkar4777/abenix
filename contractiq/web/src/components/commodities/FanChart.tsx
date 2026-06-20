'use client';

import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

export interface FanPoint {
  tenor: string;
  expected?: number | null;
  p10?: number | null;
  p90?: number | null;
  base?: number | null;
  band?: number | null; // P90 - P10, used to render the diff layer
}

export interface FanChartForecast {
  base_curve?: { tenor: string; mid: number }[];
  expected_curve?: { tenor: string; expected: number }[];
  p10?: { tenor: string; value: number }[];
  p90?: { tenor: string; value: number }[];
}

interface Props {
  forecast?: FanChartForecast | null;
  unit?: string;
  height?: number;
  title?: string;
  /**
   * Retained for backwards-compat. The base curve is always model-derived
   * (the fairvalue YAML admits base == MC expected even on the "live"
   * path), so the dashed series is always labelled "Base (model)".
   */
  dataQuality?: string | null;
}

function mergePoints(forecast?: FanChartForecast | null): FanPoint[] {
  if (!forecast) return [];
  const byTenor = new Map<string, FanPoint>();
  const upsert = (tenor: string, patch: Partial<FanPoint>) => {
    const existing = byTenor.get(tenor) ?? { tenor };
    byTenor.set(tenor, { ...existing, ...patch });
  };
  (forecast.expected_curve || []).forEach(p => upsert(p.tenor, { expected: p.expected }));
  (forecast.base_curve || []).forEach(p => upsert(p.tenor, { base: p.mid }));
  (forecast.p10 || []).forEach(p => upsert(p.tenor, { p10: p.value }));
  (forecast.p90 || []).forEach(p => upsert(p.tenor, { p90: p.value }));
  // band = P90 - P10. Stacked on top of P10 it renders the confidence
  // ribbon correctly regardless of the surrounding background colour.
  return Array.from(byTenor.values()).map(pt => {
    const band =
      typeof pt.p90 === 'number' && typeof pt.p10 === 'number'
        ? Math.max(0, pt.p90 - pt.p10)
        : null;
    return { ...pt, band };
  });
}

export function FanChart({
  forecast,
  unit = '',
  height = 320,
  title,
  dataQuality: _dataQuality,
}: Props) {
  const points = mergePoints(forecast);
  const hasData = points.length > 0;
  // Always "Base (model)" — the fairvalue YAML admits base == MC expected
  // even on the live path, so calling it "Observed" would overstate what
  // the dashed series represents.
  const baseLabel = 'Base (model)';

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-white">{title || 'Forward fan chart'}</h2>
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          P10 / Expected / P90 {unit ? `· ${unit}` : ''}
        </span>
      </div>
      {!hasData ? (
        <div
          data-testid="fan-chart-empty"
          className="h-72 flex items-center justify-center text-xs text-slate-500"
        >
          Run analysis to populate the fan chart.
        </div>
      ) : (
        <div data-testid="fan-chart">
          <ResponsiveContainer width="100%" height={height}>
            <ComposedChart data={points} margin={{ top: 10, right: 16, left: 0, bottom: 8 }}>
              <defs>
                <linearGradient id="fan-band-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0.12} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="#1e293b" />
              <XAxis dataKey="tenor" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} domain={['auto', 'auto']} />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {/* Stacked Areas — the P10 layer is invisible, the band */}
              {/* layer on top renders (P90 - P10). The result is a true */}
              {/* shaded interval that works on any background colour. */}
              <Area
                type="monotone"
                dataKey="p10"
                stackId="fan"
                stroke="none"
                fill="transparent"
                legendType="none"
                isAnimationActive={false}
                activeDot={false}
                name="P10"
              />
              <Area
                type="monotone"
                dataKey="band"
                stackId="fan"
                stroke="none"
                fill="url(#fan-band-grad)"
                fillOpacity={1}
                isAnimationActive={false}
                activeDot={false}
                name="P10 - P90 band"
              />
              <Line
                type="monotone"
                dataKey="expected"
                stroke="#10b981"
                strokeWidth={2.5}
                dot={false}
                name="Expected"
              />
              <Line
                type="monotone"
                dataKey="base"
                stroke="#94a3b8"
                strokeDasharray="3 3"
                strokeWidth={1.5}
                dot={false}
                name={baseLabel}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default FanChart;
