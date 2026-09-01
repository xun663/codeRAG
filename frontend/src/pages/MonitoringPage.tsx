import React, { useEffect, useState } from 'react';
import {
  Row, Col, Card, Statistic, Typography, Space, Alert, Table, Tag,
} from 'antd';
import {
  ApiOutlined, ClockCircleOutlined, CheckCircleOutlined, WarningOutlined,
  DatabaseOutlined, LineChartOutlined, FundOutlined, StarOutlined,
} from '@ant-design/icons';
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, PieChart, Pie,
  Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { useTranslation } from 'react-i18next';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { getDashboard, DashboardSummary, KBStorageItem } from '@/api/monitoring';

const { Title, Text } = Typography;

const STATUS_COLORS: Record<string, string> = {
  ok: '#52c41a',
  degraded: '#faad14',
  error: '#ff4d4f',
};

const PIE_COLORS = ['#1677ff', '#52c41a', '#faad14', '#eb2f96', '#722ed1', '#13c2c2', '#fa8c16'];

const MonitoringPage: React.FC = () => {
  const { t } = useTranslation();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getDashboard()
      .then((d) => { if (mounted) setData(d); })
      .catch((e) => { if (mounted) setError(e?.message || t('monitoring.loadFailed')); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [t]);

  if (loading) return <LoadingSpinner tip={t('common.loading')} />;
  if (error || !data) {
    return (
      <Card>
        <Alert type="error" showIcon message={error || t('monitoring.loadFailed')} />
      </Card>
    );
  }

  const health = data.system_health;
  const checks = Object.entries(health.checks || {});
  const models = (data.models || []).map((m) => ({
    name: m.model || m.provider || 'unknown',
    value: m.count,
  }));
  const ratings = Object.entries(data.ratings?.distribution || {}).map(([k, v]) => ({
    name: `${k}★`,
    count: v,
  }));
  const trend = (data.recent_activity || []).map((a) => ({ time: a.hour, count: a.count }));

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={3} style={{ margin: 0 }}>{t('monitoring.title')}</Title>
        <Text type="secondary">{t('monitoring.subtitle')}</Text>
      </div>

      {/* ── Row 1: Health KPIs ── */}
      <Row gutter={[16, 16]}>
        {checks.map(([name, check]) => {
          const ok = check.status === 'ok';
          const color = STATUS_COLORS[check.status] || '#ff4d4f';
          const label = {
            database: t('monitoring.database'),
            redis: t('monitoring.redis'),
            chromadb: t('monitoring.chromadb'),
          }[name] || name;
          return (
            <Col xs={24} sm={12} lg={8} key={name}>
              <Card>
                <Statistic
                  title={`${label}`}
                  value={ok ? t('monitoring.healthy') : (check.status === 'degraded' ? t('monitoring.degraded') : t('monitoring.unhealthy'))}
                  valueStyle={{ color }}
                  prefix={ok ? <CheckCircleOutlined /> : <WarningOutlined />}
                />
              </Card>
            </Col>
          );
        })}
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title={t('monitoring.apiRequests')}
              value={data.latency?.total_requests || 0}
              prefix={<ApiOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* ── Row 2: Usage summary ── */}
      <Row gutter={[16, 16]}>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small"><Statistic title={t('monitoring.totalConversations')} value={data.usage?.total_conversations || 0} /></Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small"><Statistic title={t('monitoring.totalMessages')} value={data.usage?.total_messages || 0} /></Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small"><Statistic title={t('monitoring.totalUsers')} value={data.usage?.total_users || 0} /></Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small"><Statistic title={t('monitoring.totalKBs')} value={data.usage?.total_kbs || 0} /></Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small"><Statistic title={t('monitoring.totalDocuments')} value={data.usage?.total_documents || 0} /></Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small"><Statistic title={t('monitoring.totalChunks')} value={(data.kb_storage || []).reduce((s, k) => s + k.chunks, 0)} /></Card>
        </Col>
      </Row>

      {/* ── Row 3: Trend + Model distribution ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title={<span><LineChartOutlined /> {t('monitoring.messageTrend')}</span>}>
            {trend.length === 0 ? (
              <Text type="secondary">{t('monitoring.noModels')}</Text>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={trend}>
                  <defs>
                    <linearGradient id="msgGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#1677ff" stopOpacity={0.8} />
                      <stop offset="95%" stopColor="#1677ff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" fontSize={10} interval={3} />
                  <YAxis allowDecimals={false} fontSize={11} />
                  <Tooltip />
                  <Area type="monotone" dataKey="count" stroke="#1677ff" fill="url(#msgGrad)" name={t('monitoring.totalMessages')} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title={<span><FundOutlined /> {t('monitoring.modelDistribution')}</span>}>
            {models.length === 0 ? (
              <Text type="secondary">{t('monitoring.noModels')}</Text>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={models} dataKey="value" nameKey="name" outerRadius={90} label={(e) => `${e.name}: ${e.value}`}>
                    {models.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── Row 4: KB storage + ratings ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title={<span><DatabaseOutlined /> {t('monitoring.kbStorage')}</span>}>
            <Table<KBStorageItem>
              size="small"
              rowKey="name"
              pagination={false}
              dataSource={data.kb_storage || []}
              columns={[
                { title: t('monitoring.totalKBs'), dataIndex: 'name', render: (n) => <Tag color="blue">{n}</Tag> },
                { title: t('monitoring.docs'), dataIndex: 'docs', align: 'right' },
                { title: t('monitoring.totalChunks'), dataIndex: 'chunks', align: 'right' },
                { title: t('monitoring.vectordbChunks'), dataIndex: 'vectordb_chunks', align: 'right' },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title={<span><StarOutlined /> {t('monitoring.ratingDistribution')}</span>}>
            {ratings.length === 0 ? (
              <Text type="secondary">{t('monitoring.noRatings')}</Text>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={ratings}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#faad14" name={t('monitoring.totalMessages')} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── Row 5: Latency + tokens ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title={<span><ClockCircleOutlined /> {t('monitoring.latency')}</span>}>
            <Row gutter={[16, 16]}>
              <Col span={8}><Statistic title={t('monitoring.avgMs')} value={data.latency?.avg_ms || 0} suffix="ms" precision={1} /></Col>
              <Col span={8}><Statistic title={t('monitoring.minMs')} value={data.latency?.min_ms || 0} suffix="ms" /></Col>
              <Col span={8}><Statistic title={t('monitoring.maxMs')} value={data.latency?.max_ms || 0} suffix="ms" /></Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title={<span><ApiOutlined /> {t('monitoring.tokenUsage')}</span>}>
            <Row gutter={[16, 16]}>
              <Col span={8}><Statistic title={t('monitoring.totalPromptTokens')} value={data.tokens?.total_prompt || 0} /></Col>
              <Col span={8}><Statistic title={t('monitoring.totalCompletionTokens')} value={data.tokens?.total_completion || 0} /></Col>
              <Col span={8}><Statistic title={t('monitoring.avgTokensPerReq')} value={data.tokens?.avg_per_request || 0} /></Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </Space>
  );
};

export default MonitoringPage;
