export const API_BASE_URL = '/api/v1';

export const DEFAULT_PAGE_SIZE = 20;

export const ROLES = {
  ADMIN: 'admin',
  USER: 'user',
  VIEWER: 'viewer',
} as const;

export const KB_TYPES = {
  PUBLIC: 'public',
  PRIVATE: 'private',
  TEAM: 'team',
} as const;

export const DOCUMENT_STATUS = {
  PENDING: 'pending',
  PROCESSING: 'processing',
  INDEXED: 'indexed',
  FAILED: 'failed',
} as const;

export const MESSAGE_ROLES = {
  USER: 'user',
  ASSISTANT: 'assistant',
  SYSTEM: 'system',
} as const;

export const CHUNK_STRATEGIES = {
  TOKEN: 'token',
  SEMANTIC: 'semantic',
  RECURSIVE: 'recursive',
} as const;

export const EMBEDDING_PROVIDERS = {
  OPENAI: 'openai',
  AZURE: 'azure',
  LOCAL: 'local',
} as const;

export const LLM_PROVIDERS = {
  OPENAI: 'openai',
  ANTHROPIC: 'anthropic',
  AZURE: 'azure',
  LOCAL: 'local',
} as const;
