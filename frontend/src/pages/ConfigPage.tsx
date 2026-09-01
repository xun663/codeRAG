import React, { useEffect, useState } from 'react';
import {
  Card, Form, Input, InputNumber, Button, Typography, Space, Tabs, Select,
  AutoComplete, App, Alert, Empty, Table, Modal, Tag, Popconfirm,
} from 'antd';
import {
  SaveOutlined, ApiOutlined, FileProtectOutlined,
  ThunderboltOutlined, PlusOutlined, DeleteOutlined, EditOutlined, CheckCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import * as configApi from '@/api/config';

const { Title, Text } = Typography;

const MODEL_OPTIONS = [
  { value: 'deepseek-v4-flash' },
  { value: 'deepseek-chat' },
  { value: 'gpt-4o-mini' },
  { value: 'gpt-4o' },
  { value: 'qwen-plus' },
  { value: 'glm-4-flash' },
];

const QWEN_EMBEDDING_BASE = 'https://dashscope.aliyuncs.com/compatible-mode/v1';

const ConfigPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [profileForm] = Form.useForm();
  const [embedForm] = Form.useForm();

  // ── LLM 配置单 ──────────────────────────────────────────────
  const [profiles, setProfiles] = useState<configApi.LLMProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<configApi.LLMProfile | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  // ── 嵌入模型配置 ────────────────────────────────────────────
  const [embedSaving, setEmbedSaving] = useState(false);

  const fetchProfiles = async () => {
    setLoading(true);
    try {
      setProfiles(await configApi.listLLMProfiles());
    } catch { message.error(t('config.loadFailed')); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchProfiles(); }, []);

  const openCreate = () => {
    setEditing(null);
    profileForm.resetFields();
    setModalOpen(true);
  };

  const openEdit = (p: configApi.LLMProfile) => {
    setEditing(p);
    profileForm.setFieldsValue({ name: p.name, base_url: p.base_url, model: p.model, api_key: undefined });
    setModalOpen(true);
  };

  const handleTest = async () => {
    const values = await profileForm.validateFields();
    setTesting(true);
    try {
      const result = await configApi.testLLM({ base_url: values.base_url, model: values.model, api_key: values.api_key });
      if (result.success) {
        message.success(result.response ? `${t('config.testSuccess')} — ${result.response}` : t('config.testSuccess'));
      } else {
        message.error(`${t('config.testFailed')}: ${result.error ?? ''}`);
      }
    } catch { message.error(t('config.testFailed')); }
    finally { setTesting(false); }
  };

  const handleSave = async () => {
    const values = await profileForm.validateFields();
    setSaving(true);
    try {
      if (editing) await configApi.updateLLMProfile(editing.id, values);
      else await configApi.createLLMProfile(values);
      message.success(t('config.saved'));
      setModalOpen(false);
      fetchProfiles();
    } catch { message.error(t('config.saveFailed')); }
    finally { setSaving(false); }
  };

  const handleActivate = async (p: configApi.LLMProfile) => {
    try {
      await configApi.activateLLMProfile(p.id);
      message.success(t('config.activated'));
      fetchProfiles();
    } catch { message.error(t('config.saveFailed')); }
  };

  const handleDelete = async (p: configApi.LLMProfile) => {
    try {
      await configApi.deleteLLMProfile(p.id);
      message.success(t('config.deleted'));
      fetchProfiles();
    } catch { message.error(t('config.deleteFailed')); }
  };

  const columns = [
    {
      title: t('config.profileName'), dataIndex: 'name', key: 'name',
      render: (v: string, r: configApi.LLMProfile) => (
        <Space>
          {v}
          {r.is_active && <Tag color="green">{t('config.active')}</Tag>}
        </Space>
      ),
    },
    { title: t('config.model'), dataIndex: 'model', key: 'model' },
    { title: t('config.baseUrl'), dataIndex: 'base_url', key: 'base_url' },
    {
      title: t('config.apiKey'), key: 'key',
      render: (_: unknown, r: configApi.LLMProfile) => (
        r.has_key ? <Tag color="blue">{t('config.keyConfigured')}</Tag> : <Tag>{t('config.keyEmpty')}</Tag>
      ),
    },
    {
      title: t('common.actions'), key: 'actions',
      render: (_: unknown, r: configApi.LLMProfile) => (
        <Space size={0}>
          {!r.is_active && (
            <Button size="small" type="link" icon={<CheckCircleOutlined />} onClick={() => handleActivate(r)}>
              {t('config.activate')}
            </Button>
          )}
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            {t('common.edit')}
          </Button>
          <Popconfirm title={t('config.confirmDelete')} onConfirm={() => handleDelete(r)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>{t('common.delete')}</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ── 嵌入模型配置 handlers ───────────────────────────────────
  useEffect(() => {
    configApi.getEmbeddingConfig()
      .then((cfg) => {
        embedForm.setFieldsValue({ provider: cfg.provider, base_url: cfg.base_url, model: cfg.model, dimension: cfg.dimension });
      })
      .catch(() => { /* 未配置则留空表单 */ });
  }, [embedForm]);

  const handleEmbedProviderChange = (provider: string) => {
    if (provider === 'local') {
      embedForm.setFieldsValue({ base_url: '', model: 'BAAI/bge-m3', dimension: 1024 });
    } else {
      embedForm.setFieldsValue({ base_url: QWEN_EMBEDDING_BASE, model: 'text-embedding-v3', dimension: 1024 });
    }
  };

  const handleEmbedSave = async () => {
    const values = await embedForm.validateFields();
    setEmbedSaving(true);
    try {
      const saved = await configApi.saveEmbeddingConfig(values);
      embedForm.setFieldsValue({ provider: saved.provider, base_url: saved.base_url, model: saved.model, dimension: saved.dimension });
      message.success(t('config.saved'));
    } catch (e: unknown) {
      const data = (e as { response?: { data?: { error?: string; detail?: string } } })?.response?.data;
      const msg = data?.error || data?.detail;
      if (msg) message.error(`${t('config.embeddingDimBlocked')}：${msg}`);
      else message.error(t('config.saveFailed'));
    }
    setEmbedSaving(false);
  };

  // ── tabs ────────────────────────────────────────────────────
  const llmTab = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert type="info" showIcon message={t('config.providerHint')} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text strong>{t('config.profiles')} ({profiles.length})</Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>{t('config.addProfile')}</Button>
      </div>
      <Table
        rowKey="id" size="small" dataSource={profiles} columns={columns} pagination={false} loading={loading}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('config.noProfiles')} /> }}
      />
      <Modal
        title={editing ? t('config.editProfile') : t('config.addProfile')}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={t('config.save')}
        cancelText={t('common.cancel')}
      >
        <Form form={profileForm} layout="vertical">
          <Form.Item label={t('config.profileName')} name="name">
            <Input placeholder={t('config.profileNamePlaceholder')} />
          </Form.Item>
          <Form.Item label={t('config.baseUrl')} name="base_url" rules={[{ required: true }]}>
            <Input placeholder="https://api.deepseek.com/v1" />
          </Form.Item>
          <Form.Item label={t('config.model')} name="model" rules={[{ required: true }]}>
            <AutoComplete
              options={MODEL_OPTIONS}
              placeholder="deepseek-v4-flash"
              filterOption={(input, option) => (option?.value ?? '').toLowerCase().includes(input.toLowerCase())}
            />
          </Form.Item>
          <Form.Item label={t('config.apiKey')} name="api_key" extra={editing ? t('config.apiKeyKeepHint') : undefined}>
            <Input.Password autoComplete="new-password" placeholder={t('config.apiKeyPlaceholder')} />
          </Form.Item>
          <Button icon={<ThunderboltOutlined />} loading={testing} onClick={handleTest}>
            {t('config.testConnection')}
          </Button>
        </Form>
      </Modal>
    </Space>
  );

  const embeddingTab = (
    <Form form={embedForm} layout="vertical" style={{ maxWidth: 600 }}>
      <Alert type="info" showIcon message={t('config.embeddingHint')} style={{ marginBottom: 16 }} />
      <Form.Item label={t('config.embeddingProvider')} name="provider" rules={[{ required: true }]}>
        <Select
          options={[
            { value: 'local', label: '本地 bge-m3' },
            { value: 'openai', label: 'OpenAI 兼容（千问/OpenAI）' },
          ]}
          onChange={handleEmbedProviderChange}
        />
      </Form.Item>
      <Form.Item label={t('config.baseUrl')} name="base_url">
        <Input placeholder={QWEN_EMBEDDING_BASE} />
      </Form.Item>
      <Form.Item label={t('config.embeddingModel')} name="model" rules={[{ required: true }]}>
        <Input placeholder="text-embedding-v3 / BAAI/bge-m3" />
      </Form.Item>
      <Form.Item label={t('config.embeddingDimension')} name="dimension" rules={[{ required: true }]}>
        <InputNumber min={64} max={4096} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item label={t('config.apiKey')} name="api_key" extra={t('config.apiKeyKeepHint')}>
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Button type="primary" icon={<SaveOutlined />} loading={embedSaving} onClick={handleEmbedSave}>
        {t('config.save')}
      </Button>
    </Form>
  );

  const tabItems = [
    {
      key: 'llm',
      label: <span><ApiOutlined /> {t('config.llm')}</span>,
      children: llmTab,
    },
    {
      key: 'embedding',
      label: <span><FileProtectOutlined /> {t('config.embedding')}</span>,
      children: embeddingTab,
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={3} style={{ margin: 0 }}>{t('config.title')}</Title>
        <Text type="secondary">{t('config.subtitle')}</Text>
      </div>
      <Card><Tabs defaultActiveKey="llm" items={tabItems} /></Card>
    </Space>
  );
};

export default ConfigPage;
