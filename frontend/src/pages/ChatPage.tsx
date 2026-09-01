import React, { useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Input, Button, Typography, List, Empty, Popconfirm, message as antMsg, Tag, Spin, Drawer } from 'antd';
import { SendOutlined, PlusOutlined, MessageOutlined, DeleteOutlined, DatabaseOutlined, MenuOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useChatStore } from '@/stores/chatStore';
import { useIsMobile } from '@/hooks/useIsMobile';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import MarkdownRenderer from '@/components/common/MarkdownRenderer';
import KBSelectorModal from '@/components/Chat/KBSelectorModal';
import * as kbsApi from '@/api/kbs';
import type { KBResponse } from '@/api/kbs';

const { Text } = Typography;
const { TextArea } = Input;

// Memoized message bubble to prevent re-render of old messages during streaming
const MessageBubble = React.memo(({ msg }: { msg: { id: string; role: string; content: string } }) => (
  <div style={{
    display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
    marginBottom: 16,
  }}>
    <div style={{
      maxWidth: '80%', padding: '12px 16px', borderRadius: 12,
      background: msg.role === 'user' ? '#1677ff' : '#f5f5f5',
      color: msg.role === 'user' ? '#fff' : 'inherit',
    }}>
      {msg.role === 'user'
        ? <Text style={{ color: '#fff', whiteSpace: 'pre-wrap' }}>{msg.content}</Text>
        : <MarkdownRenderer content={msg.content} />}
    </div>
  </div>
));

const ChatPage: React.FC = () => {
  const { t } = useTranslation();
  const { convId } = useParams<{ convId?: string }>();
  const navigate = useNavigate();

  const store = useChatStore();
  const {
    conversations, activeConvId, messagesByConv, streamingContent, streamPhase,
    loadingConv, loadingMessages, sending,
    fetchConversations, selectConversation,
    createConversation, deleteConversation, sendMessage,
  } = store;
  const isMobile = useIsMobile();
  const [convDrawerOpen, setConvDrawerOpen] = React.useState(false);

  const messages = (activeConvId && messagesByConv?.[activeConvId]) ? messagesByConv[activeConvId] : [];

  const [inputValue, setInputValue] = React.useState('');
  const [showKBSelector, setShowKBSelector] = React.useState(false);
  const [kbMap, setKbMap] = React.useState<Record<string, KBResponse>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const isStreamingRef = useRef(false);
  const rafIdRef = useRef<number>(0);

  // initial load
  useEffect(() => { fetchConversations(); }, [fetchConversations]);

  // load KB list for name lookup
  useEffect(() => {
    kbsApi.listKBs({ page: 1, pageSize: 50 }).then((res) => {
      const map: Record<string, KBResponse> = {};
      for (const kb of res.items || []) {
        map[kb.id] = kb;
      }
      setKbMap(map);
    }).catch(() => {});
  }, [conversations.length]);  // refresh when conversations change

  // sync URL param to store
  useEffect(() => {
    if (convId && convId !== activeConvId) {
      selectConversation(convId);
    } else if (!convId) {
      useChatStore.setState({ activeConvId: null });
    }
  }, [convId, activeConvId, selectConversation]);

  // Track streaming state
  useEffect(() => {
    isStreamingRef.current = !!streamingContent;
  }, [streamingContent]);

  // Auto-scroll: instant during streaming (rAF-throttled), smooth otherwise
  const scrollToBottom = useCallback((smooth: boolean) => {
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
    }
    rafIdRef.current = requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({
        behavior: smooth ? 'smooth' : 'auto',
        block: 'end',
      });
    });
  }, []);

  useEffect(() => {
    if (messages.length === 0 && !streamingContent) return;
    // During streaming use instant scroll to avoid animation pile-up jitter
    scrollToBottom(!streamingContent);
  }, [messages, streamingContent, scrollToBottom]);

  const handleSelect = (id: string) => navigate(`/chat/${id}`);

  const handleNew = () => {
    setShowKBSelector(true);
  };

  const handleKBSelect = async (kbId: string | null) => {
    setShowKBSelector(false);
    const id = await createConversation(kbId ?? undefined);
    navigate(`/chat/${id}`);
  };

  const handleKBCancel = () => {
    setShowKBSelector(false);
  };

  const handleDelete = async (id: string) => {
    await deleteConversation(id);
    if (activeConvId === id) navigate('/chat');
    antMsg.success(t('chat.deleteSuccess'));
  };

  const handleSend = async () => {
    if (!inputValue.trim() || !activeConvId) return;
    const text = inputValue.trim();
    setInputValue('');
    await sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 对话列表内容：桌面端放固定侧栏，移动端放 Drawer
  const conversationList = (
    <>
      <Button type="primary" icon={<PlusOutlined />} block onClick={handleNew} style={{ marginBottom: 12, flexShrink: 0 }}>
        {t('chat.newChat')}
      </Button>
      {loadingConv ? (
        <LoadingSpinner size="small" />
      ) : (conversations || []).length === 0 ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Empty description={t('chat.noConversations')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          <List
            dataSource={conversations}
            renderItem={(c) => (
              <List.Item
                onClick={() => handleSelect(c.id)}
                style={{
                  cursor: 'pointer', padding: '8px 12px', borderRadius: 6,
                  background: activeConvId === c.id ? '#e6f4ff' : 'transparent',
                }}
                actions={[
                  <Popconfirm key="del" title={t('chat.deleteConfirm')} onConfirm={(e) => { e?.stopPropagation(); handleDelete(c.id); }}>
                    <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<MessageOutlined style={{ color: activeConvId === c.id ? '#1677ff' : '#999' }} />}
                  title={<Text ellipsis style={{ fontWeight: activeConvId === c.id ? 600 : 400 }}>{c.title || 'Untitled'}</Text>}
                  description={
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>{t('chat.messagesCount', { count: c.message_count || 0 })}</Text>
                      {c.kb_id && kbMap[c.kb_id] && (
                        <Tag color="blue" style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>
                          <DatabaseOutlined style={{ fontSize: 10 }} /> {kbMap[c.kb_id]?.name ?? 'KB'}
                        </Tag>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        </div>
      )}
    </>
  );

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 120px)', gap: 16, minHeight: 0 }}>
      {/* 对话列表：桌面端固定侧栏，移动端抽屉 */}
      {!isMobile && (
        <div style={{ width: 280, flexShrink: 0, height: '100%', display: 'flex', flexDirection: 'column', background: '#fff', borderRadius: 8, padding: 12 }}>
          {conversationList}
        </div>
      )}

      {/* main — 独立滚动容器 */}
      <Card style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', minWidth: 0 }}
        title={
          (isMobile ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Button type="text" icon={<MenuOutlined />} onClick={() => setConvDrawerOpen(true)} style={{ marginLeft: -12 }} />
              <span>Chat</span>
              {(() => {
                const conv = conversations.find(c => c.id === activeConvId);
                if (conv?.kb_id && kbMap[conv.kb_id]) {
                  return (
                    <Tag color="blue" style={{ fontSize: 12 }}>
                      <DatabaseOutlined /> {kbMap[conv.kb_id]?.name ?? 'KB'}
                    </Tag>
                  );
                }
                return null;
              })()}
            </div>
          ) : activeConvId ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Chat</span>
              {(() => {
                const conv = conversations.find(c => c.id === activeConvId);
                if (conv?.kb_id && kbMap[conv.kb_id]) {
                  return (
                    <Tag color="blue" style={{ fontSize: 12 }}>
                      <DatabaseOutlined /> {kbMap[conv.kb_id]?.name ?? 'KB'}
                    </Tag>
                  );
                }
                return null;
              })()}
            </div>
          ) : undefined)
        }
        styles={{ body: { flex: 1, display: 'flex', flexDirection: 'column', padding: isMobile ? 12 : 24, minHeight: 0, overflow: 'hidden' } }}>
        <div
          ref={messagesContainerRef}
          style={{
            flex: 1, overflowY: 'auto', minHeight: 0, marginBottom: 16,
            overflowAnchor: 'auto',
          }}
        >
          {!activeConvId ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Empty description={t('chat.newConversation')} />
            </div>
          ) : loadingMessages ? (
            <LoadingSpinner tip={t('common.loading')} />
          ) : messages.length === 0 && !streamingContent ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Empty description={t('chat.noMessages')} />
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} />
              ))}
              {streamingContent && (
                <div style={{
                  display: 'flex', justifyContent: 'flex-start', marginBottom: 16,
                  overflowAnchor: 'none',
                }}>
                  <div style={{ maxWidth: '80%', padding: '12px 16px', borderRadius: 12, background: '#f5f5f5' }}>
                    <MarkdownRenderer content={streamingContent} />
                  </div>
                </div>
              )}
              {sending && !streamingContent && streamPhase && (
                <div style={{
                  display: 'flex', justifyContent: 'flex-start', marginBottom: 16,
                  overflowAnchor: 'none',
                }}>
                  <div style={{
                    maxWidth: '80%', padding: '10px 16px', borderRadius: 12,
                    background: '#f5f5f5', color: '#666', fontSize: 13,
                    display: 'flex', alignItems: 'center', gap: 8,
                  }}>
                    <Spin size="small" />
                    {streamPhase}
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <TextArea
            rows={3}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={activeConvId ? t('chat.inputPlaceholder') : t('chat.selectFirst')}
            disabled={!activeConvId || sending}
            style={{ flex: 1 }}
          />
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend}
            loading={sending} disabled={!activeConvId || !inputValue.trim()}
            style={{ height: 'auto', alignSelf: 'flex-end' }}>{t('chat.send')}</Button>
        </div>
      </Card>

      {/* KB Selector Modal */}
      <KBSelectorModal
        open={showKBSelector}
        onSelect={handleKBSelect}
        onCancel={handleKBCancel}
      />

      {/* 移动端：对话列表抽屉 */}
      {isMobile && (
        <Drawer
          title={t('chat.conversations')}
          placement="left"
          width={280}
          open={convDrawerOpen}
          onClose={() => setConvDrawerOpen(false)}
          styles={{ body: { padding: 12, height: '100%', display: 'flex', flexDirection: 'column' } }}
        >
          {conversationList}
        </Drawer>
      )}
    </div>
  );
};

export default ChatPage;
