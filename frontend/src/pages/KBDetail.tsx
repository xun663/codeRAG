import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Tabs, Card, Typography, Space, Button, Descriptions, Empty, Table, Tag,
  Form, Input, Upload, App, Popconfirm, Statistic, Row, Col, Select, List, Divider,
} from 'antd';
import {
  ArrowLeftOutlined, FileTextOutlined, SettingOutlined, TeamOutlined,
  UploadOutlined, DeleteOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import * as kbsApi from '@/api/kbs';
import * as usersApi from '@/api/users';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useAuthStore } from '@/stores/authStore';

const { Title, Text } = Typography;

const DOCUMENT_STATUS_COLORS: Record<string, string> = {
  pending: 'default', processing: 'processing', indexed: 'success',
  failed: 'error', completed: 'success',
};

const KBDetail: React.FC = () => {
  const { message } = App.useApp();
  const { t } = useTranslation();
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const { user } = useAuthStore();

  // 修改权限：官方库（platform 标签）仅 admin 可改（上传/删除/编辑）；个人库可改（后端按 owner/写权限兜底）
  const [kb, setKb] = useState<kbsApi.KBResponse | null>(null);
  const [stats, setStats] = useState<kbsApi.KBStatsResponse | null>(null);
  const [documents, setDocuments] = useState<kbsApi.DocumentResponse[]>([]);
  const [loadingKB, setLoadingKB] = useState(true);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('documents');
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editForm] = Form.useForm();

  // ── 成员管理状态 ──
  const [members, setMembers] = useState<kbsApi.KBMember[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [memberSearch, setMemberSearch] = useState('');
  const [memberResults, setMemberResults] = useState<usersApi.UserInfo[]>([]);
  const [addingMember, setAddingMember] = useState(false);

  const fetchKB = async () => {
    if (!kbId) return;
    try {
      setLoadingKB(true); setError(null);
      const [kbData, statsData] = await Promise.all([
        kbsApi.getKB(kbId),
        kbsApi.getKBStats(kbId).catch(() => null),
      ]);
      setKb(kbData); setStats(statsData);
      editForm.setFieldsValue({ name: kbData.name, description: kbData.description, kb_type: kbData.kb_type, visibility: kbData.visibility });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('kb.loadFailed');
      setError(msg);
      message.error(t('kb.loadFailed'));
    } finally { setLoadingKB(false); }
  };

  const fetchDocuments = async () => {
    if (!kbId) return;
    try {
      setLoadingDocs(true);
      const result = await kbsApi.listDocuments(kbId, { page: 1, pageSize: 100 });
      setDocuments(result.items || []);
    } catch { message.error(t('kb.loadFailed')); }
    finally { setLoadingDocs(false); }
  };

  useEffect(() => { fetchKB(); }, [kbId]);
  useEffect(() => { if (activeTab === 'documents' && kb) fetchDocuments(); }, [activeTab, kb?.id]);
  useEffect(() => { if (activeTab === 'members' && kb) fetchMembers(); }, [activeTab, kb?.id]);

  // ── 成员管理 handlers ──
  const fetchMembers = async () => {
    if (!kbId) return;
    try {
      setLoadingMembers(true);
      const ms = await kbsApi.listMembers(kbId);
      setMembers(ms);
    } catch { /* 无权限等静默 */ }
    finally { setLoadingMembers(false); }
  };

  const handleSearchUsers = async (q: string) => {
    setMemberSearch(q);
    if (!q.trim()) { setMemberResults([]); return; }
    try {
      const res = await usersApi.searchUsers(q.trim());
      const existing = new Set(members.map((m) => m.user_id));
      setMemberResults(res.filter((u) => !existing.has(u.id)));
    } catch { setMemberResults([]); }
  };

  const handleAddMember = async (userId: string) => {
    if (!kbId) return;
    setAddingMember(true);
    try {
      await kbsApi.addMember(kbId, { user_id: userId, permission: 'read' });
      message.success('已分享给该用户');
      setMemberSearch('');
      setMemberResults([]);
      await fetchMembers();
    } catch { message.error('添加成员失败'); }
    finally { setAddingMember(false); }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!kbId) return;
    try {
      await kbsApi.removeMember(kbId, userId);
      message.success('已移除成员');
      await fetchMembers();
    } catch { message.error('移除成员失败'); }
  };

  const CleaningSummary = ({ doc }: { doc: kbsApi.DocumentResponse }) => {
    const cleaning = doc.metadata_json?.cleaning as Record<string, unknown> | undefined;
    if (!cleaning || !cleaning.enabled) return null;
    return (
      <div style={{ padding: '8px 0', fontSize: 13 }}>
        <Text type="secondary">
          {t('kb.cleaningSummary', {
            before: cleaning.before_chars as number,
            after: cleaning.after_chars as number,
            pct: cleaning.removed_pct as number,
          })}
        </Text>
      </div>
    );
  };

  const pendingFilesRef = useRef<File[]>([]);

  // Ant Design beforeUpload 在 multiple 模式下逐文件同步调用，收集到当前 tick 结束后一次性批量上传
  const handleUpload = (file: File) => {
    pendingFilesRef.current.push(file);
    setTimeout(() => {
      const batch = pendingFilesRef.current.splice(0, pendingFilesRef.current.length);
      if (batch.length) uploadBatch(batch);
    }, 0);
    return false;
  };

  const uploadBatch = async (files: File[]) => {
    if (!kbId) return;
    try {
      setUploading(true);
      const results = await kbsApi.uploadDocuments(kbId, files);
      const ok = results.filter((d) => d.status === 'indexed').length;
      const failed = results.length - ok;
      if (failed) message.success(t('kb.uploadPartial', { ok, failed }));
      else message.success(t('kb.uploadSuccessCount', { count: ok }));
      fetchDocuments(); fetchKB();
    } catch { message.error(t('kb.uploadFailed')); }
    finally { setUploading(false); }
  };

  const handleDeleteDoc = async (docId: string) => {
    if (!kbId) return;
    try { await kbsApi.deleteDocument(kbId, docId); message.success(t('kb.deleteSuccess')); setDocuments((p) => p.filter((d) => d.id !== docId)); }
    catch { message.error(t('kb.deleteFailed')); }
  };

  const handleSaveSettings = async (values: Record<string, unknown>) => {
    if (!kbId) return;
    try {
      setSaving(true);
      const updated = await kbsApi.updateKB(kbId, {
        name: values.name as string,
        description: values.description as string | undefined,
        visibility: values.visibility as string | undefined,
      });
      setKb(updated);
      message.success(t('kb.saveSuccess'));
    } catch { message.error(t('kb.saveFailed')); }
    finally { setSaving(false); }
  };

  if (loadingKB) return <LoadingSpinner />;
  if (error || !kb) return <Card><Space direction="vertical"><Text type="danger">{error || t('kb.notFound')}</Text><Button onClick={() => navigate('/kbs')}>{t('kb.back')}</Button></Space></Card>;

  // 官方库（platform）仅 admin 可改；个人库登录用户可改（后端再按 owner/写权限校验）
  const canModify = user?.role === 'admin' || kb.scope !== 'platform';
  // 成员管理仅个人库（platform 已全员可见，无需成员）的 owner 可用
  const canManageMembers = kb.scope !== 'platform' && !!kb.owner_id && String(kb.owner_id) === String(user?.id);

  const docColumns = [
    { title: t('kb.tableTitle'), dataIndex: 'title', key: 'title', render: (t: string) => <Text strong>{t}</Text> },
    { title: t('kb.tableType'), dataIndex: 'source_type', key: 'source_type', width: 80 },
    { title: t('kb.tableSize'), dataIndex: 'file_size', key: 'file_size', width: 80, render: (s: number) => s ? `${(s / 1024).toFixed(1)} KB` : '-' },
    {
      title: t('kb.tableCleaning'), key: 'cleaning', width: 80, render: (_: unknown, r: kbsApi.DocumentResponse) => {
        const c = r.metadata_json?.cleaning as Record<string, unknown> | undefined;
        if (!c?.enabled) return <Text type="secondary">{t('kb.noCleaning')}</Text>;
        const pct = c.removed_pct as number;
        return <Text type={pct > 20 ? 'warning' : 'secondary'}>{pct}%</Text>;
      }
    },
    { title: t('kb.tableStatus'), dataIndex: 'status', key: 'status', width: 100, render: (s: string) => <Tag color={DOCUMENT_STATUS_COLORS[s] || 'default'}>{s}</Tag> },
    { title: t('kb.tableCreated'), dataIndex: 'created_at', key: 'created_at', width: 150, render: (d: string) => new Date(d).toLocaleString() },
    ...(canModify ? [{
      title: '', key: 'actions', width: 50, render: (_: unknown, r: kbsApi.DocumentResponse) => (
        <Popconfirm title={t('kb.confirmDelete')} onConfirm={() => handleDeleteDoc(r.id)}>
          <Button type="text" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      )
    }] : []),
  ];

  const tabs = [
    {
      key: 'documents', label: <span><FileTextOutlined /> {t('kb.documents')}</span>,
      children: (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <Text strong>{t('kb.documents')} ({documents.length})</Text>
            <Space>
              {canModify && (
                <Upload accept=".py,.js,.ts,.java,.go,.rs,.md,.txt,.json,.yaml,.yml,.xml,.html,.css" showUploadList={false} multiple
                  beforeUpload={(f) => { handleUpload(f); return false; }} disabled={uploading}>
                  <Button type="primary" icon={<UploadOutlined />} loading={uploading}>{t('kb.upload')}</Button>
                </Upload>
              )}
              <Button icon={<ReloadOutlined />} onClick={fetchDocuments}>{t('kb.refresh')}</Button>
            </Space>
          </div>
          <Table dataSource={documents} columns={docColumns} rowKey="id" loading={loadingDocs} pagination={false}
            scroll={{ x: 900 }}
            expandable={{ expandedRowRender: (r: kbsApi.DocumentResponse) => <CleaningSummary doc={r} /> }}
            locale={{ emptyText: <Empty description={t('kb.noDocuments')} /> }} />
        </Space>
      ),
    },
    {
      key: 'settings', label: <span><SettingOutlined /> {t('kb.settings')}</span>,
      children: (
        <Row gutter={[24, 24]}>
          <Col xs={24} md={12}>
            <Card title={t('kb.info')}><Descriptions column={1} bordered size="small">
              <Descriptions.Item label="ID">{kb.id}</Descriptions.Item>
              <Descriptions.Item label={t('kb.name')}>{kb.name}</Descriptions.Item>
              <Descriptions.Item label={t('kb.type')}><Tag>{kb.kb_type}</Tag></Descriptions.Item>
              <Descriptions.Item label={t('kb.description')}>{kb.description || '-'}</Descriptions.Item>
              <Descriptions.Item label={t('kb.tableCreated')}>{new Date(kb.created_at).toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label={t('common.edit')}>{new Date(kb.updated_at).toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label={t('kb.owner')}>{kb.owner_id}</Descriptions.Item>
            </Descriptions></Card>
          </Col>
          <Col xs={24} md={12}>
            <Card title={t('kb.stats')}><Row gutter={[16, 16]}>
              <Col span={12}><Statistic title={t('kb.documents')} value={stats?.doc_count || 0} prefix={<FileTextOutlined />} /></Col>
              <Col span={12}><Statistic title={t('kb.chunks')} value={stats?.chunk_count || 0} /></Col>
              <Col span={12}><Statistic title={t('kb.totalTokens')} value={stats?.total_tokens || 0} /></Col>
              <Col span={12}><Statistic title={t('kb.avgChunkSize')} value={stats?.avg_chunk_size || 0} /></Col>
            </Row></Card>
          </Col>
          {canModify ? (
            <Col xs={24}>
              <Card title={t('kb.edit')}><Form form={editForm} layout="vertical" onFinish={handleSaveSettings} style={{ maxWidth: 500 }}>
                <Form.Item name="name" label={t('kb.name')} rules={[{ required: true }]}><Input /></Form.Item>
                <Form.Item name="description" label={t('kb.description')}><Input.TextArea rows={3} /></Form.Item>
                {kb.scope === 'platform' && (
                  <Form.Item name="visibility" label="可见性"
                    tooltip="官方库默认公开；调试期可切为私有（仅管理员可见），测完切回公开。个人库固定私有，分享走成员。">
                    <Select options={[
                      { label: '私有（仅管理员）', value: 'private' },
                      { label: '公开（全员可见）', value: 'public' },
                    ]} />
                  </Form.Item>
                )}
                <Form.Item><Button type="primary" htmlType="submit" loading={saving}>{t('kb.save')}</Button></Form.Item>
              </Form></Card>
            </Col>
          ) : (
            <Col xs={24}>
              <Card title={t('kb.edit')}>
                <Text type="secondary">官方知识库仅管理员可修改，如需调整请联系管理员。</Text>
              </Card>
            </Col>
          )}
        </Row>
      ),
    },
  ];

  // 成员 tab 仅知识库所有者 / 系统 admin 可见
  if (canManageMembers) {
    tabs.push({
      key: 'members', label: <span><TeamOutlined /> {t('kb.members')}</span>,
      children: (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Text strong>添加成员（输入用户名分享知识库）</Text>
            <div style={{ marginTop: 8 }}>
              <Select
                showSearch
                allowClear
                value={memberSearch || undefined}
                placeholder="输入用户名搜索并选择..."
                filterOption={false}
                onSearch={handleSearchUsers}
                onSelect={handleAddMember}
                loading={addingMember}
                notFoundContent={memberSearch ? '未找到匹配用户' : '输入用户名开始搜索'}
                options={memberResults.map((u) => ({
                  label: u.display_name ? `${u.username} (${u.display_name})` : u.username,
                  value: u.id,
                }))}
                style={{ width: 360, maxWidth: '100%' }}
              />
            </div>
          </div>
          <Divider style={{ margin: '4px 0' }} />
          <Text strong>当前成员（{members.length}）</Text>
          {loadingMembers ? (
            <LoadingSpinner size="small" />
          ) : members.length === 0 ? (
            <Empty description="尚未共享给其他用户" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              dataSource={members}
              renderItem={(m) => (
                <List.Item
                  actions={[
                    <Popconfirm key="rm" title="确定移除该成员？" onConfirm={() => handleRemoveMember(m.user_id)}>
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<TeamOutlined style={{ color: '#1677ff' }} />}
                    title={<Text>{m.username || m.user_id}</Text>}
                    description={<Tag color="blue">{m.permission}</Tag>}
                  />
                </List.Item>
              )}
            />
          )}
        </Space>
      ),
    });
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/kbs')} type="text" />
        <div>
          <Title level={3} style={{ margin: 0 }}>{kb.name}</Title>
          <Text type="secondary">{kb.kb_type}{kb.doc_count ? t('kb.docsCount', { count: kb.doc_count }) : ''}</Text>
        </div>
      </div>
      <Card><Tabs activeKey={activeTab} onChange={setActiveTab} items={tabs} /></Card>
    </Space>
  );
};

export default KBDetail;
