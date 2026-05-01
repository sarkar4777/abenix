'use client';

import { useCallback, useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle,
  BadgeCheck,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  FileText,
  Globe,
  Key,
  Loader2,
  MessageSquare,
  Plug,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  Trash2,
  TrendingUp,
  User,
  Wrench,
  X,
} from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { SkeletonAgentCard } from '@/components/ui/Skeleton';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Types

interface MCPConnection {
  id: string;
  server_name: string;
  server_url: string;
  transport_type: string;
  auth_type: string;
  discovered_tools: ToolInfo[] | null;
  health_status: string;
  is_enabled: boolean;
  last_health_check: string | null;
  created_at: string | null;
  oauth2_configured: boolean;
  oauth2_connected: boolean;
}

interface ToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  annotations: Record<string, unknown>;
}

interface RegistryEntry {
  id: string;
  registry_id: string;
  name: string;
  description: string;
  server_url: string;
  auth_type: string;
  categories: string[];
  tools_count: number;
  popularity_score: number;
  verified: boolean;
}

interface MCPResource {
  uri: string;
  name: string;
  description: string;
  mime_type: string | null;
}

interface MCPPrompt {
  name: string;
  description: string;
  arguments: { name: string; description?: string; required?: boolean }[];
}

// Helpers

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return token
    ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    : { 'Content-Type': 'application/json' };
}

type TabId = 'servers' | 'registry' | 'resources' | 'prompts';

const TABS: { id: TabId; label: string }[] = [
  { id: 'servers', label: 'My Servers' },
  { id: 'registry', label: 'Registry' },
  { id: 'resources', label: 'Resources' },
  { id: 'prompts', label: 'Prompts' },
];

const REGISTRY_CATEGORIES = [
  'all',
  'development',
  'productivity',
  'database',
  'finance',
  'communication',
  'analytics',
  'security',
  'cloud',
];

// ConnectModal

function ConnectModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (conn: MCPConnection) => void;
}) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [authType, setAuthType] = useState('none');
  const [apiKey, setApiKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');

  // OAuth2 fields
  const [clientId, setClientId] = useState('');
  const [authorizationUrl, setAuthorizationUrl] = useState('');
  const [tokenUrl, setTokenUrl] = useState('');

  // Inline discover
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverCount, setDiscoverCount] = useState<number | null>(null);
  const [discoverError, setDiscoverError] = useState('');

  const reset = () => {
    setName('');
    setUrl('');
    setAuthType('none');
    setApiKey('');
    setClientId('');
    setAuthorizationUrl('');
    setTokenUrl('');
    setErr('');
    setDiscoverLoading(false);
    setDiscoverCount(null);
    setDiscoverError('');
  };

  const handleUrlBlur = async () => {
    if (!url.trim()) return;
    setDiscoverLoading(true);
    setDiscoverCount(null);
    setDiscoverError('');
    try {
      const res = await fetch(`${API_URL}/api/mcp/discover`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ server_url: url.trim() }),
      });
      const json = await res.json();
      if (json.error) {
        setDiscoverError(json.error.message || 'Discovery failed');
      } else if (json.data) {
        setDiscoverCount(json.data.tools_count ?? json.data.tools?.length ?? 0);
      }
    } catch {
      setDiscoverError('Could not reach server');
    } finally {
      setDiscoverLoading(false);
    }
  };

  const submit = async () => {
    if (!name.trim() || !url.trim()) {
      setErr('Name and URL are required');
      return;
    }
    setSubmitting(true);
    setErr('');

    try {
      let authConfig: Record<string, string> | undefined;
      if (authType === 'api_key') {
        authConfig = { api_key: apiKey };
      } else if (authType === 'oauth2') {
        authConfig = {
          client_id: clientId,
          authorization_url: authorizationUrl,
          token_url: tokenUrl,
        };
      }

      const res = await fetch(`${API_URL}/api/mcp/connections`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          server_name: name.trim(),
          server_url: url.trim(),
          auth_type: authType,
          auth_config: authConfig,
        }),
      });
      const json = await res.json();
      if (json.error) {
        setErr(json.error.message);
        return;
      }
      onCreated(json.data);
      reset();
      onClose();
    } catch {
      setErr('Failed to connect');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ResponsiveModal open={open} onClose={() => { reset(); onClose(); }} title="Connect MCP Server" maxWidth="max-w-md">
      <div className="space-y-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Server Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. GitHub MCP"
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Server URL</label>
          <input
            type="text"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              setDiscoverCount(null);
              setDiscoverError('');
            }}
            onBlur={handleUrlBlur}
            placeholder="https://mcp-server.example.com/mcp"
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
          {discoverLoading && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <Loader2 className="w-3 h-3 text-cyan-400 animate-spin" />
              <span className="text-xs text-slate-400">Discovering tools...</span>
            </div>
          )}
          {discoverCount !== null && !discoverLoading && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <CheckCircle2 className="w-3 h-3 text-emerald-400" />
              <span className="text-xs text-emerald-400">
                {discoverCount} tool{discoverCount !== 1 ? 's' : ''} discovered
              </span>
            </div>
          )}
          {discoverError && !discoverLoading && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <AlertTriangle className="w-3 h-3 text-amber-400" />
              <span className="text-xs text-amber-400">{discoverError}</span>
            </div>
          )}
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Authentication</label>
          <select
            value={authType}
            onChange={(e) => setAuthType(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
          >
            <option value="none">None</option>
            <option value="api_key">API Key</option>
            <option value="oauth2">OAuth 2.0</option>
          </select>
        </div>
        {authType === 'api_key' && (
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            />
          </div>
        )}
        {authType === 'oauth2' && (
          <>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Client ID</label>
              <input
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="your-client-id"
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Authorization URL</label>
              <input
                type="text"
                value={authorizationUrl}
                onChange={(e) => setAuthorizationUrl(e.target.value)}
                placeholder="https://provider.com/oauth/authorize"
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Token URL</label>
              <input
                type="text"
                value={tokenUrl}
                onChange={(e) => setTokenUrl(e.target.value)}
                placeholder="https://provider.com/oauth/token"
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>
          </>
        )}
        {err && <p className="text-xs text-red-400">{err}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={() => {
              reset();
              onClose();
            }}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Connect
          </button>
        </div>
      </div>
    </ResponsiveModal>
  );
}

// ToolsDrawer

function getToolBadge(tool: ToolInfo): { label: string; className: string } | null {
  const annotations = tool.annotations || {};
  if (annotations.destructiveHint === true) {
    return { label: 'destructive', className: 'bg-red-500/10 text-red-400' };
  }
  if (annotations.readOnlyHint === true) {
    return { label: 'read-only', className: 'bg-emerald-500/10 text-emerald-400' };
  }
  // Tools that are explicitly not read-only, or tools without readOnlyHint at all get "write"
  if (annotations.readOnlyHint === false || !('readOnlyHint' in annotations)) {
    return { label: 'write', className: 'bg-yellow-500/10 text-yellow-400' };
  }
  return null;
}

function ToolsDrawer({
  connection,
  onClose,
}: {
  connection: MCPConnection;
  onClose: () => void;
}) {
  const tools = connection.discovered_tools || [];
  const isMobile = useIsMobile();

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        transition={{ type: 'spring', damping: 25, stiffness: 200 }}
        className={`bg-[#0F172A] border-l border-slate-700 shadow-2xl overflow-y-auto ${isMobile ? 'w-full' : 'w-full max-w-md'}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-[#0F172A] border-b border-slate-800 p-4 flex items-center justify-between z-10">
          <div>
            <h2 className="text-base font-semibold text-white">{connection.server_name}</h2>
            <p className="text-xs text-slate-500 mt-0.5">{tools.length} tools discovered</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-2">
          {tools.length === 0 && (
            <p className="text-sm text-slate-500 text-center py-8">
              No tools discovered yet. Click &quot;Discover&quot; on the server card.
            </p>
          )}
          {tools.map((tool) => {
            const badge = getToolBadge(tool);
            const annotations = tool.annotations || {};
            const isDestructive = annotations.destructiveHint === true;
            const isReadOnly = annotations.readOnlyHint === true;

            return (
              <div
                key={tool.name}
                className="p-3 bg-slate-800/30 border border-slate-700/50 rounded-lg"
              >
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <Wrench className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                  <span className="text-sm font-medium text-white">{tool.name}</span>
                  {badge && (
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${badge.className}`}
                    >
                      {badge.label}
                    </span>
                  )}
                  {isReadOnly && (
                    <span className="text-[10px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded">
                      read-only
                    </span>
                  )}
                  {isDestructive && (
                    <span className="text-[10px] bg-red-500/10 text-red-400 px-1.5 py-0.5 rounded">
                      destructive
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 ml-5.5">{tool.description}</p>
              </div>
            );
          })}
        </div>
      </motion.div>
    </div>
  );
}

// ConnectionDropdown - reusable dropdown to select a connection

function ConnectionDropdown({
  connections,
  selectedId,
  onSelect,
}: {
  connections: MCPConnection[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selected = connections.find((c) => c.id === selectedId);

  return (
    <div ref={ref} className="relative w-full max-w-sm">
      <button
        onClick={() => setDropdownOpen((prev) => !prev)}
        className="w-full flex items-center justify-between px-3 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-white hover:border-slate-600 transition-colors"
      >
        <span className={selected ? 'text-white' : 'text-slate-500'}>
          {selected ? selected.server_name : 'Select a connection...'}
        </span>
        <ChevronDown className="w-4 h-4 text-slate-500" />
      </button>
      {dropdownOpen && (
        <div className="absolute z-20 mt-1 w-full bg-[#0F172A] border border-slate-700 rounded-lg shadow-xl max-h-60 overflow-y-auto">
          {connections.length === 0 && (
            <p className="text-xs text-slate-500 p-3">No connections available</p>
          )}
          {connections.map((conn) => (
            <button
              key={conn.id}
              onClick={() => {
                onSelect(conn.id);
                setDropdownOpen(false);
              }}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-slate-800/60 transition-colors ${
                conn.id === selectedId ? 'text-cyan-400 bg-slate-800/40' : 'text-white'
              }`}
            >
              <span className="block">{conn.server_name}</span>
              <span className="block text-[11px] text-slate-600 truncate">{conn.server_url}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ResourceContentModal

function ResourceContentModal({
  open,
  onClose,
  resource,
  content,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  resource: MCPResource | null;
  content: string;
  loading: boolean;
}) {
  if (!open || !resource) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="w-full max-w-2xl bg-[#0F172A] border border-slate-700 rounded-xl shadow-2xl max-h-[80vh] flex flex-col"
      >
        <div className="flex items-center justify-between p-4 border-b border-slate-800 shrink-0">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-white truncate">{resource.name}</h2>
            <p className="text-xs text-slate-500 truncate mt-0.5">{resource.uri}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white shrink-0 ml-3">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-4 overflow-y-auto flex-1">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 text-cyan-500 animate-spin" />
            </div>
          ) : (
            <pre className="text-sm text-slate-300 whitespace-pre-wrap break-words font-mono bg-slate-900/50 rounded-lg p-4 border border-slate-800">
              {content || 'No content available'}
            </pre>
          )}
        </div>
        <div className="flex justify-end p-4 border-t border-slate-800 shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            Close
          </button>
        </div>
      </motion.div>
    </div>
  );
}

// PromptTryModal

function PromptTryModal({
  open,
  onClose,
  prompt,
  connectionId,
}: {
  open: boolean;
  onClose: () => void;
  prompt: MCPPrompt | null;
  connectionId: string;
}) {
  const [argValues, setArgValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (prompt) {
      const defaults: Record<string, string> = {};
      prompt.arguments.forEach((a) => {
        defaults[a.name] = '';
      });
      setArgValues(defaults);
      setMessages([]);
      setErr('');
    }
  }, [prompt]);

  const handleSubmit = async () => {
    if (!prompt) return;
    setSubmitting(true);
    setErr('');
    setMessages([]);
    try {
      const res = await fetch(
        `${API_URL}/api/mcp/connections/${connectionId}/prompts/get`,
        {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({
            name: prompt.name,
            arguments: argValues,
          }),
        },
      );
      const json = await res.json();
      if (json.error) {
        setErr(json.error.message || 'Failed to get prompt');
      } else if (json.data?.messages) {
        setMessages(json.data.messages);
      }
    } catch {
      setErr('Failed to call prompt');
    } finally {
      setSubmitting(false);
    }
  };

  if (!open || !prompt) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="w-full max-w-lg bg-[#0F172A] border border-slate-700 rounded-xl shadow-2xl max-h-[85vh] flex flex-col"
      >
        <div className="flex items-center justify-between p-4 border-b border-slate-800 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-white">{prompt.name}</h2>
            <p className="text-xs text-slate-500 mt-0.5">{prompt.description}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white shrink-0 ml-3">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-3 overflow-y-auto flex-1">
          {prompt.arguments.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">
                Arguments
              </p>
              {prompt.arguments.map((arg) => (
                <div key={arg.name}>
                  <label className="block text-xs text-slate-400 mb-1.5">
                    {arg.name}
                    {arg.required && <span className="text-red-400 ml-0.5">*</span>}
                    {arg.description && (
                      <span className="text-slate-600 ml-1.5">- {arg.description}</span>
                    )}
                  </label>
                  <input
                    type="text"
                    value={argValues[arg.name] || ''}
                    onChange={(e) =>
                      setArgValues((prev) => ({ ...prev, [arg.name]: e.target.value }))
                    }
                    placeholder={arg.description || arg.name}
                    className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                  />
                </div>
              ))}
            </div>
          )}

          {prompt.arguments.length === 0 && (
            <p className="text-xs text-slate-500">This prompt has no arguments.</p>
          )}

          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 w-full justify-center"
          >
            {submitting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
            Generate Messages
          </button>

          {err && <p className="text-xs text-red-400">{err}</p>}

          {messages.length > 0 && (
            <div className="space-y-2 pt-2">
              <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">
                Generated Messages
              </p>
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={`p-3 rounded-lg text-sm ${
                    msg.role === 'user'
                      ? 'bg-cyan-500/10 border border-cyan-500/20 text-cyan-100'
                      : msg.role === 'assistant'
                        ? 'bg-slate-800/50 border border-slate-700/50 text-slate-300'
                        : 'bg-slate-800/30 border border-slate-700/30 text-slate-400'
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-1.5">
                    {msg.role === 'user' ? (
                      <User className="w-3 h-3" />
                    ) : (
                      <MessageSquare className="w-3 h-3" />
                    )}
                    <span className="text-[10px] uppercase tracking-wider font-medium opacity-70">
                      {msg.role}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex justify-end p-4 border-t border-slate-800 shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            Close
          </button>
        </div>
      </motion.div>
    </div>
  );
}

// MyServersTab

function MyServersTab({
  connections,
  setConnections,
  onOpenModal,
}: {
  connections: MCPConnection[];
  setConnections: React.Dispatch<React.SetStateAction<MCPConnection[]>>;
  onOpenModal: () => void;
}) {
  const [discovering, setDiscovering] = useState<string | null>(null);
  const [healthChecking, setHealthChecking] = useState<string | null>(null);
  const [drawerConn, setDrawerConn] = useState<MCPConnection | null>(null);
  const [search, setSearch] = useState('');
  const [oauthStarting, setOauthStarting] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const discoverTools = async (connId: string) => {
    setDiscovering(connId);
    try {
      const res = await fetch(`${API_URL}/api/mcp/connections/${connId}/discover`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      const json = await res.json();
      if (json.data) {
        setConnections((prev) =>
          prev.map((c) =>
            c.id === connId
              ? {
                  ...c,
                  discovered_tools: json.data.tools,
                  health_status: 'healthy',
                  last_health_check: new Date().toISOString(),
                }
              : c,
          ),
        );
      }
    } catch {
      setConnections((prev) =>
        prev.map((c) => (c.id === connId ? { ...c, health_status: 'error' } : c)),
      );
    } finally {
      setDiscovering(null);
    }
  };

  const healthCheck = async (connId: string) => {
    setHealthChecking(connId);
    try {
      const res = await fetch(`${API_URL}/api/mcp/connections/${connId}/health`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      const json = await res.json();
      if (json.data) {
        setConnections((prev) =>
          prev.map((c) =>
            c.id === connId
              ? {
                  ...c,
                  health_status: json.data.status || 'healthy',
                  last_health_check: new Date().toISOString(),
                }
              : c,
          ),
        );
      }
    } catch {
      setConnections((prev) =>
        prev.map((c) => (c.id === connId ? { ...c, health_status: 'error' } : c)),
      );
    } finally {
      setHealthChecking(null);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!confirmDeleteId) return;
    setDeleting(true);
    try {
      await fetch(`${API_URL}/api/mcp/connections/${confirmDeleteId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
      setConnections((prev) => prev.filter((c) => c.id !== confirmDeleteId));
      toastSuccess('Server disconnected');
    } catch {
      toastError('Failed to disconnect server');
    } finally {
      setDeleting(false);
      setConfirmDeleteId(null);
    }
  };

  const startOAuth = async (connId: string) => {
    setOauthStarting(connId);
    try {
      const res = await fetch(`${API_URL}/api/mcp/oauth2/start`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ connection_id: connId }),
      });
      const json = await res.json();
      if (json.data?.authorization_url) {
        window.location.href = json.data.authorization_url;
      }
    } catch {
      // silent
    } finally {
      setOauthStarting(null);
    }
  };

  const filtered = search
    ? connections.filter(
        (c) =>
          c.server_name.toLowerCase().includes(search.toLowerCase()) ||
          c.server_url.toLowerCase().includes(search.toLowerCase()),
      )
    : connections;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        {connections.length > 3 && (
          <div className="relative max-w-sm flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search servers..."
              className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
            />
          </div>
        )}
        <button
          onClick={onOpenModal}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity shrink-0"
        >
          <Plus className="w-4 h-4" />
          Add Server
        </button>
      </div>

      {filtered.length === 0 && !search && (
        <div className="text-center py-16">
          <div className="w-14 h-14 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center mx-auto mb-4">
            <Plug className="w-7 h-7 text-slate-600" />
          </div>
          <p className="text-sm text-slate-400 mb-1">No MCP servers connected</p>
          <p className="text-xs text-slate-600">
            Click &quot;Add Server&quot; to connect your first MCP server
          </p>
        </div>
      )}

      {filtered.length === 0 && search && (
        <p className="text-sm text-slate-500 text-center py-8">
          No servers match &quot;{search}&quot;
        </p>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((conn) => {
          const toolCount = conn.discovered_tools?.length ?? 0;
          const isDiscovering = discovering === conn.id;
          const isChecking = healthChecking === conn.id;
          const isHealthy = conn.health_status === 'healthy';
          const isError = conn.health_status === 'error';
          const showOAuth =
            conn.auth_type === 'oauth2' && conn.oauth2_configured && !conn.oauth2_connected;

          return (
            <motion.div
              key={conn.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-colors group"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
                  <Plug className="w-5 h-5 text-cyan-400" />
                </div>
                <div className="flex items-center gap-2">
                  {isHealthy && (
                    <span className="flex items-center gap-1 text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full">
                      <CheckCircle2 className="w-3 h-3" /> Healthy
                    </span>
                  )}
                  {isError && (
                    <span className="flex items-center gap-1 text-xs text-red-400 bg-red-500/10 px-2 py-0.5 rounded-full">
                      <AlertTriangle className="w-3 h-3" /> Error
                    </span>
                  )}
                  {!isHealthy && !isError && (
                    <span className="text-xs text-slate-500 bg-slate-700/50 px-2 py-0.5 rounded-full">
                      Unknown
                    </span>
                  )}
                </div>
              </div>

              <h3 className="text-sm font-semibold text-white mb-0.5">{conn.server_name}</h3>
              <p className="text-[11px] text-slate-600 truncate mb-1">{conn.server_url}</p>

              <div className="flex items-center gap-1.5 mb-3">
                {conn.auth_type !== 'none' && (
                  <span className="text-[10px] bg-slate-700/60 text-slate-400 px-1.5 py-0.5 rounded">
                    {conn.auth_type === 'api_key' ? 'API Key' : 'OAuth2'}
                  </span>
                )}
                {conn.auth_type === 'oauth2' && conn.oauth2_connected && (
                  <span className="text-[10px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded">
                    Connected
                  </span>
                )}
              </div>

              {showOAuth && (
                <button
                  onClick={() => startOAuth(conn.id)}
                  disabled={oauthStarting === conn.id}
                  className="w-full flex items-center justify-center gap-1.5 mb-3 px-3 py-1.5 text-xs bg-blue-600/20 border border-blue-500/30 text-blue-400 rounded-lg hover:bg-blue-600/30 transition-colors disabled:opacity-50"
                >
                  {oauthStarting === conn.id ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Key className="w-3 h-3" />
                  )}
                  Connect with OAuth
                </button>
              )}

              <div className="flex items-center justify-between pt-3 border-t border-slate-700/30">
                <span className="text-xs text-slate-500">
                  {toolCount > 0 ? `${toolCount} tools` : 'No tools yet'}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => discoverTools(conn.id)}
                    disabled={isDiscovering}
                    className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 px-2 py-1 rounded hover:bg-cyan-500/10 transition-colors disabled:opacity-50"
                    title="Discover tools"
                  >
                    {isDiscovering ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Search className="w-3 h-3" />
                    )}
                    Discover
                  </button>
                  <button
                    onClick={() => healthCheck(conn.id)}
                    disabled={isChecking}
                    className="text-xs text-slate-400 hover:text-white flex items-center gap-1 px-2 py-1 rounded hover:bg-slate-700/50 transition-colors disabled:opacity-50"
                    title="Health check"
                  >
                    {isChecking ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3 h-3" />
                    )}
                  </button>
                  {toolCount > 0 && (
                    <button
                      onClick={() => setDrawerConn(conn)}
                      className="text-xs text-slate-400 hover:text-white flex items-center gap-1 px-2 py-1 rounded hover:bg-slate-700/50 transition-colors"
                      title="View tools"
                    >
                      <ExternalLink className="w-3 h-3" />
                    </button>
                  )}
                  <button
                    onClick={() => setConfirmDeleteId(conn.id)}
                    className="text-xs text-slate-500 hover:text-red-400 px-2 py-1 rounded hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
                    title="Delete"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>

      <ConfirmModal
        open={confirmDeleteId !== null}
        onClose={() => setConfirmDeleteId(null)}
        onConfirm={handleDeleteConfirm}
        title="Disconnect Server"
        description="Are you sure you want to disconnect this MCP server? Any agents using its tools will lose access."
        confirmLabel="Disconnect"
        loading={deleting}
      />

      <AnimatePresence>
        {drawerConn && <ToolsDrawer connection={drawerConn} onClose={() => setDrawerConn(null)} />}
      </AnimatePresence>
    </div>
  );
}

// RegistryTab

function RegistryTab({
  onInstalled,
}: {
  onInstalled: (conn: MCPConnection) => void;
}) {
  const [entries, setEntries] = useState<RegistryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [installing, setInstalling] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const fetchRegistry = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (category !== 'all') params.set('category', category);
      const res = await fetch(`${API_URL}/api/mcp/registry?${params.toString()}`, {
        headers: getAuthHeaders(),
      });
      const json = await res.json();
      if (json.data) setEntries(json.data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [search, category]);

  useEffect(() => {
    fetchRegistry();
  }, [fetchRegistry]);

  const syncRegistry = async () => {
    setSyncing(true);
    try {
      await fetch(`${API_URL}/api/mcp/registry/sync`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      await fetchRegistry();
    } catch {
      // silent
    } finally {
      setSyncing(false);
    }
  };

  const installEntry = async (entry: RegistryEntry) => {
    setInstalling(entry.id);
    try {
      const res = await fetch(`${API_URL}/api/mcp/registry/install`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ registry_entry_id: entry.id }),
      });
      const json = await res.json();
      if (json.data) {
        onInstalled(json.data);
      }
    } catch {
      // silent
    } finally {
      setInstalling(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search registry..."
            className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
        <button
          onClick={syncRegistry}
          disabled={syncing}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 shrink-0"
        >
          {syncing ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
          Sync Registry
        </button>
      </div>

      {/* Category pills */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {REGISTRY_CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
              category === cat
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'bg-slate-800/50 text-slate-400 border border-slate-700/50 hover:border-slate-600/50 hover:text-slate-300'
            }`}
          >
            {cat === 'all' ? 'All' : cat.charAt(0).toUpperCase() + cat.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 text-cyan-500 animate-spin" />
        </div>
      ) : entries.length === 0 ? (
        <div className="text-center py-16">
          <div className="w-14 h-14 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center mx-auto mb-4">
            <Globe className="w-7 h-7 text-slate-600" />
          </div>
          <p className="text-sm text-slate-400 mb-1">No registry entries found</p>
          <p className="text-xs text-slate-600">
            Try a different search or sync the registry
          </p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {entries.map((entry) => (
            <motion.div
              key={entry.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-colors group"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
                  <Server className="w-5 h-5 text-blue-400" />
                </div>
                <div className="flex items-center gap-1.5">
                  {entry.verified && (
                    <span className="flex items-center gap-1 text-xs text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded-full">
                      <BadgeCheck className="w-3 h-3" /> Verified
                    </span>
                  )}
                </div>
              </div>

              <h3 className="text-sm font-semibold text-white mb-1">{entry.name}</h3>
              <p className="text-xs text-slate-500 mb-3 line-clamp-2">{entry.description}</p>

              <div className="flex items-center gap-2 flex-wrap mb-3">
                <span className="text-[10px] bg-slate-700/60 text-slate-400 px-1.5 py-0.5 rounded">
                  {entry.auth_type === 'none'
                    ? 'No Auth'
                    : entry.auth_type === 'api_key'
                      ? 'API Key'
                      : 'OAuth2'}
                </span>
                <span className="text-[10px] bg-slate-700/60 text-slate-400 px-1.5 py-0.5 rounded flex items-center gap-0.5">
                  <Wrench className="w-2.5 h-2.5" /> {entry.tools_count} tools
                </span>
                <span className="text-[10px] bg-slate-700/60 text-slate-400 px-1.5 py-0.5 rounded flex items-center gap-0.5">
                  <TrendingUp className="w-2.5 h-2.5" /> {entry.popularity_score}
                </span>
              </div>

              {entry.categories.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap mb-3">
                  {entry.categories.slice(0, 3).map((cat) => (
                    <span
                      key={cat}
                      className="text-[10px] bg-cyan-500/10 text-cyan-400/80 px-1.5 py-0.5 rounded"
                    >
                      {cat}
                    </span>
                  ))}
                  {entry.categories.length > 3 && (
                    <span className="text-[10px] text-slate-600">
                      +{entry.categories.length - 3}
                    </span>
                  )}
                </div>
              )}

              <button
                onClick={() => installEntry(entry)}
                disabled={installing === entry.id}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium bg-gradient-to-r from-cyan-500 to-blue-600 text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                {installing === entry.id ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Plus className="w-3 h-3" />
                )}
                Install
              </button>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}

// ResourcesTab

function ResourcesTab({ connections }: { connections: MCPConnection[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resources, setResources] = useState<MCPResource[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeResource, setActiveResource] = useState<MCPResource | null>(null);
  const [resourceContent, setResourceContent] = useState('');
  const [contentLoading, setContentLoading] = useState(false);
  const [contentModalOpen, setContentModalOpen] = useState(false);

  const fetchResources = useCallback(async (connId: string) => {
    setLoading(true);
    setResources([]);
    try {
      const res = await fetch(`${API_URL}/api/mcp/connections/${connId}/resources`, {
        headers: getAuthHeaders(),
      });
      const json = await res.json();
      if (json.data) setResources(json.data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) {
      fetchResources(selectedId);
    } else {
      setResources([]);
    }
  }, [selectedId, fetchResources]);

  const readResource = async (resource: MCPResource) => {
    if (!selectedId) return;
    setActiveResource(resource);
    setContentModalOpen(true);
    setContentLoading(true);
    setResourceContent('');
    try {
      const res = await fetch(
        `${API_URL}/api/mcp/connections/${selectedId}/resources/read`,
        {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ uri: resource.uri }),
        },
      );
      const json = await res.json();
      if (json.data?.content) {
        setResourceContent(
          typeof json.data.content === 'string'
            ? json.data.content
            : JSON.stringify(json.data.content, null, 2),
        );
      } else if (json.data?.text) {
        setResourceContent(json.data.text);
      } else {
        setResourceContent(JSON.stringify(json.data, null, 2));
      }
    } catch {
      setResourceContent('Failed to read resource');
    } finally {
      setContentLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <ConnectionDropdown
        connections={connections}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      {!selectedId && (
        <div className="text-center py-16">
          <div className="w-14 h-14 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center mx-auto mb-4">
            <FileText className="w-7 h-7 text-slate-600" />
          </div>
          <p className="text-sm text-slate-400 mb-1">Select a connection</p>
          <p className="text-xs text-slate-600">Choose an MCP server to browse its resources</p>
        </div>
      )}

      {selectedId && loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 text-cyan-500 animate-spin" />
        </div>
      )}

      {selectedId && !loading && resources.length === 0 && (
        <div className="text-center py-16">
          <div className="w-14 h-14 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center mx-auto mb-4">
            <FileText className="w-7 h-7 text-slate-600" />
          </div>
          <p className="text-sm text-slate-400 mb-1">No resources available</p>
          <p className="text-xs text-slate-600">This server does not expose any resources</p>
        </div>
      )}

      {selectedId && !loading && resources.length > 0 && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {resources.map((resource) => (
            <motion.div
              key={resource.uri}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/50 transition-colors cursor-pointer group"
              onClick={() => readResource(resource)}
            >
              <div className="flex items-start gap-3 mb-2">
                <div className="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center shrink-0">
                  <FileText className="w-4 h-4 text-purple-400" />
                </div>
                <div className="min-w-0">
                  <h4 className="text-sm font-medium text-white truncate">{resource.name}</h4>
                  <p className="text-[11px] text-slate-600 truncate">{resource.uri}</p>
                </div>
              </div>
              {resource.description && (
                <p className="text-xs text-slate-500 mb-2 line-clamp-2">{resource.description}</p>
              )}
              {resource.mime_type && (
                <span className="text-[10px] bg-slate-700/60 text-slate-400 px-1.5 py-0.5 rounded">
                  {resource.mime_type}
                </span>
              )}
              <div className="mt-2 flex justify-end">
                <span className="text-xs text-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity">
                  Click to read
                </span>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      <ResourceContentModal
        open={contentModalOpen}
        onClose={() => {
          setContentModalOpen(false);
          setActiveResource(null);
          setResourceContent('');
        }}
        resource={activeResource}
        content={resourceContent}
        loading={contentLoading}
      />
    </div>
  );
}

// PromptsTab

function PromptsTab({ connections }: { connections: MCPConnection[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [prompts, setPrompts] = useState<MCPPrompt[]>([]);
  const [loading, setLoading] = useState(false);
  const [tryPrompt, setTryPrompt] = useState<MCPPrompt | null>(null);

  const fetchPrompts = useCallback(async (connId: string) => {
    setLoading(true);
    setPrompts([]);
    try {
      const res = await fetch(`${API_URL}/api/mcp/connections/${connId}/prompts`, {
        headers: getAuthHeaders(),
      });
      const json = await res.json();
      if (json.data) setPrompts(json.data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) {
      fetchPrompts(selectedId);
    } else {
      setPrompts([]);
    }
  }, [selectedId, fetchPrompts]);

  return (
    <div className="space-y-4">
      <ConnectionDropdown
        connections={connections}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      {!selectedId && (
        <div className="text-center py-16">
          <div className="w-14 h-14 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center mx-auto mb-4">
            <BookOpen className="w-7 h-7 text-slate-600" />
          </div>
          <p className="text-sm text-slate-400 mb-1">Select a connection</p>
          <p className="text-xs text-slate-600">Choose an MCP server to browse its prompts</p>
        </div>
      )}

      {selectedId && loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 text-cyan-500 animate-spin" />
        </div>
      )}

      {selectedId && !loading && prompts.length === 0 && (
        <div className="text-center py-16">
          <div className="w-14 h-14 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center mx-auto mb-4">
            <BookOpen className="w-7 h-7 text-slate-600" />
          </div>
          <p className="text-sm text-slate-400 mb-1">No prompts available</p>
          <p className="text-xs text-slate-600">This server does not expose any prompts</p>
        </div>
      )}

      {selectedId && !loading && prompts.length > 0 && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {prompts.map((prompt) => (
            <motion.div
              key={prompt.name}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/50 transition-colors"
            >
              <div className="flex items-start gap-3 mb-2">
                <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0">
                  <MessageSquare className="w-4 h-4 text-amber-400" />
                </div>
                <div className="min-w-0">
                  <h4 className="text-sm font-medium text-white">{prompt.name}</h4>
                </div>
              </div>
              {prompt.description && (
                <p className="text-xs text-slate-500 mb-3 line-clamp-2">{prompt.description}</p>
              )}

              {prompt.arguments.length > 0 && (
                <div className="mb-3 space-y-1">
                  <p className="text-[10px] text-slate-600 uppercase tracking-wider">Arguments</p>
                  {prompt.arguments.map((arg) => (
                    <div key={arg.name} className="flex items-center gap-1.5">
                      <span className="text-xs text-slate-400 font-mono">{arg.name}</span>
                      {arg.required && (
                        <span className="text-[9px] bg-red-500/10 text-red-400 px-1 py-0.5 rounded">
                          required
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <button
                onClick={() => setTryPrompt(prompt)}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium bg-gradient-to-r from-cyan-500 to-blue-600 text-white rounded-lg hover:opacity-90 transition-opacity"
              >
                <Send className="w-3 h-3" />
                Try it
              </button>
            </motion.div>
          ))}
        </div>
      )}

      {selectedId && (
        <PromptTryModal
          open={tryPrompt !== null}
          onClose={() => setTryPrompt(null)}
          prompt={tryPrompt}
          connectionId={selectedId}
        />
      )}
    </div>
  );
}

// MCPPage (main)

export default function MCPPage() {
  usePageTitle('MCP Servers');
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>('servers');

  const { data: connectionsData, isLoading: loading } =
    useApi<MCPConnection[]>('/api/mcp/connections');

  useEffect(() => {
    if (connectionsData) setConnections(connectionsData);
  }, [connectionsData]);

  const handleCreated = (conn: MCPConnection) => {
    setConnections((prev) => [conn, ...prev]);
  };

  const handleInstalled = (conn: MCPConnection) => {
    setConnections((prev) => [conn, ...prev]);
    setActiveTab('servers');
  };

  if (loading) {
    return (
      <div className="space-y-6 max-w-[1400px]">
        <div>
          <div className="h-7 w-32 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-64 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonAgentCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1400px]"
    >
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">MCP Servers</h1>
        <p className="text-sm text-slate-500 mt-1">
          Connect Model Context Protocol tool servers to your agents
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 border-b border-slate-800 overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`relative px-4 py-2.5 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-cyan-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab.label}
            {activeTab === tab.id && (
              <motion.div
                layoutId="mcp-tab-underline"
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-cyan-500 to-blue-600"
                transition={{ type: 'spring', stiffness: 300, damping: 30 }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <AnimatePresence mode="wait">
        {activeTab === 'servers' && (
          <motion.div
            key="servers"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
          >
            <MyServersTab
              connections={connections}
              setConnections={setConnections}
              onOpenModal={() => setModalOpen(true)}
            />
          </motion.div>
        )}
        {activeTab === 'registry' && (
          <motion.div
            key="registry"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
          >
            <RegistryTab onInstalled={handleInstalled} />
          </motion.div>
        )}
        {activeTab === 'resources' && (
          <motion.div
            key="resources"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
          >
            <ResourcesTab connections={connections} />
          </motion.div>
        )}
        {activeTab === 'prompts' && (
          <motion.div
            key="prompts"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
          >
            <PromptsTab connections={connections} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Connect Modal (shared across tabs) */}
      <ConnectModal open={modalOpen} onClose={() => setModalOpen(false)} onCreated={handleCreated} />
    </motion.div>
  );
}
