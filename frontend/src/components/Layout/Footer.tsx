import React from 'react';
import { Layout, Typography } from 'antd';

const { Text } = Typography;

const AppFooter: React.FC = () => {
  return (
    <Layout.Footer
      style={{
        textAlign: 'center',
        background: '#fafafa',
        borderTop: '1px solid #f0f0f0',
        padding: '12px 16px',
      }}
    >
      <Text type="secondary" style={{ fontSize: 13 }}>
        CodeRAG &copy; {new Date().getFullYear()} &mdash; Intelligent Code Analysis Platform
      </Text>
    </Layout.Footer>
  );
};

export default AppFooter;
