import client from './client';

export interface LLMProfile {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  model: string;
  has_key: boolean;
  is_active: boolean;
}

export interface LLMProfileInput {
  name?: string;
  base_url: string;
  model: string;
  api_key?: string;
}

export interface LLMTestResult {
  success: boolean;
  response?: string;
  error?: string;
}

export async function listLLMProfiles(): Promise<LLMProfile[]> {
  const res = await client.get<LLMProfile[]>('/llm-profiles');
  return res.data;
}

export async function createLLMProfile(input: LLMProfileInput): Promise<LLMProfile> {
  const res = await client.post<LLMProfile>('/llm-profiles', input);
  return res.data;
}

export async function updateLLMProfile(id: string, input: LLMProfileInput): Promise<LLMProfile> {
  const res = await client.put<LLMProfile>(`/llm-profiles/${id}`, input);
  return res.data;
}

export async function deleteLLMProfile(id: string): Promise<void> {
  await client.delete(`/llm-profiles/${id}`);
}

export async function activateLLMProfile(id: string): Promise<LLMProfile> {
  const res = await client.post<LLMProfile>(`/llm-profiles/${id}/activate`);
  return res.data;
}

export async function testLLM(cfg: { base_url: string; model: string; api_key?: string }): Promise<LLMTestResult> {
  const res = await client.post<LLMTestResult>('/config/test-llm', cfg);
  return res.data;
}

// ── Embedding config ────────────────────────────────────────────

export interface EmbeddingConfig {
  provider: string;
  base_url: string;
  model: string;
  dimension: number;
  has_key: boolean;
}

export interface EmbeddingConfigInput {
  provider: string;
  base_url?: string;
  model: string;
  dimension: number;
  api_key?: string;
}

export async function getEmbeddingConfig(): Promise<EmbeddingConfig> {
  const res = await client.get<EmbeddingConfig>('/config/embedding');
  return res.data;
}

export async function saveEmbeddingConfig(cfg: EmbeddingConfigInput): Promise<EmbeddingConfig> {
  const res = await client.put<EmbeddingConfig>('/config/embedding', cfg);
  return res.data;
}
