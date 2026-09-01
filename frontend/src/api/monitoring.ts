import client from './client';

export interface HealthCheckDetail {
  status: string;
  detail?: string | null;
}

export interface SystemHealth {
  status: string;
  checks: Record<string, HealthCheckDetail>;
}

export interface ModelUsage {
  provider: string | null;
  model: string | null;
  count: number;
}

export interface KBStorageItem {
  name: string;
  docs: number;
  chunks: number;
  vectordb_chunks: number;
}

export interface LatencyStats {
  avg_ms: number;
  min_ms: number;
  max_ms: number;
  total_requests: number;
}

export interface TokenStats {
  total_prompt: number;
  total_completion: number;
  avg_per_request: number;
  total_requests: number;
}

export interface RatingSummary {
  avg: number;
  total: number;
  distribution: Record<number, number>;
}

export interface DashboardSummary {
  system_health: SystemHealth;
  usage: {
    total_conversations: number;
    total_messages: number;
    total_users: number;
    total_kbs: number;
    total_documents: number;
  };
  latency: LatencyStats;
  tokens: TokenStats;
  models: ModelUsage[];
  kb_storage: KBStorageItem[];
  ratings: RatingSummary;
  recent_activity: { hour: string; count: number }[];
}

export interface HealthResponse {
  status: string;
  version: string;
  checks: Record<string, HealthCheckDetail>;
}

export async function getDashboard(): Promise<DashboardSummary> {
  const res = await client.get<DashboardSummary>('/monitoring/dashboard');
  return res.data;
}

export async function getModels(): Promise<ModelUsage[]> {
  const res = await client.get<ModelUsage[]>('/monitoring/models');
  return res.data;
}

export async function getKBStorage(): Promise<KBStorageItem[]> {
  const res = await client.get<KBStorageItem[]>('/monitoring/kb-storage');
  return res.data;
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await client.get<HealthResponse>('/health');
  return res.data;
}
