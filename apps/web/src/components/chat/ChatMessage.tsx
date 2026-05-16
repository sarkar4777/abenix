'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/atom-one-dark.css';
import { ChevronDown, ChevronUp, User, Bot, Wrench, AlertCircle, GitBranch, Check, XCircle, SkipForward } from 'lucide-react';
import type { ContentBlock, ToolBlock, PipelineNodeBlock } from '@/stores/chatStore';
import { renderRich } from './RichRenderer';

function ToolCallCard({ block }: { block: ToolBlock }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-3 my-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left"
      >
        <div className="flex items-center gap-2">
          <Wrench className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-mono text-cyan-400">{block.name}</span>
          {block.result !== undefined && (
            <span className="text-xs text-emerald-400/70">completed</span>
          )}
          {block.result === undefined && (
            <span className="flex items-center gap-1 text-xs text-amber-400/70">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              running
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          <div>
            <p className="text-xs text-slate-500 mb-1">Arguments</p>
            <pre className="text-xs text-slate-300 bg-slate-950/50 rounded p-2 overflow-x-auto">
              {JSON.stringify(block.arguments, null, 2)}
            </pre>
          </div>
          {block.result !== undefined && (
            <div>
              <p className="text-xs text-slate-500 mb-1">Result</p>
              {block.isError ? (
                <div className="flex items-start gap-1.5 text-xs text-red-400 bg-red-500/10 rounded p-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{block.result}</span>
                </div>
              ) : (
                <pre className="text-xs text-slate-300 bg-slate-950/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                  {block.result}
                </pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const nodeStatusConfig = {
  running: {
    icon: <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />,
    label: 'running',
    color: 'text-amber-400/70',
    border: 'border-amber-500/20',
  },
  completed: {
    icon: <Check className="w-3 h-3 text-emerald-400" />,
    label: 'completed',
    color: 'text-emerald-400/70',
    border: 'border-emerald-500/20',
  },
  failed: {
    icon: <XCircle className="w-3 h-3 text-red-400" />,
    label: 'failed',
    color: 'text-red-400/70',
    border: 'border-red-500/20',
  },
  skipped: {
    icon: <SkipForward className="w-3 h-3 text-slate-500" />,
    label: 'skipped',
    color: 'text-slate-500',
    border: 'border-slate-700/50',
  },
};

function PipelineNodeCard({ block }: { block: PipelineNodeBlock }) {
  const cfg = nodeStatusConfig[block.status];

  return (
    <div className={`flex items-center gap-2.5 bg-slate-900/50 border ${cfg.border} rounded-lg px-3 py-2 my-1`}>
      <GitBranch className="w-3.5 h-3.5 text-purple-400" />
      <span className="text-xs font-mono text-slate-300">{block.nodeId}</span>
      <span className="text-[10px] text-slate-500">{block.toolName}</span>
      <span className="ml-auto flex items-center gap-1">
        {cfg.icon}
        <span className={`text-xs ${cfg.color}`}>{cfg.label}</span>
      </span>
      {block.durationMs !== undefined && (
        <span className="text-[10px] text-slate-600">{block.durationMs}ms</span>
      )}
    </div>
  );
}

interface ChatMessageProps {
  role: 'user' | 'assistant';
  blocks: ContentBlock[];
  isStreaming?: boolean;
}

export default function ChatMessage({ role, blocks, isStreaming }: ChatMessageProps) {
  const isUser = role === 'user';

  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0 mt-1">
          <Bot className="w-4 h-4 text-cyan-400" />
        </div>
      )}

      <div
        className={`${
          isUser
            ? 'bg-cyan-600/20 border border-cyan-500/20 rounded-2xl rounded-br-sm max-w-[70%]'
            : 'bg-slate-800/50 border border-slate-700/50 rounded-2xl rounded-bl-sm max-w-[80%]'
        } p-4`}
      >
        {blocks.map((block, i) => {
          if (block.type === 'text') {
            // Dynamic rich rendering — detect FEN chess boards, mermaid,
            // structured JSON with table/image/fen keys, etc. Anything not
            // recognised falls through to the markdown renderer below.
            const rich = !isUser ? renderRich(block.content) : null;
            const bodyText = rich ? rich.remainingText : block.content;
            return (
              <div key={i} className={`prose prose-invert prose-sm max-w-none ${isUser ? 'text-white' : 'text-slate-200'}`}>
                {rich && rich.widgets.length > 0 && (
                  <div className="not-prose space-y-1">{rich.widgets}</div>
                )}
                {bodyText.trim() ? (
                <ReactMarkdown
                  rehypePlugins={[rehypeHighlight]}
                  components={{
                    pre: ({ children }) => (
                      <pre className="bg-slate-950/50 border border-slate-700/50 rounded-lg p-3 my-2 overflow-x-auto">
                        {children}
                      </pre>
                    ),
                    code: ({ className, children, ...props }) => {
                      const isInline = !className;
                      if (isInline) {
                        return (
                          <code className="bg-slate-700/50 text-cyan-300 px-1.5 py-0.5 rounded text-xs" {...props}>
                            {children}
                          </code>
                        );
                      }
                      return (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    },
                  }}
                >
                  {bodyText}
                </ReactMarkdown>
                ) : null}
                {isStreaming && i === blocks.length - 1 && (
                  <span className="inline-block w-2 h-4 bg-cyan-400 animate-pulse ml-0.5 align-middle" />
                )}
              </div>
            );
          }
          if (block.type === 'tool') {
            return <ToolCallCard key={i} block={block} />;
          }
          if (block.type === 'pipeline_node') {
            return <PipelineNodeCard key={i} block={block} />;
          }
          return null;
        })}

        {isStreaming && blocks.length === 0 && (
          <div className="flex items-center gap-1.5 text-sm text-slate-400">
            <span>Agent is thinking</span>
            <span className="flex gap-0.5">
              <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
            </span>
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center shrink-0 mt-1">
          <User className="w-4 h-4 text-purple-400" />
        </div>
      )}
    </div>
  );
}
