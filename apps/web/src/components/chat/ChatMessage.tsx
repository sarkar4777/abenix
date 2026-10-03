'use client';

import { useState } from 'react';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
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
    <div className="my-1">
    <div className={`flex items-center gap-2.5 bg-slate-900/50 border ${cfg.border} rounded-lg px-3 py-2`}>
      <GitBranch className="w-3.5 h-3.5 text-purple-400" />
      <span className={`text-xs text-slate-300 ${block.label ? "" : "font-mono"}`} title={block.nodeId}>{block.label || block.nodeId}</span>
      <span className="text-[10px] text-slate-500">{block.toolName}</span>
      <span className="ml-auto flex items-center gap-1">
        {cfg.icon}
        <span className={`text-xs ${cfg.color}`}>{cfg.label}</span>
      </span>
      {block.durationMs !== undefined && (
        <span className="text-[10px] text-slate-600">{block.durationMs}ms</span>
      )}
    </div>
    {block.error && (
      <p className="mt-1 ml-6 text-[11px] text-red-300" data-testid="pipeline-node-error">{block.error}</p>
    )}
    </div>
  );
}

interface ChatMessageProps {
  role: 'user' | 'assistant';
  blocks: ContentBlock[];
  isStreaming?: boolean;
  model?: string;
  requestedModel?: string;
  fallbackReason?: string;
  executionId?: string;
}

export default function ChatMessage({ role, blocks, isStreaming, model, requestedModel, fallbackReason, executionId }: ChatMessageProps) {
  const isUser = role === 'user';
  const hasFallback = !!(model && requestedModel && model !== requestedModel);

  return (
    <div data-testid="chat-message" data-role={isUser ? 'user' : 'assistant'} className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
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
            // A text block with no content used to take the whole page down
            // through the error boundary, losing the conversation, because
            // both this and renderRich call .trim() on it.
            const content = typeof block.content === 'string' ? block.content : '';
            // Dynamic rich rendering — detect FEN chess boards, mermaid,
            // structured JSON with table/image/fen keys, etc. Anything not
            // recognised falls through to the markdown renderer below.
            const rich = !isUser ? renderRich(content) : null;
            const bodyText = rich ? rich.remainingText : content;
            return (
              <div key={i} className={`prose prose-invert prose-sm max-w-none ${isUser ? 'text-white' : 'text-slate-200'}`}>
                {rich && rich.widgets.length > 0 && (
                  <div className="not-prose space-y-1">{rich.widgets}</div>
                )}
                {bodyText.trim() ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeHighlight]}
                  components={{
                    // no typography plugin here, so tables, headings and lists need their own styles
                    h1: ({ children }) => <h3 className="text-base font-semibold text-white mt-4 mb-2">{children}</h3>,
                    h2: ({ children }) => <h3 className="text-base font-semibold text-white mt-4 mb-2">{children}</h3>,
                    h3: ({ children }) => <h4 className="text-sm font-semibold text-cyan-200 mt-4 mb-2">{children}</h4>,
                    p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
                    ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>,
                    table: ({ children }) => (
                      <div className="my-3 overflow-x-auto rounded-lg border border-slate-700/60">
                        <table className="w-full text-xs border-collapse">{children}</table>
                      </div>
                    ),
                    th: ({ children }) => <th className="bg-slate-900/70 text-slate-300 font-medium text-left px-2.5 py-1.5 border-b border-slate-700/60">{children}</th>,
                    td: ({ children }) => <td className="px-2.5 py-1.5 border-b border-slate-800/80 align-top">{children}</td>,
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

        {!isUser && !isStreaming && model && (
          <div
            data-testid="chat-message-model"
            className="mt-2 text-[10px] text-slate-500 font-mono flex items-center gap-1.5 flex-wrap"
            title={hasFallback && fallbackReason ? `Fallback reason: ${fallbackReason.replace(/_/g, ' ')}` : undefined}
          >
            <span>{model}</span>
            {hasFallback && (
              <>
                <span className="text-amber-400">&larr;</span>
                <span className="text-amber-300">fallback from {requestedModel}</span>
              </>
            )}
          </div>
        )}

        {!isUser && !isStreaming && executionId && (
          <Link
            href={`/executions/${executionId}`}
            data-testid="chat-view-run"
            className="mt-1.5 inline-flex items-center gap-1 text-[10px] text-cyan-400/80 hover:text-cyan-300 underline-offset-2 hover:underline"
          >
            View run
          </Link>
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
