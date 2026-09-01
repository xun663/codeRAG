import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Typography, Space, Tag, Tooltip, App, Modal, Divider } from 'antd';
import { ReloadOutlined, ThunderboltOutlined, RobotOutlined } from '@ant-design/icons';
import * as kbsApi from '@/api/kbs';
import LoadingSpinner from '@/components/common/LoadingSpinner';

const { Title, Text } = Typography;

const STATUS_META: Record<string, { color: string; label: string }> = {
  verified: { color: 'green', label: '✅ 已通过' },
  unverified: { color: 'red', label: '❌ 未达标' },
  no_qa_data: { color: 'orange', label: '无评估数据' },
  not_checked: { color: 'default', label: '未检测' },
  PASS: { color: 'green', label: '✅ 自动通过' },
  WARN: { color: 'orange', label: '⚠️ 自动预警' },
  FAIL: { color: 'red', label: '❌ 自动未过' },
};

interface RowItem extends kbsApi.KBQualityReportItem {}

const QualityReportPage: React.FC = () => {
  const { message } = App.useApp();
  const [items, setItems] = useState<RowItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [gating, setGating] = useState<string | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [autoReport, setAutoReport] = useState<kbsApi.QualityCheckTaskStatus['result'] | null>(null);

  const fetchReport = useCallback(async () => {
    try {
      setLoading(true);
      const data = await kbsApi.qualityReport();
      setItems(data);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载质量报告失败');
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const handleRunGate = async (kbId: string) => {
    try {
      setGating(kbId);
      const result = await kbsApi.runQualityGate(kbId);
      message.success(`门禁完成: ${result.status}（doc_hit=${result.metrics.avg_doc_hit_at_5}, context_recall=${result.metrics.avg_chunk_recall_at_5}）`);
      await fetchReport();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '门禁运行失败');
    } finally {
      setGating(null);
    }
  };

  // 自动体检：无需人工 GT，提交后轮询任务，完成后弹窗展示报告
  const handleAutoCheck = async (kbId: string) => {
    setChecking(kbId);
    try {
      const { task_id } = await kbsApi.runQualityCheck(kbId);
      message.info('自动体检已提交（随机采样文档自动出题），约 3-7 分钟...');
      for (let i = 0; i < 70; i++) {  // 70 × 10s = ~11 分钟上限
        await new Promise((r) => setTimeout(r, 10000));
        const t = await kbsApi.getQualityCheckTask(task_id);
        if (t.status === 'SUCCESS') {
          setAutoReport(t.result);
          await fetchReport();
          break;
        }
        if (t.status === 'FAILURE') {
          message.error(`自动体检失败: ${t.error || ''}`);
          break;
        }
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '自动体检提交失败');
    } finally {
      setChecking(null);
    }
  };

  if (loading && items.length === 0) return <LoadingSpinner />;

  const columns = [
    {
      title: '知识库',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, row: RowItem) => (
        <Space size={6}>
          <Text strong>{name}</Text>
          <Tag color={row.scope === 'platform' ? 'blue' : 'default'} style={{ marginInlineEnd: 0 }}>
            {row.scope === 'platform' ? '平台' : '个人'}
          </Tag>
          <Tag color={row.visibility === 'public' ? 'green' : 'default'} style={{ marginInlineEnd: 0 }}>
            {row.visibility}
          </Tag>
        </Space>
      ),
    },
    {
      title: '质量状态',
      dataIndex: 'quality_status',
      key: 'quality_status',
      width: 120,
      render: (s: string) => (
        <Tag color={STATUS_META[s]?.color || 'default'}>{STATUS_META[s]?.label || s}</Tag>
      ),
    },
    {
      title: '语料规模',
      key: 'corpus',
      width: 110,
      render: (_: unknown, row: RowItem) => `${row.doc_count} 文档 / ${row.chunk_count} 分块`,
    },
    {
      title: '清洗',
      key: 'cleaning',
      width: 140,
      render: (_: unknown, row: RowItem) => (
        <Tooltip title={`${row.cleaning.docs_with_cleaning} 篇文档参与清洗，移除 ${row.cleaning.removed_chars.toLocaleString()} 字符`}>
          <Text>
            {row.cleaning.removed_pct !== undefined ? `移除 ${row.cleaning.removed_pct}%` : '—'}
            <Text type="secondary" style={{ fontSize: 12 }}> / {row.cleaning.docs_with_cleaning} 篇</Text>
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '分块质量',
      key: 'chunk_stats',
      width: 170,
      render: (_: unknown, row: RowItem) => {
        const dist = row.chunk_stats.chunk_type_distribution || {};
        const summary = Object.entries(dist).map(([k, v]) => `${k}:${v}`).join(' | ');
        return (
          <Tooltip title={summary || '无分块'}>
            <Text>{row.chunk_stats.avg_tokens_per_chunk} tokens/chunk</Text>
          </Tooltip>
        );
      },
    },
    {
      title: '门禁指标',
      key: 'gate',
      width: 210,
      render: (_: unknown, row: RowItem) => {
        const m = row.gate?.metrics;
        if (!m) return <Text type="secondary">未运行</Text>;
        const isAuto = row.gate?.mode === 'auto';
        const qCount = isAuto ? (row.gate?.total_qa ?? 0) : (row.gate?.doc_level_pairs ?? 0);
        return (
          <Space direction="vertical" size={0}>
            {isAuto && row.gate?.quality_score !== undefined && (
              <Text style={{ fontSize: 12 }}>
                质量分: <Text strong>{row.gate.quality_score}</Text>（自动）
              </Text>
            )}
            <Text style={{ fontSize: 12 }}>doc_hit@5: <Text strong>{m.avg_doc_hit_at_5}</Text>（门槛 0.9）</Text>
            <Text style={{ fontSize: 12 }}>context_recall@5: <Text strong>{m.avg_chunk_recall_at_5 ?? '—'}</Text>（门槛 0.6）</Text>
            <Text style={{ fontSize: 12 }} type="secondary">MRR: {m.avg_doc_mrr} · {qCount} 题</Text>
          </Space>
        );
      },
    },
    {
      title: '最近检测',
      dataIndex: ['gate', 'run_at'],
      key: 'run_at',
      width: 160,
      render: (runAt: string | undefined) =>
        runAt ? <Text type="secondary" style={{ fontSize: 12 }}>{runAt.slice(0, 19).replace('T', ' ')}</Text> : '—',
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, row: RowItem) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={gating === row.kb_id}
            onClick={() => handleRunGate(row.kb_id)}
          >
            运行门禁
          </Button>
          <Button
            size="small"
            icon={<RobotOutlined />}
            loading={checking === row.kb_id}
            onClick={() => handleAutoCheck(row.kb_id)}
            title="无需人工 GT，随机采样自动出题评估检索质量"
          >
            自动体检
          </Button>
        </Space>
      ),
    },
  ];

  const autoReportReport = autoReport?.report;
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>知识库质量报告</Title>
          <Text type="secondary">
            检索质量负责人视图：每个知识库的清洗、分块、门禁指标聚合。门禁通过（doc_hit ≥ 0.9 且 context_recall ≥ 0.6）才可发布为平台库；「自动体检」无需人工 GT，随机采样自动出题评估任意知识库。
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchReport} loading={loading}>
          刷新
        </Button>
      </div>
      <Table<RowItem>
        rowKey="kb_id"
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={false}
        size="middle"
        scroll={{ x: 'max-content' }}
      />

      {/* 自动体检结果 */}
      <Modal
        title="自动体检报告（无需人工 GT）"
        open={!!autoReportReport}
        onCancel={() => setAutoReport(null)}
        footer={<Button type="primary" onClick={() => setAutoReport(null)}>知道了</Button>}
        width={640}
      >
        {autoReportReport && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Space size={12}>
              <Text strong style={{ fontSize: 16 }}>
                质量分: {autoReportReport.quality_score}
              </Text>
              <Tag color={STATUS_META[autoReportReport.status || '']?.color || 'default'}>
                {STATUS_META[autoReportReport.status || '']?.label || autoReportReport.status}
              </Tag>
              <Text type="secondary">{autoReportReport.total_qa} 题 · {autoReportReport.rounds} 轮</Text>
            </Space>
            <Space direction="vertical" size={0}>
              <Text>doc_hit@5: <Text strong>{autoReportReport.avg_metrics?.doc_hit}</Text>（门槛 0.6 硬线）</Text>
              <Text>context_recall@5: <Text strong>{autoReportReport.avg_metrics?.context_recall}</Text>（门槛 0.5 硬线）</Text>
              <Text type="secondary">MRR: {autoReportReport.avg_metrics?.mrr} · NDCG: {autoReportReport.avg_metrics?.ndcg}</Text>
            </Space>
            {autoReportReport.per_round && (
              <>
                <Divider style={{ margin: '4px 0' }} />
                <Text strong>各轮次</Text>
                {autoReportReport.per_round.map((r) => (
                  <Text key={r.round} style={{ fontSize: 12, display: 'block' }}>
                    第 {r.round} 轮：doc_hit {r.avg_doc_hit} · context_recall {r.avg_context_recall} · {r.n} 题
                  </Text>
                ))}
              </>
            )}
            {(autoReportReport.suggestions?.length ?? 0) > 0 && (
              <>
                <Divider style={{ margin: '4px 0' }} />
                <Text strong>诊断建议</Text>
                {autoReportReport.suggestions?.map((s, i) => (
                  <Text key={i} style={{ fontSize: 12, display: 'block' }}>• {s}</Text>
                ))}
              </>
            )}
          </Space>
        )}
      </Modal>
    </Space>
  );
};

export default QualityReportPage;
