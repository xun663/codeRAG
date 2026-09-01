import { create } from 'zustand';
import type { ConversationResponse, MessageResponse } from '@/api/chat';
import * as chatApi from '@/api/chat';

interface ChatState {
  conversations: ConversationResponse[];
  messagesByConv: Record<string, MessageResponse[]>; // convId → messages cache
  activeConvId: string | null;
  streamingContent: string;
  streamPhase: string;           // Current processing phase for streaming
  loadingConv: boolean;
  loadingMessages: boolean;
  sending: boolean;

  fetchConversations: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  createConversation: (kbId?: string) => Promise<string>;
  deleteConversation: (id: string) => Promise<void>;
  sendMessage: (content: string, kbId?: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  messagesByConv: {},
  activeConvId: null,
  streamingContent: '',
  streamPhase: '',
  loadingConv: false,
  loadingMessages: false,
  sending: false,

  fetchConversations: async () => {
    set({ loadingConv: true });
    try {
      const result = await chatApi.listConversations({ page: 1, pageSize: 50 });
      set({ conversations: result.items || [], loadingConv: false });
    } catch {
      set({ loadingConv: false });
    }
  },

  selectConversation: async (id: string) => {
    const { messagesByConv } = get();
    if (messagesByConv[id]) {
      set({ activeConvId: id });
      return;
    }
    set({ activeConvId: id, loadingMessages: true });
    try {
      const result = await chatApi.listMessages(id, { page: 1, pageSize: 100 });
      set((s) => ({
        messagesByConv: { ...s.messagesByConv, [id]: result.items || [] },
        loadingMessages: false,
      }));
    } catch {
      set({ loadingMessages: false });
    }
  },

  createConversation: async (kbId?: string) => {
    const conv = await chatApi.createConversation({
      title: 'New Chat',
      ...(kbId ? { kb_id: kbId } : {}),
    });
    set((s) => ({ conversations: [conv, ...s.conversations] }));
    return conv.id;
  },

  deleteConversation: async (id: string) => {
    await chatApi.deleteConversation(id);
    set((s) => {
      const newMsgs = { ...s.messagesByConv };
      delete newMsgs[id];
      return {
        conversations: s.conversations.filter((c) => c.id !== id),
        messagesByConv: newMsgs,
        activeConvId: s.activeConvId === id ? null : s.activeConvId,
      };
    });
  },

  sendMessage: async (content: string, kbId?: string) => {
    const { activeConvId, messagesByConv } = get();
    if (!activeConvId || !content.trim() || get().sending) return;

    set({ sending: true, streamingContent: '', streamPhase: '' });

    const userMsg: MessageResponse = {
      id: `temp-${Date.now()}`,
      conversation_id: activeConvId,
      role: 'user',
      content,
      content_type: 'markdown',
      created_at: new Date().toISOString(),
    };

    const prevMsgs = messagesByConv[activeConvId] || [];
    set((s) => ({
      messagesByConv: { ...s.messagesByConv, [activeConvId]: [...prevMsgs, userMsg] },
    }));

    let fullContent = '';
    const stream = chatApi.createChatStream();
    try {
      fullContent = await stream.streamMessage(
        activeConvId, content, kbId,
        (token) => set((s) => ({ streamingContent: s.streamingContent + token })),
        undefined,
        undefined,
        (_phase, message) => set({ streamPhase: message }),
      );
    } catch {
      // stream failed
    }

    if (fullContent) {
      const assistantMsg: MessageResponse = {
        id: `stream-${Date.now()}`,
        conversation_id: activeConvId,
        role: 'assistant',
        content: fullContent,
        content_type: 'markdown',
        created_at: new Date().toISOString(),
      };
      const current = get().messagesByConv[activeConvId] || [];
      set((s) => ({
        messagesByConv: { ...s.messagesByConv, [activeConvId]: [...current, assistantMsg] },
        sending: false,
        streamingContent: '',
      }));
    } else {
      // Non-streaming fallback
      try {
        const resp = await chatApi.sendMessage(activeConvId, { content, kb_id: kbId });
        const current = get().messagesByConv[activeConvId] || [];
        set((s) => ({
          messagesByConv: { ...s.messagesByConv, [activeConvId]: [...current, resp] },
          sending: false,
          streamingContent: '',
        }));
      } catch {
        set({ sending: false, streamingContent: '' });
      }
    }
    get().fetchConversations();
  },
}));
