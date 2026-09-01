/**
 * Route configuration metadata.
 * Used for navigation menus, breadcrumbs, and permission checks.
 */
export interface RouteConfig {
  path: string;
  label: string;
  icon?: string;
  requiredRole?: string;
  showInSidebar?: boolean;
  children?: RouteConfig[];
}

const routeConfigs: RouteConfig[] = [
  {
    path: '/',
    label: 'Dashboard',
    icon: 'DashboardOutlined',
    showInSidebar: true,
  },
  {
    path: '/login',
    label: 'Login',
    showInSidebar: false,
  },
  {
    path: '/register',
    label: 'Register',
    showInSidebar: false,
  },
  {
    path: '/kbs',
    label: 'Knowledge Bases',
    icon: 'BookOutlined',
    showInSidebar: true,
  },
  {
    path: '/kbs/:kbId',
    label: 'Knowledge Base Detail',
    showInSidebar: false,
  },
  {
    path: '/kbs/:kbId/documents/:docId',
    label: 'Document Detail',
    showInSidebar: false,
  },
  {
    path: '/chat',
    label: 'Chat',
    icon: 'MessageOutlined',
    showInSidebar: true,
  },
  {
    path: '/chat/:convId',
    label: 'Chat',
    showInSidebar: false,
  },
  {
    path: '/config',
    label: 'Configuration',
    icon: 'SettingOutlined',
    showInSidebar: true,
    requiredRole: 'admin',
  },
  {
    path: '/monitoring',
    label: 'Monitoring',
    icon: 'MonitorOutlined',
    showInSidebar: true,
    requiredRole: 'admin',
  },
  {
    path: '/admin/users',
    label: 'User Management',
    icon: 'TeamOutlined',
    showInSidebar: true,
    requiredRole: 'admin',
  },
];

export default routeConfigs;
