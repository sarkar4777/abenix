import { z } from 'zod';

export const agentSchema = z.object({
  name: z.string().min(1, 'Name is required').max(100, 'Name too long'),
  description: z.string().max(1000, 'Description too long').optional(),
  system_prompt: z.string().max(10000, 'System prompt too long').optional(),
  model: z.string().min(1, 'Model is required'),
  temperature: z.number().min(0).max(2).optional(),
  max_tokens: z.number().min(1).max(200000).optional(),
});

export const pipelineNodeSchema = z.object({
  id: z.string().min(1),
  tool_id: z.string().min(1, 'Tool is required'),
  label: z.string().min(1, 'Label is required').max(50),
  config: z.record(z.string(), z.unknown()).optional(),
});

export const knowledgeBaseSchema = z.object({
  name: z.string().min(1, 'Name is required').max(100),
  description: z.string().max(500).optional(),
});

export const loginSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

export const registerSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
  full_name: z.string().min(1, 'Name is required').max(100),
  organization: z.string().min(1, 'Organization is required').max(100),
});

export const apiKeySchema = z.object({
  name: z.string().min(1, 'Name is required').max(50),
  scopes: z.array(z.enum(['read', 'write', 'execute', 'admin'])).min(1, 'Select at least one scope'),
  expires_at: z.string().optional(),
});

export const shareSchema = z.object({
  email: z.string().email('Invalid email address'),
  permission: z.enum(['view', 'edit', 'execute']),
});
