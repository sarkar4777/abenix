'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import { Info, Workflow } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import '@gorules/jdm-editor/dist/style.css';

const Editor = dynamic(
  async () => {
    const m = await import('@gorules/jdm-editor');
    function Wrapped({ value, onChange, disabled }: { value: any; onChange: (v: any) => void; disabled: boolean }) {
      return (
        <m.JdmConfigProvider theme={{ mode: 'dark' }}>
          <m.DecisionGraph value={value} onChange={onChange} disabled={disabled} />
        </m.JdmConfigProvider>
      );
    }
    return Wrapped;
  },
  { ssr: false, loading: () => <div className="h-[560px] rounded-xl bg-slate-800/40 animate-pulse" /> },
);

export default function FlowView({
  content,
  hasBuilder,
  editable,
  onChangeContent,
}: {
  content: any;
  hasBuilder: boolean;
  editable: boolean;
  onChangeContent: (jdm: any) => void;
}) {
  const [unlocked, setUnlocked] = useState(!hasBuilder);
  const [ask, setAsk] = useState(false);
  const canEdit = editable && unlocked;

  return (
    <div data-testid="flow-view">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="flex items-start gap-2 text-sm text-slate-400 max-w-3xl">
          <Info className="w-4 h-4 mt-0.5 shrink-0 text-cyan-400" />
          {hasBuilder
            ? 'This is the decision your rules compile to. Use the flow view for multi-step decisions: switches, expressions, functions and chained tables.'
            : 'This version is authored as a flow. Drag nodes from the left, connect them, and open a node to edit it.'}
        </p>
        {editable && hasBuilder && !unlocked && (
          <button type="button" onClick={() => setAsk(true)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border border-slate-700 text-slate-200 hover:bg-slate-800" data-testid="flow-unlock">
            <Workflow className="w-4 h-4" /> Edit as a flow
          </button>
        )}
      </div>
      <div className="h-[620px] rounded-xl border border-slate-800 overflow-hidden bg-slate-950">
        <Editor value={content} onChange={(v: any) => canEdit && onChangeContent(v)} disabled={!canEdit} />
      </div>
      <ConfirmModal
        open={ask}
        onClose={() => setAsk(false)}
        onConfirm={() => { setUnlocked(true); setAsk(false); }}
        variant="warning"
        icon={Workflow}
        title="Edit this draft as a flow?"
        description="Once you change the flow, this draft is kept as a flow and the rule builder and table views no longer apply to it. Earlier versions keep their rules. You can always start a new draft from a version authored in the builder."
        confirmLabel="Edit as a flow"
      />
    </div>
  );
}
