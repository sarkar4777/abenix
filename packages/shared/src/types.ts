export interface ApiResponse<T = unknown> {
  data: T | null;
  error: ApiError | null;
  meta: Record<string, unknown>;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  model: string;
  systemPrompt: string;
  tools: string[];
  tenantId: string;
  isPublished: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface AgentSession {
  id: string;
  agentId: string;
  userId: string;
  status: 'active' | 'completed' | 'failed';
  createdAt: string;
}

export interface ChatMessage {
  id: string;
  sessionId: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  metadata?: Record<string, unknown>;
  createdAt: string;
}

export interface McpServerConfig {
  id: string;
  name: string;
  url: string;
  authType: 'none' | 'api_key' | 'oauth';
  tools: McpTool[];
}

export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}
