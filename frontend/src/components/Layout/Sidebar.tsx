import React, { useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Menu, Typography } from 'antd';
import type { MenuProps } from 'antd';
import {
  DashboardOutlined,
  BookOutlined,
  MessageOutlined,
  SettingOutlined,
  MonitorOutlined,
  TeamOutlined,
  FormOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '@/stores/authStore';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;

type MenuItem = Required<MenuProps>['items'][number];

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const { t } = useTranslation();

  const menuItems: MenuItem[] = useMemo(() => {
    const items: MenuItem[] = [
      {
        key: '/',
        icon: <DashboardOutlined />,
        label: t('nav.dashboard'),
      },
      {
        key: '/kbs',
        icon: <BookOutlined />,
        label: t('nav.knowledgeBases'),
      },
      {
        key: '/chat',
        icon: <MessageOutlined />,
        label: t('nav.chat'),
      },
      {
        type: 'divider',
      } as MenuItem,
      {
        key: '/quiz',
        icon: <FormOutlined />,
        label: '知识复习',
      },
    ];

    if (user?.role === 'admin') {
      items.push(
        {
          key: '/monitoring',
          icon: <MonitorOutlined />,
          label: t('nav.monitoring'),
        },
        {
          key: '/admin/quality',
          icon: <SafetyCertificateOutlined />,
          label: t('nav.qualityReport'),
        },
        {
          type: 'divider',
        } as MenuItem,
        {
          key: '/config',
          icon: <SettingOutlined />,
          label: t('nav.configuration'),
        },
        {
          key: '/admin/users',
          icon: <TeamOutlined />,
          label: t('nav.userManagement'),
        }
      );
    }

    return items;
  }, [user, t]);

  const selectedKey = useMemo(() => {
    const path = location.pathname;
    // Match exact or parent path
    if (path.startsWith('/chat')) return '/chat';
    if (path.startsWith('/kbs')) return '/kbs';
    if (path.startsWith('/quiz')) return '/quiz';
    return path;
  }, [location.pathname]);

  const openKeys = useMemo(() => ([] as string[]), []);

  const handleClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          padding: '16px 24px',
          borderBottom: '1px solid #f0f0f0',
        }}
      >
        <Text strong style={{ fontSize: 18, color: '#1677ff' }}>
          CodeRAG
        </Text>
      </div>
      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        defaultOpenKeys={openKeys}
        items={menuItems}
        onClick={handleClick}
        style={{ borderRight: 0, flex: 1 }}
      />
    </div>
  );
};

export default Sidebar;
