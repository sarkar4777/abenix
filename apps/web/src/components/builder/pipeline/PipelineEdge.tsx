'use client';

import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from 'reactflow';
import { X } from 'lucide-react';

// Data interface

export interface PipelineEdgeData {
  label?: string;
  animated?: boolean;
  onDelete?: () => void;
}

// PipelineEdge component

export default function PipelineEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  style,
}: EdgeProps<PipelineEdgeData>) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const isAnimated = data?.animated ?? false;

  return (
    <>
      {/* Animated flowing-dash layer (rendered beneath the solid stroke) */}
      {isAnimated && (
        <BaseEdge
          id={`${id}-animated`}
          path={edgePath}
          style={{
            stroke: '#10b981', // emerald-500
            strokeWidth: 2,
            strokeDasharray: '6 4',
            animation: 'pipelineEdgeFlow 0.6s linear infinite',
            ...style,
          }}
        />
      )}

      {/* Primary solid edge */}
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: '#10b981', // emerald-500
          strokeWidth: 2,
          opacity: isAnimated ? 0.35 : 1,
          ...style,
        }}
      />

      {/* Label and delete control at midpoint */}
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan pointer-events-auto absolute flex items-center gap-1"
          style={{
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          }}
        >
          {/* Field label badge */}
          {data?.label && (
            <span className="bg-slate-700 text-[9px] text-slate-300 px-1.5 py-0.5 rounded select-none whitespace-nowrap">
              {data.label}
            </span>
          )}

          {/* Delete button — visible only when edge is selected */}
          {selected && data?.onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                data.onDelete?.();
              }}
              className="w-4 h-4 bg-red-500 hover:bg-red-400 rounded-full flex items-center justify-center shadow-lg transition-colors"
            >
              <X className="w-2.5 h-2.5 text-white" />
            </button>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

// Edge type registry for React Flow

export const pipelineEdgeTypes = {
  pipeline: PipelineEdge,
};
