import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Card, List, Typography, Tag, Space, Empty, Spin, Radio } from 'antd';
import { DatabaseOutlined, FileTextOutlined, ThunderboltOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import * as kbsApi from '@/api/kbs';
import type { KBResponse } from '@/api/kbs';

const { Text } = Typography;

const QUALITY_TAG: Record<string, { color: string; label: string }> = {
  verified: { color: 'green', label: '已质检' },
  unverified: { color: 'red', label: '未达标' },
  no_qa_data: { color: 'orange', label: '无考题' },
  not_checked: { color: 'default', label: '未检测' },
};

interface KBSelectorModalProps {
  open: boolean;
  onSelect: (kbId: string | null) => void;
  onCancel: () => void;
  showPureLLM?: boolean;  // Show "Pure Model Chat" option (default: true)
}

const KBSelectorModal: React.FC<KBSelectorModalProps> = ({ open, onSelect, onCancel, showPureLLM = true }) => {
  const [kbs, setKBs] = useState<KBResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setLoading(true);
      setSelectedId(null);
      kbsApi.listKBs({ page: 1, pageSize: 50 })
        .then((res) => setKBs(res.items || []))
        .catch(() => setKBs([]))
        .finally(() => setLoading(false));
    }
  }, [open]);

  // 官方知识库（平台策展）与个人知识库分组
  const { officialKbs, personalKbs } = useMemo(() => {
    return {
      officialKbs: kbs.filter((kb) => kb.scope === 'platform'),
      personalKbs: kbs.filter((kb) => kb.scope !== 'platform'),
    };
  }, [kbs]);

  const renderKbCard = (kb: KBResponse) => {
    const isSelected = selectedId === kb.id;
    return (
      <Card
        size="small"
        style={{
          marginBottom: 8,
          cursor: 'pointer',
          border: isSelected ? '2px solid #1677ff' : '1px solid #d9d9d9',
          background: isSelected ? '#f0f5ff' : '#fff',
        }}
        onClick={() => setSelectedId(kb.id)}
        hoverable
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Space size={6} wrap style={{ wordBreak: 'break-word' }}>
              <Text strong>{kb.name}</Text>
              {kb.scope === 'platform' && (
                <Tag color="blue" style={{ marginInlineEnd: 0 }}>官方</Tag>
              )}
              <Tag
                color={QUALITY_TAG[kb.quality_status]?.color || 'default'}
                style={{ marginInlineEnd: 0 }}
              >
                {QUALITY_TAG[kb.quality_status]?.label || kb.quality_status}
              </Tag>
            </Space>
            {kb.description && (
              <div>
                <Text type="secondary" style={{ fontSize: 12, wordBreak: 'break-word' }}>
                  {kb.description}
                </Text>
              </div>
            )}
            <div style={{ marginTop: 4 }}>
              <Space size={4} wrap>
                <Tag color="blue" style={{ fontSize: 11 }}>
                  <FileTextOutlined /> {kb.doc_count} docs
                </Tag>
                <Tag color="green" style={{ fontSize: 11 }}>
                  {kb.chunk_count} chunks
                </Tag>
                <Tag style={{ fontSize: 11 }}>
                  {kb.kb_type || 'general'}
                </Tag>
              </Space>
            </div>
          </div>
          <Radio checked={isSelected} style={{ marginTop: 4 }} />
        </div>
      </Card>
    );
  };

  const handleOk = () => {
    onSelect(selectedId);
  };

  const handleCancel = () => {
    setSelectedId(null);
    onCancel();
  };

  return (
    <Modal
      title={
        <Space>
          <DatabaseOutlined />
          <span>选择知识库</span>
        </Space>
      }
      open={open}
      onOk={handleOk}
      onCancel={handleCancel}
      okText={selectedId ? '开始对话' : '开始纯模型对话'}
      cancelText="取消"
      width="100%"
      style={{ maxWidth: 560, margin: '0 auto' }}
      destroyOnClose
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" />
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">加载知识库列表...</Text>
          </div>
        </div>
      ) : kbs.length === 0 ? (
        <Empty
          description="暂无可用知识库"
          style={{ padding: 40 }}
        >
          <Text type="secondary">
            请先在 Dashboard 中上传文档创建知识库。
          </Text>
        </Empty>
      ) : (
        <div style={{ maxHeight: 380, overflowY: 'auto' }}>
          {/* Pure LLM option — only shown for chat, not quiz */}
          {showPureLLM && (
            <Card
              size="small"
              style={{
                marginBottom: 12,
                cursor: 'pointer',
                border: selectedId === null ? '2px solid #1677ff' : '1px solid #d9d9d9',
                background: selectedId === null ? '#f0f5ff' : '#fff',
              }}
              onClick={() => setSelectedId(null)}
              hoverable
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ThunderboltOutlined style={{ fontSize: 20, color: '#faad14' }} />
                <div>
                  <Text strong>纯模型对话</Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    不使用知识库，LLM 基于训练数据直接回答。适合一般性问题和闲聊。
                  </Text>
                </div>
              </div>
            </Card>
          )}

          {/* Official KBs (平台策展) */}
          {officialKbs.length > 0 && (
            <>
              <div style={{ margin: '8px 0 6px' }}>
                <Space size={6}>
                  <SafetyCertificateOutlined style={{ color: '#1677ff' }} />
                  <Text strong style={{ fontSize: 13 }}>官方知识库</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>平台策展 · 质检通过 · 全员可用</Text>
                </Space>
              </div>
              <List
                dataSource={officialKbs}
                renderItem={renderKbCard}
              />
            </>
          )}

          {/* Personal KBs (自建) */}
          {personalKbs.length > 0 && (
            <>
              <div style={{ margin: '12px 0 6px' }}>
                <Space size={6}>
                  <UserOutlined style={{ color: '#52c41a' }} />
                  <Text strong style={{ fontSize: 13 }}>我的知识库</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>个人上传 · 仅自己可见</Text>
                </Space>
              </div>
              <List
                dataSource={personalKbs}
                renderItem={renderKbCard}
              />
            </>
          )}
        </div>
      )}
    </Modal>
  );
};

export default KBSelectorModal;
