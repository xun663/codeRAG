import React from 'react';
import { Card, Typography, Space, Table, Button, Tag, Avatar, Empty } from 'antd';
import { PlusOutlined, UserOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

const { Title, Text } = Typography;

const AdminUsers: React.FC = () => {
  const { t } = useTranslation();

  const columns = [
    {
      title: t('admin.tableUser'),
      dataIndex: 'username',
      key: 'username',
      render: (username: string, record: { avatar?: string }) => (
        <Space>
          <Avatar src={record.avatar} icon={<UserOutlined />} size="small" />
          <Text>{username}</Text>
        </Space>
      ),
    },
    {
      title: t('admin.tableEmail'),
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: t('admin.tableRole'),
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => {
        const colorMap: Record<string, string> = { admin: 'red', user: 'blue', viewer: 'default' };
        return <Tag color={colorMap[role] ?? 'default'}>{role}</Tag>;
      },
    },
    {
      title: t('admin.tableCreated'),
      dataIndex: 'createdAt',
      key: 'createdAt',
    },
    {
      title: t('admin.tableActions'),
      key: 'actions',
      render: () => (
        <Space>
          <Button type="link">{t('admin.edit')}</Button>
          <Button type="link" danger>{t('admin.disable')}</Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>{t('admin.title')}</Title>
          <Text type="secondary">{t('admin.subtitle')}</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />}>{t('admin.addUser')}</Button>
      </div>
      <Card>
        <Table
          dataSource={[]}
          columns={columns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('admin.noUsers')}>
            <Button type="primary" icon={<PlusOutlined />}>{t('admin.addUser')}</Button>
          </Empty> }}
          pagination={{ pageSize: 20 }}
        />
      </Card>
    </Space>
  );
};

export default AdminUsers;
