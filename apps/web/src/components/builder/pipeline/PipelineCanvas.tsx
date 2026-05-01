'use client';

import { useMemo, useRef } from 'react';
import { GripVertical, Link2, Play } from 'lucide-react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { nodeTypes } from '../nodes';
import { pipelineNodeTypes } from './PipelineNodes';
import { pipelineEdgeTypes } from './PipelineEdge';
import { isValidConnection as checkValidConnection } from './pipelineUtils';
import type { PipelineStep } from './pipelineUtils';

// Props

interface PipelineCanvasProps {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: (changes: any) => void;
  onEdgesChange: (changes: any) => void;
  onConnect: (connection: Connection) => void;
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onPaneClick: () => void;
  onNodesDelete: (nodes: Node[]) => void;
  onDragOver: (event: React.DragEvent) => void;
  onDrop: (event: React.DragEvent) => void;
  onInit: (instance: ReactFlowInstance) => void;
  isValidConnection: (connection: Connection) => boolean;
}

// MiniMap node color resolver

function getMiniMapNodeColor(node: Node): string {
  switch (node.type) {
    case 'agent':
      return '#06B6D4'; // cyan-500
    case 'tool':
      return '#06B6D4'; // cyan-500
    case 'knowledge':
      return '#A855F7'; // purple-500
    case 'mcp':
      return '#F59E0B'; // amber-500
    case 'pipelineStep':
      return '#10B981'; // emerald-500
    case 'condition':
      return '#F59E0B'; // amber-500
    case 'output':
      return '#A855F7'; // purple-500
    default:
      return '#475569'; // slate-600
  }
}

// PipelineCanvas

export default function PipelineCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onPaneClick,
  onNodesDelete,
  onDragOver,
  onDrop,
  onInit,
  isValidConnection,
}: PipelineCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  // Merge existing agent-mode node types with pipeline-specific node types
  const mergedNodeTypes = useMemo(
    () => ({
      ...nodeTypes,
      ...pipelineNodeTypes,
    }),
    [],
  );

  const mergedEdgeTypes = useMemo(() => pipelineEdgeTypes, []);

  const hasNodes = nodes.length > 0;

  return (
    <div ref={reactFlowWrapper} className="flex-1 relative h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onNodesDelete={onNodesDelete}
        onDragOver={onDragOver}
        onDrop={onDrop}
        onInit={onInit}
        nodeTypes={mergedNodeTypes}
        edgeTypes={mergedEdgeTypes}
        isValidConnection={isValidConnection}
        connectionLineStyle={{ stroke: '#10B981', strokeWidth: 2 }}
        defaultEdgeOptions={{
          type: 'pipeline',
          style: { stroke: '#10B981', strokeWidth: 2 },
        }}
        proOptions={{ hideAttribution: true }}
        fitView
        deleteKeyCode={['Backspace', 'Delete']}
        style={{ background: '#0B0F19' }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color="#1E293B"
          gap={20}
          size={1}
        />

        <Controls
          className="!bg-slate-800/90 !border-slate-700 !rounded-lg !shadow-lg [&>button]:!bg-slate-800 [&>button]:!border-slate-700 [&>button]:!text-slate-400 [&>button:hover]:!bg-slate-700 [&>button:hover]:!text-white [&>button>svg]:!fill-current"
          showInteractive={false}
        />

        <MiniMap
          nodeColor={getMiniMapNodeColor}
          maskColor="rgba(11, 15, 25, 0.85)"
          className="!bg-slate-900/90 !border-slate-700 !rounded-lg"
          pannable
          zoomable
        />
      </ReactFlow>

      {/* Empty state overlay — 3-step guide (dismissible) */}
      {!hasNodes && !(typeof window !== 'undefined' && localStorage.getItem('abenix:pipeline-onboarding-dismissed')) && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
          <div className="text-center max-w-md px-6 relative pointer-events-auto">
            <button
              onClick={() => { localStorage.setItem('abenix:pipeline-onboarding-dismissed', 'true'); window.location.reload(); }}
              className="absolute -top-2 -right-2 w-6 h-6 bg-slate-700 border border-slate-600 rounded-full flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-600 transition-colors text-xs"
            >&times;</button>
            <h3 className="text-sm font-semibold text-white mb-5">
              Build Your Pipeline
            </h3>

            <div className="flex items-start justify-center gap-6">
              {/* Step 1 */}
              <div className="flex flex-col items-center gap-2 max-w-[100px]">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                  <GripVertical className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <p className="text-[10px] font-semibold text-emerald-400">1. Drag</p>
                  <p className="text-[10px] text-slate-500 leading-tight">
                    Drag steps from the toolbar
                  </p>
                </div>
              </div>

              {/* Arrow */}
              <div className="mt-4 text-slate-700">
                <svg width="24" height="12" viewBox="0 0 24 12" fill="none">
                  <path d="M0 6h20M16 1l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>

              {/* Step 2 */}
              <div className="flex flex-col items-center gap-2 max-w-[100px]">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                  <Link2 className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <p className="text-[10px] font-semibold text-emerald-400">2. Connect</p>
                  <p className="text-[10px] text-slate-500 leading-tight">
                    Link steps to define data flow
                  </p>
                </div>
              </div>

              {/* Arrow */}
              <div className="mt-4 text-slate-700">
                <svg width="24" height="12" viewBox="0 0 24 12" fill="none">
                  <path d="M0 6h20M16 1l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>

              {/* Step 3 */}
              <div className="flex flex-col items-center gap-2 max-w-[100px]">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                  <Play className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <p className="text-[10px] font-semibold text-emerald-400">3. Run</p>
                  <p className="text-[10px] text-slate-500 leading-tight">
                    Execute and view results
                  </p>
                </div>
              </div>
            </div>

            <p className="text-[10px] text-slate-600 mt-5">
              Steps without dependencies will run in parallel automatically
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
