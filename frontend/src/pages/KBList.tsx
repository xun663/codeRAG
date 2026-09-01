import React, { useState, useEffect } from 'react';
import { Row, Col, Card, Button, Typography, Space, Empty, Modal, Form, Input, Select, Tag, App } from 'antd';
import { PlusOutlined, BookOutlined, FileTextOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import * as kbsApi from '@/api/kbs';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useAuthStore } from '@/stores/authStore';

const { Title, Text } = Typography;

const KB_TYPES = [
  { label: '通用', value: 'general' },
  { label: 'Python', value: 'python' },
  { label: 'JavaScript', value: 'javascript' },
  { label: 'TypeScript', value: 'typescript' },
  { label: 'Java', value: 'java' },
  { label: 'C', value: 'c' },
  { label: 'C++', value: 'cpp' },
  { label: 'C#', value: 'csharp' },
  { label: 'Go', value: 'go' },
  { label: 'Rust', value: 'rust' },
  { label: 'HTML/CSS', value: 'web' },
  { label: 'Markdown', value: 'markdown' },
  { label: '多语言', value: 'multi' },
];

const VISIBILITY_OPTIONS = [
  { label: '私有（仅自己/成员）', value: 'private' },
  { label: '公开（全员可见）', value: 'public' },
];

const QUALITY_STATUS_META: Record<string, { color: string; label: string }> = {
  verified: { color: 'green', label: '已验证' },
  unverified: { color: 'red', label: '未达标' },
  no_qa_data: { color: 'orange', label: '无评估数据' },
  not_checked: { color: 'default', label: '未检测' },
};

const SCOPE_OPTIONS = [
  { label: '平台策展库（质量门禁）', value: 'platform' },
  { label: '个人库（隔离）', value: 'personal' },
];

const KBList: React.FC = () => {
  const { message } = App.useApp();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const isAdmin = user?.role === 'admin';
  const [kbs, setKbs] = useState<kbsApi.KBResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const fetchKBs = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await kbsApi.listKBs({ page: 1, pageSize: 50 });
      setKbs(result.items || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('kb.loadFailed');
      setError(msg);
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchKBs(); }, []);

  const handleCreate = async (values: Record<string, unknown>) => {
    try {
      setCreating(true);
      await kbsApi.createKB({
        name: values.name as string,
        description: values.description as string | undefined,
        kb_type: values.kb_type as string,
        visibility: values.visibility as string | undefined,
        scope: (values.scope as 'platform' | 'personal' | undefined) || (isAdmin ? 'platform' : 'personal'),
      });
      message.success(t('kb.createSuccess'));
      setModalOpen(false);
      form.resetFields();
      fetchKBs();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : t('kb.createFailed'));
    } finally {
      setCreating(false);
    }
  };

  if (loading) return <LoadingSpinner />;

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>{t('kb.title')}</Title>
          <Text type="secondary">{t('kb.subtitle')}</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} size="large" onClick={() => setModalOpen(true)}>
          {t('kb.create')}
        </Button>
      </div>

      {error ? (
        <Card><Text type="danger">{error}</Text></Card>
      ) : kbs.length === 0 ? (
        <Card>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('kb.noKb')}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
              {t('kb.create')}
            </Button>
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {kbs.map((kb) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={kb.id}>
              <Card hoverable onClick={() => navigate(`/kbs/${kb.id}`)} style={{ height: '100%' }}>
                <Card.Meta
                  avatar={<BookOutlined style={{ fontSize: 24, color: '#1677ff' }} />}
                  title={
                    <Space size={6}>
                      {kb.name}
                      {kb.scope === 'platform' ? (
                        <Tag color="blue" style={{ marginInlineEnd: 0 }}>平台</Tag>
                      ) : (
                        <Tag style={{ marginInlineEnd: 0 }}>个人</Tag>
                      )}
                      <Tag
                        color={QUALITY_STATUS_META[kb.quality_status]?.color || 'default'}
                        style={{ marginInlineEnd: 0 }}
                      >
                        {QUALITY_STATUS_META[kb.quality_status]?.label || kb.quality_status}
                      </Tag>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={4}>
                      <Text type="secondary" ellipsis>{kb.description || t('kb.noDescription')}</Text>
                      <Space size="small">
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          <FileTextOutlined /> {kb.doc_count || 0} {t('kb.docsCount', { count: kb.doc_count || 0 })}
                        </Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{kb.kb_type}</Text>
                      </Space>
                    </Space>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal title={t('kb.createModal')} open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        footer={null} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={handleCreate}
          initialValues={{ kb_type: 'general', visibility: isAdmin ? 'public' : 'private', scope: isAdmin ? 'platform' : 'personal' }}>
          <Form.Item name="name" label={t('kb.name')}
            rules={[{ required: true, message: t('kb.nameRequired') }, { min: 2, message: t('kb.nameMinLength') }]}>
            <Input placeholder={t('kb.name')} />
          </Form.Item>
          <Form.Item name="description" label={t('kb.description')}>
            <Input.TextArea rows={3} placeholder={t('kb.description')} />
          </Form.Item>
          <Form.Item name="kb_type" label={t('kb.type')}
            rules={[{ required: true, message: t('kb.typeRequired') }]}>
            <Select options={KB_TYPES} />
          </Form.Item>
          {isAdmin ? (
            <Form.Item name="visibility" label={t('kb.visibility')}
              tooltip="官方库默认公开；调试期可切为私有（仅管理员可见），测完切回公开">
              <Select options={VISIBILITY_OPTIONS} />
            </Form.Item>
          ) : (
            <Form.Item style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                个人知识库默认私有，分享给他人需通过「成员」功能添加用户。
              </Text>
            </Form.Item>
          )}
          {isAdmin && (
            <Form.Item name="scope" label="知识库类型">
              <Select options={SCOPE_OPTIONS} />
            </Form.Item>
          )}
          {!isAdmin && (
            <Form.Item style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                普通用户创建个人知识库（隔离作用域，不进入公共检索与评估）。平台策展库由管理员创建。
              </Text>
            </Form.Item>
          )}
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => { setModalOpen(false); form.resetFields(); }}>{t('kb.cancel')}</Button>
              <Button type="primary" htmlType="submit" loading={creating}>{t('kb.create')}</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
};

export default KBList;
