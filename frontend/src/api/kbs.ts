import client from './client';

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface KBResponse {
  id: string;
  name: string;
  description: string | null;
  owner_id: string;
  kb_type: string;
  visibility: string;
  /** platform（平台策展库）/ personal（个人库） */
  scope: string;
  /** not_checked / verified / unverified / no_qa_data */
  quality_status: string;
  quality_metrics_json: Record<string, unknown> | null;
  current_version: number;
  doc_count: number;
  chunk_count: number;
  status: string;
  config_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateKBData {
  name: string;
  description?: string;
  kb_type?: string;
  visibility?: string;
  scope?: 'platform' | 'personal';
}

export interface QualityGateResponse {
  kb_id: string;
  status: string;
  total_qa: number;
  doc_level_pairs: number;
  chunk_level_pairs: number;
  metrics: {
    avg_doc_hit_at_5?: number;
    avg_doc_mrr?: number;
    avg_ndcg_at_5?: number;
    avg_chunk_recall_at_5?: number | null;
    chunk_level_pairs?: number;
  };
  thresholds: Record<string, number>;
  latency_ms: number;
  run_at: string;
  // 自动门禁（mode=auto）额外字段
  mode?: 'auto' | 'manual';
  quality_score?: number;
  rounds?: number;
  per_pair: Array<{
    qa_pair_id: string;
    question: string;
    doc_hit_at_5: number;
    doc_mrr: number;
    ndcg_at_5: number;
    chunk_recall_at_5: number | null;
  }>;
}

export interface KBQualityReportItem {
  kb_id: string;
  name: string;
  scope: string;
  visibility: string;
  quality_status: string;
  current_version: number;
  doc_count: number;
  chunk_count: number;
  cleaning: {
    docs_with_cleaning: number;
    before_chars: number;
    after_chars: number;
    removed_chars: number;
    removed_pct?: number;
  };
  chunk_stats: {
    total_tokens: number;
    avg_tokens_per_chunk: number;
    chunk_type_distribution: Record<string, number>;
  };
  gate: {
    status?: string;
    metrics?: QualityGateResponse['metrics'];
    thresholds?: Record<string, number>;
    run_at?: string;
    latency_ms?: number;
    doc_level_pairs?: number;
    // 自动门禁（mode=auto）字段
    mode?: 'auto' | 'manual';
    quality_score?: number;
    total_qa?: number;
    rounds?: number;
  } | null;
  updated_at: string;
}

export interface UpdateKBData {
  name?: string;
  description?: string;
  visibility?: string;
  config_json?: Record<string, unknown>;
}

export interface KBStatsResponse {
  kb_id: string;
  doc_count: number;
  chunk_count: number;
  total_tokens: number;
  avg_chunk_size: number;
}

export interface DocumentResponse {
  id: string;
  kb_id: string;
  title: string;
  source_type: string;
  source_url: string | null;
  file_path: string | null;
  file_size: number | null;
  mime_type: string | null;
  word_count: number | null;
  status: string;
  error_message: string | null;
  version: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function listKBs(params?: {
  page?: number;
  pageSize?: number;
}): Promise<PaginatedResponse<KBResponse>> {
  return client.get('/kbs', {
    params: { page: params?.page, page_size: params?.pageSize },
  }).then((res) => res.data);
}

export function createKB(data: CreateKBData): Promise<KBResponse> {
  return client.post('/kbs', data).then((res) => res.data);
}

export function getKB(id: string): Promise<KBResponse> {
  return client.get(`/kbs/${id}`).then((res) => res.data);
}

export function updateKB(id: string, data: UpdateKBData): Promise<KBResponse> {
  return client.patch(`/kbs/${id}`, data).then((res) => res.data);
}

export function deleteKB(id: string): Promise<void> {
  return client.delete(`/kbs/${id}`);
}

export function getKBStats(id: string): Promise<KBStatsResponse> {
  return client.get(`/kbs/${id}/stats`).then((res) => res.data);
}

/** [admin] 全库质量报告 */
export function qualityReport(): Promise<KBQualityReportItem[]> {
  return client.get('/kbs/quality-report').then((res) => res.data);
}

/** [admin] 对知识库运行入库质量门禁 */
export function runQualityGate(kbId: string): Promise<QualityGateResponse> {
  return client.post(`/kbs/${kbId}/quality-gate`).then((res) => res.data);
}

export function listDocuments(
  kbId: string,
  params?: { page?: number; pageSize?: number }
): Promise<PaginatedResponse<DocumentResponse>> {
  return client.get(`/kbs/${kbId}/documents`, {
    params: { page: params?.page, page_size: params?.pageSize },
  }).then((res) => res.data);
}

export function uploadDocument(kbId: string, file: File): Promise<DocumentResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return client
    .post(`/kbs/${kbId}/documents/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => res.data);
}

export function uploadDocuments(kbId: string, files: File[]): Promise<DocumentResponse[]> {
  const formData = new FormData();
  files.forEach((f) => formData.append('files', f));
  return client
    .post(`/kbs/${kbId}/documents/upload-many`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => res.data);
}

export function deleteDocument(kbId: string, docId: string): Promise<void> {
  return client.delete(`/kbs/${kbId}/documents/${docId}`);
}

// ── 成员管理（按用户名分享）──────────────────────────────────────

export interface KBMember {
  id: string;
  user_id: string;
  username?: string | null;
  permission: string;
  created_at: string;
}

export function listMembers(kbId: string): Promise<KBMember[]> {
  return client.get(`/kbs/${kbId}/members`).then((res) => res.data);
}

export function addMember(
  kbId: string,
  data: { user_id: string; permission?: string }
): Promise<KBMember> {
  return client.post(`/kbs/${kbId}/members`, data).then((res) => res.data);
}

export function removeMember(kbId: string, userId: string): Promise<void> {
  return client.delete(`/kbs/${kbId}/members/${userId}`);
}

// ── 自动化质量门禁（无需人工 GT）────────────────────────────────

export interface QualityCheckTaskResponse {
  kb_id: string;
  task_id: string;
  status: string;
}

export interface QualityCheckTaskStatus {
  task_id: string;
  status: string; // PENDING / STARTED / SUCCESS / FAILURE
  result?: {
    status?: string;
    kb_id?: string;
    report?: {
      status?: string;
      quality_score?: number;
      total_qa?: number;
      rounds?: number;
      avg_metrics?: {
        doc_hit?: number;
        context_recall?: number;
        mrr?: number;
        ndcg?: number;
      };
      per_round?: Array<{ round: number; n: number; avg_doc_hit?: number; avg_context_recall?: number }>;
      suggestions?: string[];
    };
  } | null;
  error?: string | null;
}

/** 提交自动质量门禁（异步，返回 task_id）。 */
export function runQualityCheck(kbId: string): Promise<QualityCheckTaskResponse> {
  return client.post(`/kbs/${kbId}/quality-check`).then((res) => res.data);
}

/** 轮询自动质量门禁任务状态。 */
export function getQualityCheckTask(taskId: string): Promise<QualityCheckTaskStatus> {
  return client.get(`/kbs/quality-check/tasks/${taskId}`).then((res) => res.data);
}
