import React from 'react';
import { Button, Result } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

const NotFound: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#f0f2f5' }}>
      <Result
        status="404"
        title={t('notFound.title')}
        subTitle={t('notFound.subtitle')}
        extra={[
          <Button type="primary" key="home" onClick={() => navigate('/')}>{t('notFound.backToDashboard')}</Button>,
          <Button key="back" onClick={() => navigate(-1)}>{t('notFound.goBack')}</Button>,
        ]}
      />
    </div>
  );
};

export default NotFound;
