import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout, Avatar, Dropdown, Typography, Space, Button, theme } from 'antd';
import type { MenuProps } from 'antd';
import {
  UserOutlined,
  LogoutOutlined,
  SettingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  BellOutlined,
  MenuOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '@/stores/authStore';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;

interface AppHeaderProps {
  collapsed: boolean;
  onToggle: () => void;
  isMobile?: boolean;
  onMenuClick?: () => void;
}

const AppHeader: React.FC<AppHeaderProps> = ({ collapsed, onToggle, isMobile = false, onMenuClick }) => {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const { t, i18n } = useTranslation();
  const { token } = theme.useToken();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const toggleLanguage = () => {
    const nextLang = i18n.language === 'zh' ? 'en' : 'zh';
    i18n.changeLanguage(nextLang);
  };

  const dropdownItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: t('header.profile'),
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: t('header.settings'),
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: t('header.logout'),
      danger: true,
      onClick: handleLogout,
    },
  ];

  return (
    <Layout.Header
      style={{
        background: token.colorBgContainer,
        padding: isMobile ? '0 8px' : '0 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid #f0f0f0',
        height: 56,
        lineHeight: '56px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <Button
          type="text"
          icon={isMobile ? <MenuOutlined /> : (collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />)}
          onClick={isMobile ? onMenuClick : onToggle}
          style={{ fontSize: 16, width: 40, height: 40 }}
        />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? 4 : 16 }}>
        {!isMobile && (
          <Button
            type="text"
            icon={<BellOutlined />}
            title={t('header.notifications')}
            style={{ fontSize: 16, width: 40, height: 40 }}
          />
        )}

        {!isMobile && (
          <Button type="text" onClick={toggleLanguage}>
            {t('language.switch')}
          </Button>
        )}

        <Dropdown menu={{ items: dropdownItems }} placement="bottomRight">
          <Space
            style={{ cursor: 'pointer', padding: '4px 8px', borderRadius: 6 }}
          >
            <Avatar
              size="small"
              icon={<UserOutlined />}
              style={{ backgroundColor: token.colorPrimary }}
            />
            {!isMobile && <Text>{user?.username ?? 'User'}</Text>}
          </Space>
        </Dropdown>
      </div>
    </Layout.Header>
  );
};

export default AppHeader;
