'use client';

import { useState, useRef, useEffect, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, Check, CheckCircle2, HelpCircle, Loader2, MessageSquare, Pencil, Play, Rocket, Save, ShieldCheck, Sparkles } from 'lucide-react';
import PublishDialog from './PublishDialog';
import BuilderHelpDialog from './BuilderHelpDialog';
import AIBuilderDialog from './AIBuilderDialog';
import AIValidateDialog from './AIValidateDialog';

export type BuilderMode = 'agent' | 'pipeline';

interface BuilderTopBarProps {
  agentId: string | null;
  name: string;
  onNameChange: (name: string) => void;
  onSave: () => void;
  onPublish: () => void;
  saving: boolean;
  dirty: boolean;
  builderMode: BuilderMode;
  onModeChange: (mode: BuilderMode) => void;
  onRunPipeline?: () => void;
  pipelineRunning?: boolean;
  onAIBuild?: (config: Record<string, unknown>) => void;
  validationErrorCount?: number;
  validationWarningCount?: number;
  isValidating?: boolean;
  hasPipelineSteps?: boolean;
  getDraftForValidate?: () => {
    nodes: unknown[];
    tools: string[];
    context_keys: string[];
    purpose: string;
  } | null;
}

export default function BuilderTopBar({
  agentId,
  name,
  onNameChange,
  onSave,
  onPublish,
  saving,
  dirty,
  builderMode,
  onModeChange,
  onRunPipeline,
  pipelineRunning,
  onAIBuild,
  validationErrorCount = 0,
  validationWarningCount = 0,
  isValidating = false,
  hasPipelineSteps = false,
  getDraftForValidate,
}: BuilderTopBarProps) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(name);
  const inputRef = useRef<HTMLInputElement>(null);
  const [showPublish, setShowPublish] = useState(false);
  const [showAIBuilder, setShowAIBuilder] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showAIValidate, setShowAIValidate] = useState(false);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const commitName = () => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== name) {
      onNameChange(trimmed);
    }
    setEditing(false);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter') commitName();
    if (e.key === 'Escape') {
      setEditValue(name);
      setEditing(false);
    }
  };

  return (
    <div className="h-14 bg-[#0F172A] border-b border-slate-800 flex items-center justify-between px-4 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        {editing ? (
          <input
            ref={inputRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitName}
            onKeyDown={handleKeyDown}
            className="px-2 py-1 bg-slate-800 border border-cyan-500 rounded text-sm text-white focus:outline-none min-w-[200px]"
          />
        ) : (
          <button
            onClick={() => {
              setEditValue(name);
              setEditing(true);
            }}
            className="flex items-center gap-2 text-sm font-semibold text-white hover:text-cyan-400 transition-colors group"
          >
            <span className="truncate max-w-[300px]">{name || 'Untitled Agent'}</span>
            <Pencil className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400" />
          </button>
        )}

        {saving && (
          <span className="flex items-center gap-1.5 text-xs text-slate-500">
            <Loader2 className="w-3 h-3 animate-spin" />
            Saving...
          </span>
        )}
        {!saving && !dirty && agentId && (
          <span className="flex items-center gap-1 text-xs text-emerald-400/70">
            <Check className="w-3 h-3" />
            Saved
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {/* Mode toggle */}
        <div className="flex bg-slate-800 rounded-lg border border-slate-700 p-0.5">
          <button
            onClick={() => onModeChange('agent')}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              builderMode === 'agent'
                ? 'bg-cyan-500/20 text-cyan-400'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Agent mode: iterative LLM tool-use loop"
            aria-label="Switch to Agent mode (iterative tool use)"
          >
            Agent
          </button>
          <button
            onClick={() => onModeChange('pipeline')}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              builderMode === 'pipeline'
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Pipeline mode: DAG workflow with parallel steps"
            aria-label="Switch to Pipeline mode (DAG workflow)"
          >
            Pipeline
          </button>
        </div>

        {/* Help button */}
        <button
          onClick={() => setShowHelp(true)}
          className="p-1.5 text-slate-500 hover:text-slate-300 hover:bg-slate-800 rounded-md transition-colors"
          title="Agent vs Pipeline \u2014 what's the difference?"
        >
          <HelpCircle className="w-4 h-4" />
        </button>

        {/* Pipeline validation status chip */}
        {builderMode === 'pipeline' && hasPipelineSteps && (
          <>
            {isValidating && (
              <span
                className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-800/60 border border-slate-700 text-slate-400 text-[11px] rounded-md"
                data-testid="validation-chip-validating"
              >
                <Loader2 className="w-3 h-3 animate-spin" />
                Validating...
              </span>
            )}
            {!isValidating && validationErrorCount > 0 && (
              <span
                className="flex items-center gap-1.5 px-2.5 py-1 bg-red-500/10 border border-red-500/30 text-red-400 text-[11px] rounded-md"
                data-testid="validation-chip-error"
                title="Pipeline has validation errors. Click a node to see details."
              >
                <AlertTriangle className="w-3 h-3" />
                {validationErrorCount} {validationErrorCount === 1 ? 'error' : 'errors'}
                {validationWarningCount > 0 && (
                  <span className="text-amber-400/90">
                    {' '}+ {validationWarningCount} warn
                  </span>
                )}
              </span>
            )}
            {!isValidating && validationErrorCount === 0 && validationWarningCount > 0 && (
              <span
                className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[11px] rounded-md"
                data-testid="validation-chip-warning"
              >
                <AlertTriangle className="w-3 h-3" />
                {validationWarningCount} {validationWarningCount === 1 ? 'warning' : 'warnings'}
              </span>
            )}
            {!isValidating && validationErrorCount === 0 && validationWarningCount === 0 && (
              <span
                className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[11px] rounded-md"
                data-testid="validation-chip-valid"
              >
                <CheckCircle2 className="w-3 h-3" />
                Valid
              </span>
            )}
          </>
        )}

        {/* Run Pipeline button */}
        {builderMode === 'pipeline' && agentId && (
          <button
            onClick={onRunPipeline}
            disabled={pipelineRunning}
            className="flex items-center gap-1.5 px-3 py-2 bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 text-xs font-medium rounded-lg hover:bg-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {pipelineRunning ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            {pipelineRunning ? 'Running...' : 'Run Pipeline'}
          </button>
        )}

        {agentId && (
          <button
            onClick={() => router.push(`/agents/${agentId}/chat`)}
            className="flex items-center gap-1.5 px-3 py-2 bg-transparent text-slate-400 text-xs rounded-lg hover:text-white hover:bg-slate-800 transition-colors"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            Test
          </button>
        )}
        <button
          onClick={() => setShowAIValidate(true)}
          data-testid="ai-validate-button"
          title={agentId ? 'Validate the saved agent' : 'Validate the current draft (not yet saved)'}
          className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 text-emerald-300 text-xs rounded-lg hover:border-emerald-400/50 transition-colors"
        >
          <ShieldCheck className="w-3.5 h-3.5" />
          AI Validate
        </button>
        <button
          onClick={() => setShowAIBuilder(true)}
          data-testid="ai-builder-button"
          className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-purple-500/20 to-cyan-500/20 border border-purple-500/30 text-purple-300 text-xs rounded-lg hover:border-purple-400/50 transition-colors"
        >
          <Sparkles className="w-3.5 h-3.5" />
          Build with AI
        </button>
        <button
          onClick={onSave}
          disabled={saving || !dirty}
          className="flex items-center gap-1.5 px-3 py-2 bg-slate-700/50 border border-slate-600 text-slate-200 text-xs rounded-lg hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Save className="w-3.5 h-3.5" />
          Save Draft
        </button>
        <button
          onClick={() => setShowPublish(true)}
          disabled={saving || !agentId}
          className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-xs font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          <Rocket className="w-3.5 h-3.5" />
          Publish
        </button>
      </div>
      {agentId && (
        <PublishDialog
          open={showPublish}
          onClose={() => setShowPublish(false)}
          agentId={agentId}
          onPublished={onPublish}
        />
      )}
      <AIBuilderDialog
        open={showAIBuilder}
        onClose={() => setShowAIBuilder(false)}
        onApply={(config) => {
          if (onAIBuild) onAIBuild(config as unknown as Record<string, unknown>);
        }}
      />
      <BuilderHelpDialog
        open={showHelp}
        onClose={() => setShowHelp(false)}
      />
      <AIValidateDialog
        open={showAIValidate}
        onClose={() => setShowAIValidate(false)}
        agentId={agentId}
        agentName={name}
        getDraft={getDraftForValidate}
      />
    </div>
  );
}
