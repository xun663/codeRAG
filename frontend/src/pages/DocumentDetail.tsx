import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Typography, Space, Button, Tag, Empty, Descriptions } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

const { Title, Text } = Typography;

const DocumentDetail: React.FC = () => {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/kbs/${kbId}`)} type="text" />
        <div>
          <Title level={3} style={{ margin: 0 }}>{t('document.title')}</Title>
          <Text type="secondary">{t('document.subtitle', { kbId, docId })}</Text>
        </div>
      </div>

      <Card title={t('document.info')}>
        <Descriptions column={2}>
          <Descriptions.Item label={t('document.fieldName')}>--</Descriptions.Item>
          <Descriptions.Item label={t('document.fieldStatus')}><Tag>pending</Tag></Descriptions.Item>
          <Descriptions.Item label={t('document.fieldSize')}>--</Descriptions.Item>
          <Descriptions.Item label={t('document.fieldType')}>--</Descriptions.Item>
          <Descriptions.Item label={t('document.fieldUploaded')}>--</Descriptions.Item>
          <Descriptions.Item label={t('document.fieldChunks')}>0</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title={t('document.chunks')}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('document.noChunks')} />
      </Card>
    </Space>
  );
};

export default DocumentDetail;
