import React from 'react';
import { Spin } from 'antd';
import { LoadingOutlined } from '@ant-design/icons';

interface LoadingSpinnerProps {
  tip?: string;
  fullPage?: boolean;
  size?: 'small' | 'default' | 'large';
}

const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({
  tip = 'Loading...',
  fullPage = false,
  size = 'large',
}) => {
  const indicator = <LoadingOutlined spin />;

  const spinner = (
    <Spin
      indicator={indicator}
      tip={tip}
      size={size}
      style={{ width: '100%', padding: '48px 0' }}
    />
  );

  if (fullPage) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: '100vh',
          width: '100%',
        }}
      >
        {spinner}
      </div>
    );
  }

  return (
    <div style={{ textAlign: 'center', padding: '48px 0' }}>
      {spinner}
    </div>
  );
};

export default LoadingSpinner;
