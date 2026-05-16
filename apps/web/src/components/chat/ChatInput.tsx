'use client';

import { useRef, useState, useCallback, type KeyboardEvent, type ChangeEvent } from 'react';
import { ArrowUp, FileText, Paperclip, Square, X } from 'lucide-react';

interface AttachedFile {
  name: string;
  content: string;
  size: number;
}

interface ChatInputProps {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  model: string;
  tokenCount: { input: number; output: number };
  cost: number;
  confidenceScore?: number | null;
}

export default function ChatInput({
  onSend,
  onStop,
  isStreaming,
  model,
  tokenCount,
  cost,
  confidenceScore,
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileAttach = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    Array.from(files).forEach((file) => {
      const reader = new FileReader();
      reader.onload = () => {
        const content = reader.result as string;
        setAttachedFiles((prev) => [
          ...prev,
          { name: file.name, content, size: file.size },
        ]);
      };
      reader.readAsText(file);
    });
    e.target.value = '';
  }, []);

  const removeFile = useCallback((name: string) => {
    setAttachedFiles((prev) => prev.filter((f) => f.name !== name));
  }, []);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if ((!trimmed && attachedFiles.length === 0) || isStreaming) return;

    let message = trimmed;
    if (attachedFiles.length > 0) {
      const fileBlocks = attachedFiles
        .map((f) => `--- File: ${f.name} ---\n${f.content}\n--- End of ${f.name} ---`)
        .join('\n\n');
      message = message
        ? `${message}\n\n${fileBlocks}`
        : `Please analyze the following file(s):\n\n${fileBlocks}`;
    }

    onSend(message);
    setValue('');
    setAttachedFiles([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, attachedFiles, isStreaming, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const maxHeight = 4 * 24;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, []);

  const totalTokens = tokenCount.input + tokenCount.output;

  return (
    <div className="bg-[#111827] border-t border-slate-800 p-4">
      {attachedFiles.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {attachedFiles.map((file) => (
            <div
              key={file.name}
              className="flex items-center gap-2 bg-slate-800/50 border border-slate-700/50 rounded-lg px-2.5 py-1.5"
            >
              <FileText className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-xs text-slate-300 max-w-[150px] truncate">
                {file.name}
              </span>
              <span className="text-[10px] text-slate-500">
                {(file.size / 1024).toFixed(1)}KB
              </span>
              <button
                onClick={() => removeFile(file.name)}
                className="w-4 h-4 flex items-center justify-center rounded text-slate-500 hover:text-red-400 transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-end gap-3">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".txt,.md,.csv,.json,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.yaml,.yml,.log,.sql,.sh,.env,.toml,.cfg,.ini,.pdf,.docx"
          onChange={handleFileAttach}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors shrink-0 mb-0.5 ${
            attachedFiles.length > 0
              ? 'text-cyan-400 bg-cyan-500/10'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
          }`}
          title="Attach file"
        >
          <Paperclip className="w-5 h-5" />
        </button>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            handleInput();
          }}
          onKeyDown={handleKeyDown}
          placeholder="Message agent..."
          rows={1}
          className="flex-1 bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500 transition-colors"
        />

        {isStreaming ? (
          <button
            onClick={onStop}
            className="w-10 h-10 flex items-center justify-center rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors shrink-0 mb-0.5"
            title="Stop generating"
          >
            <Square className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!value.trim() && attachedFiles.length === 0}
            className="w-10 h-10 flex items-center justify-center rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white shadow-lg shadow-cyan-500/25 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity shrink-0 mb-0.5"
            title="Send message"
          >
            <ArrowUp className="w-5 h-5" />
          </button>
        )}
      </div>

      <div className="hidden sm:flex items-center gap-3 mt-2 px-1">
        <span className="text-xs font-mono text-slate-600 bg-slate-800/50 px-2 py-0.5 rounded">
          {model}
        </span>
        {totalTokens > 0 && (
          <>
            <span className="text-xs text-slate-600">
              {totalTokens.toLocaleString()} tokens
            </span>
            <span className="text-xs text-slate-600">
              ${cost.toFixed(4)}
            </span>
            {confidenceScore != null && (
              <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                confidenceScore >= 0.7 ? 'text-emerald-400 bg-emerald-500/10' :
                confidenceScore >= 0.5 ? 'text-amber-400 bg-amber-500/10' :
                'text-red-400 bg-red-500/10'
              }`}>
                {Math.round(confidenceScore * 100)}% confidence
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}
