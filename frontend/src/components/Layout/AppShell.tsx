import React, { useState } from 'react';
import { Layout, Drawer } from 'antd';
import Sidebar from './Sidebar';
import AppHeader from './Header';
import AppFooter from './Footer';
import { useIsMobile } from '@/hooks/useIsMobile';

const { Sider, Content } = Layout;

interface AppShellProps {
  children?: React.ReactNode;
}

const AppShell: React.FC<AppShellProps> = ({ children }) => {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isMobile = useIsMobile();

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 桌面端：固定 Sider；移动端：隐藏，改用 Drawer */}
      {!isMobile && (
        <Sider
          trigger={null}
          collapsible
          collapsed={collapsed}
          width={240}
          style={{
            borderRight: '1px solid #f0f0f0',
            background: '#ffffff',
            overflow: 'auto',
          }}
        >
          <Sidebar />
        </Sider>
      )}
      <Layout>
        <AppHeader
          collapsed={collapsed}
          isMobile={isMobile}
          onToggle={() => setCollapsed(!collapsed)}
          onMenuClick={() => setDrawerOpen(true)}
        />
        <Content
          style={{
            margin: 0,
            padding: isMobile ? 12 : 24,
            minHeight: 280,
            background: '#f5f5f5',
            overflow: 'auto',
          }}
        >
          {children}
        </Content>
        <AppFooter />
      </Layout>
      {isMobile && (
        <Drawer
          placement="left"
          width={240}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          styles={{ body: { padding: 0, height: '100%' } }}
        >
          <Sidebar />
        </Drawer>
      )}
    </Layout>
  );
};

export default AppShell;
