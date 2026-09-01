import React, { useState, useEffect } from 'react';
import { Row, Col, Card, Statistic, Typography, Space, List, Tag, Button, App } from 'antd';
import { BookOutlined, FileTextOutlined, MessageOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import * as kbsApi from '@/api/kbs';
import * as chatApi from '@/api/chat';
import LoadingSpinner from '@/components/common/LoadingSpinner';

const { Title, Text } = Typography;

const Dashboard: React.FC = () => {
  const { message } = App.useApp();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [kbs, setKbs] = useState<kbsApi.KBResponse[]>([]);
  const [convCount, setConvCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);
        const [kbResult, convResult] = await Promise.all([
          kbsApi.listKBs({ page: 1, pageSize: 100 }),
          chatApi.listConversations({ page: 1, pageSize: 100 }),
        ]);
        setKbs(kbResult.items || []);
        setConvCount(convResult.total || 0);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : t('dashboard.loadFailed', 'Failed to load dashboard');
        setError(msg);
        message.error(msg);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [t]);

  if (loading) return <LoadingSpinner />;
  if (error) return <Card><Text type="danger">{error}</Text></Card>;

  const docCount = kbs.reduce((sum, kb) => sum + (kb.doc_count || 0), 0);
  const recentKBs = [...kbs]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={3} style={{ margin: 0 }}>{t('dashboard.title')}</Title>
        <Typography.Text type="secondary">{t('dashboard.welcome')}</Typography.Text>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/kbs')} style={{ cursor: 'pointer' }}>
            <Statistic title={t('dashboard.knowledgeBases')} value={kbs.length} prefix={<BookOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title={t('dashboard.documents')} value={docCount} prefix={<FileTextOutlined />} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/chat')} style={{ cursor: 'pointer' }}>
            <Statistic title={t('dashboard.conversations')} value={convCount} prefix={<MessageOutlined />} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card title={t('dashboard.recentActivity')}>
            {recentKBs.length === 0 ? (
              <Text type="secondary">{t('dashboard.noActivity')}</Text>
            ) : (
              <List
                dataSource={recentKBs}
                renderItem={(kb) => (
                  <List.Item onClick={() => navigate(`/kbs/${kb.id}`)} style={{ cursor: 'pointer' }}
                    extra={<Tag>{kb.kb_type}</Tag>}>
                    <List.Item.Meta title={kb.name} description={kb.description || t('dashboard.noDescription')} />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={t('dashboard.quickActions')}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text type="secondary">{t('dashboard.quickActionsHint')}</Text>
              <Button type="primary" block onClick={() => navigate('/kbs')}>{t('dashboard.goToKBs')}</Button>
              <Button block onClick={() => navigate('/chat')}>{t('dashboard.startChat')}</Button>
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  );
};

export default Dashboard;
