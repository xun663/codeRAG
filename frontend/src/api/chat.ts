import client from './client';
import { storage } from '@/utils/storage';
import type { PaginatedResponse } from './kbs';

export interface ConversationResponse {
  id: string;
  user_id: string;
  kb_id: string | null;
  title: string | null;
  message_count: number;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface MessageResponse {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  content_type: string;
  retrieval_config?: any;
  retrieved_chunks?: any[];
  llm_provider?: string;
  llm_model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  latency_ms?: number;
  user_rating?: number;
  created_at: string;
}

export interface ConversationData {
  title?: string;
  kb_id?: string;
}

export interface SendMessageData {
  content: string;
  kb_id?: string;
}

export function listConversations(params?: {
  page?: number;
  pageSize?: number;
}): Promise<PaginatedResponse<ConversationResponse>> {
  // 后端分页参数是 page_size（snake_case），axios 直传 pageSize 会匹配不上导致用默认 20
  return client.get('/chat/conversations', {
    params: { page: params?.page, page_size: params?.pageSize },
  }).then((res) => res.data);
}

export function createConversation(data: ConversationData): Promise<ConversationResponse> {
  return client.post('/chat/conversations', data).then((res) => res.data);
}

export function getConversation(id: string): Promise<ConversationResponse> {
  return client.get(`/chat/conversations/${id}`).then((res) => res.data);
}

export function deleteConversation(id: string): Promise<void> {
  return client.delete(`/chat/conversations/${id}`);
}

export function listMessages(
  conversationId: string,
  params?: { page?: number; pageSize?: number }
): Promise<PaginatedResponse<MessageResponse>> {
  return client
    .get(`/chat/conversations/${conversationId}/messages`, {
      params: { page: params?.page, page_size: params?.pageSize },
    })
    .then((res) => res.data);
}

export function sendMessage(
  conversationId: string,
  data: SendMessageData
): Promise<MessageResponse> {
  return client
    .post(`/chat/conversations/${conversationId}/messages`, data)
    .then((res) => res.data);
}

export interface StreamEvent {
  type: 'token' | 'sources' | 'done' | 'error' | 'phase';
  content?: string;
  sources?: any[];
  phase?: string;
  message?: string;
  conversation_id?: string;
  message_id?: string;
}

export class ChatStream {
  private abortController: AbortController | null = null;

  async streamMessage(
    conversationId: string,
    content: string,
    kbId: string | undefined,
    onToken: (token: string) => void,
    onSources?: (sources: any[]) => void,
    onError?: (error: Error) => void,
    onPhase?: (phase: string, message: string) => void,
  ): Promise<string> {
    this.abortController = new AbortController();
    const token = storage.get('accessToken');
    let fullContent = '';

    try {
      const response = await fetch(`/api/v1/chat/conversations/${conversationId}/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content, ...(kbId ? { kb_id: kbId } : {}) }),
        signal: this.abortController.signal,
      });

      if (!response.ok) throw new Error(`Stream failed: ${response.statusText}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No reader');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;
          const jsonStr = trimmed.slice(6);
          try {
            const evt: StreamEvent = JSON.parse(jsonStr);
            if (evt.type === 'token' && evt.content) {
              fullContent += evt.content;
              onToken(evt.content);
            } else if (evt.type === 'sources' && evt.sources) {
              onSources?.(evt.sources);
            } else if (evt.type === 'phase' && evt.phase) {
              onPhase?.(evt.phase, evt.message || '');
            } else if (evt.type === 'done') {
              fullContent = evt.content || fullContent;
            } else if (evt.type === 'error') {
              onError?.(new Error(evt.content || 'Stream error'));
              return fullContent;
            }
          } catch { /* skip malformed JSON */ }
        }
      }
    } catch (error) {
      if (error instanceof Error && error.name !== 'AbortError') {
        onError?.(error);
      }
    }
    return fullContent;
  }

  abort(): void {
    this.abortController?.abort();
  }
}

export function createChatStream(): ChatStream {
  return new ChatStream();
}
