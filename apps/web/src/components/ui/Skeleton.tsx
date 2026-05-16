'use client';

import { cn } from '@/lib/utils';


interface SkeletonBoxProps {
  className?: string;
}

export function SkeletonBox({ className }: SkeletonBoxProps) {
  return (
    <div
      className={cn('bg-slate-800 animate-pulse rounded', className)}
    />
  );
}

interface SkeletonTextProps {
  className?: string;
  lines?: number;
}

export function SkeletonText({ className, lines = 1 }: SkeletonTextProps) {
  const widths = ['w-full', 'w-3/4', 'w-5/6', 'w-2/3', 'w-4/5'];
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={cn(
            'h-3 bg-slate-800 animate-pulse rounded',
            widths[i % widths.length],
          )}
        />
      ))}
    </div>
  );
}

interface SkeletonCircleProps {
  className?: string;
  size?: number;
}

export function SkeletonCircle({ className, size = 10 }: SkeletonCircleProps) {
  return (
    <div
      className={cn(
        'bg-slate-800 animate-pulse rounded-full shrink-0',
        className,
      )}
      style={{ width: `${size * 4}px`, height: `${size * 4}px` }}
    />
  );
}


export function SkeletonStatCard() {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-start justify-between mb-3">
        <div className="w-10 h-10 rounded-lg bg-slate-700/50 animate-pulse" />
        <div className="h-3 w-16 bg-slate-800 animate-pulse rounded" />
      </div>
      <div className="h-7 w-24 bg-slate-800 animate-pulse rounded mb-1" />
      <div className="h-3 w-16 bg-slate-700/50 animate-pulse rounded" />
    </div>
  );
}

export function SkeletonAgentCard() {
  return (
    <div className="bg-slate-800/30 backdrop-blur border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-start justify-between mb-3">
        <div className="w-10 h-10 rounded-lg bg-slate-700/50 animate-pulse" />
        <div className="h-5 w-14 bg-slate-800 animate-pulse rounded-full" />
      </div>
      <div className="h-4 w-32 bg-slate-800 animate-pulse rounded mb-1" />
      <div className="space-y-1.5 mb-3">
        <div className="h-3 w-full bg-slate-700/50 animate-pulse rounded" />
        <div className="h-3 w-4/5 bg-slate-700/50 animate-pulse rounded" />
      </div>
      <div className="flex items-center gap-2 mb-4">
        <div className="h-4 w-16 bg-slate-800 animate-pulse rounded" />
        <div className="h-4 w-20 bg-slate-800 animate-pulse rounded" />
        <div className="h-4 w-10 bg-slate-800 animate-pulse rounded" />
      </div>
      <div className="flex items-center gap-2 pt-3 border-t border-slate-700/30">
        <div className="flex-1 h-8 bg-slate-700/50 animate-pulse rounded-lg" />
        <div className="h-8 w-16 bg-slate-800 animate-pulse rounded-lg" />
      </div>
    </div>
  );
}

interface SkeletonTableRowProps {
  columns?: number;
}

export function SkeletonTableRow({ columns = 5 }: SkeletonTableRowProps) {
  const widths = ['w-24', 'w-32', 'w-20', 'w-28', 'w-16'];
  return (
    <div className="flex items-center gap-4 px-5 py-3.5 border-b border-slate-700/30">
      {Array.from({ length: columns }).map((_, i) => (
        <div
          key={i}
          className={cn(
            'h-3 bg-slate-800 animate-pulse rounded',
            widths[i % widths.length],
            i === 0 ? 'flex-shrink-0' : 'flex-1',
          )}
        />
      ))}
    </div>
  );
}

export function SkeletonChartCard() {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
        <div className="h-4 w-28 bg-slate-800 animate-pulse rounded" />
        <div className="h-3 w-16 bg-slate-700/50 animate-pulse rounded" />
      </div>
      <div className="p-5">
        <div
          className="w-full rounded-lg animate-pulse"
          style={{
            height: '260px',
            background:
              'linear-gradient(180deg, rgba(51,65,85,0.3) 0%, rgba(51,65,85,0.08) 100%)',
          }}
        />
      </div>
    </div>
  );
}

export function SkeletonChatMessage() {
  return (
    <div className="flex gap-3 py-4">
      <div className="w-8 h-8 rounded-full bg-slate-800 animate-pulse shrink-0" />
      <div className="flex-1 space-y-2 pt-0.5">
        <div className="h-3 w-5/6 bg-slate-800 animate-pulse rounded" />
        <div className="h-3 w-3/4 bg-slate-700/50 animate-pulse rounded" />
        <div className="h-3 w-2/3 bg-slate-700/50 animate-pulse rounded" />
      </div>
    </div>
  );
}


export function DashboardSkeleton() {
  return (
    <div className="space-y-6 max-w-[1400px]">
      {/* Header */}
      <div>
        <div className="h-7 w-32 bg-slate-800 animate-pulse rounded" />
        <div className="h-3 w-56 bg-slate-700/50 animate-pulse rounded mt-2" />
      </div>

      {/* 4 KPI stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonStatCard key={i} />
        ))}
      </div>

      {/* Activity panel + sidebar */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Live Activity panel */}
        <div className="lg:col-span-2 bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
            <div className="h-4 w-24 bg-slate-800 animate-pulse rounded" />
            <div className="h-3 w-14 bg-slate-700/50 animate-pulse rounded" />
          </div>
          <div className="p-5 grid grid-cols-1 sm:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="bg-slate-900/50 rounded-lg p-4 border border-slate-700/30"
              >
                <div className="h-3 w-16 bg-slate-700/50 animate-pulse rounded mb-2" />
                <div className="h-6 w-12 bg-slate-800 animate-pulse rounded" />
              </div>
            ))}
          </div>
        </div>

        {/* Quick actions + System status */}
        <div className="space-y-6">
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <div className="h-4 w-24 bg-slate-800 animate-pulse rounded mb-4" />
            <div className="grid grid-cols-2 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="flex flex-col items-center gap-2 p-3 rounded-lg bg-slate-800/50 border border-slate-700/30"
                >
                  <div className="w-9 h-9 rounded-lg bg-slate-700/50 animate-pulse" />
                  <div className="h-3 w-14 bg-slate-700/50 animate-pulse rounded" />
                </div>
              ))}
            </div>
          </div>

          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="h-4 w-24 bg-slate-800 animate-pulse rounded" />
              <div className="h-3 w-16 bg-slate-700/50 animate-pulse rounded" />
            </div>
            <div className="space-y-2.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="h-3 w-20 bg-slate-700/50 animate-pulse rounded" />
                  <div className="h-3 w-14 bg-slate-800 animate-pulse rounded" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AgentsSkeleton() {
  return (
    <div className="space-y-6 max-w-[1400px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="h-7 w-24 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-36 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        <div className="h-9 w-28 bg-slate-700/50 animate-pulse rounded-lg" />
      </div>

      {/* Tabs + search */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex bg-slate-800/50 rounded-lg p-1 border border-slate-700/50">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-7 w-24 bg-slate-700/50 animate-pulse rounded-md mx-0.5"
            />
          ))}
        </div>
        <div className="h-9 w-full md:max-w-sm bg-slate-800/50 border border-slate-700/50 animate-pulse rounded-lg" />
      </div>

      {/* 6 agent cards grid */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonAgentCard key={i} />
        ))}
      </div>
    </div>
  );
}

export function AnalyticsSkeleton() {
  return (
    <div className="space-y-6 max-w-[1400px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="h-7 w-28 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-48 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        <div className="h-8 w-40 bg-slate-800/50 border border-slate-700/50 animate-pulse rounded-lg" />
      </div>

      {/* 5 KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonStatCard key={i} />
        ))}
      </div>

      {/* 4 chart cards (2x2 grid) */}
      <div className="grid lg:grid-cols-2 gap-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonChartCard key={i} />
        ))}
      </div>
    </div>
  );
}

export function KnowledgeSkeleton() {
  return (
    <div className="space-y-6 max-w-[1400px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="h-7 w-36 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-52 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        <div className="h-9 w-36 bg-slate-700/50 animate-pulse rounded-lg" />
      </div>

      {/* 3 KB cards */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5"
          >
            <div className="flex items-start justify-between mb-3">
              <div className="w-10 h-10 rounded-lg bg-slate-700/50 animate-pulse" />
              <div className="h-5 w-16 bg-slate-800 animate-pulse rounded-full" />
            </div>
            <div className="h-4 w-36 bg-slate-800 animate-pulse rounded mb-2" />
            <div className="space-y-1.5 mb-4">
              <div className="h-3 w-full bg-slate-700/50 animate-pulse rounded" />
              <div className="h-3 w-3/4 bg-slate-700/50 animate-pulse rounded" />
            </div>
            <div className="flex items-center gap-4 pt-3 border-t border-slate-700/30">
              <div className="h-3 w-20 bg-slate-700/50 animate-pulse rounded" />
              <div className="h-3 w-20 bg-slate-700/50 animate-pulse rounded" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface TableSkeletonProps {
  rows?: number;
  columns?: number;
}

export function TableSkeleton({ rows = 8, columns = 5 }: TableSkeletonProps) {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
      {/* Table header */}
      <div className="flex items-center gap-4 px-5 py-3 border-b border-slate-700/50">
        {Array.from({ length: columns }).map((_, i) => (
          <div
            key={i}
            className={cn(
              'h-3 bg-slate-700/50 animate-pulse rounded',
              i === 0 ? 'w-28 flex-shrink-0' : 'flex-1',
            )}
          />
        ))}
      </div>

      {/* Table rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonTableRow key={i} columns={columns} />
      ))}
    </div>
  );
}
