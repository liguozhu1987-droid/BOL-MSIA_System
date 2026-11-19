import { createBrowserRouter, Navigate } from 'react-router-dom';
import MainLayout from '@/layouts/MainLayout';
import AuthRoute from '@/components/AuthRoute';
import Login from '@/pages/Login';
import OidcCallback from '@/pages/OidcCallback';
import Dashboard from '@/pages/Dashboard';
import Workbench from '@/pages/Workbench';
import Projects from '@/pages/Projects';
import ProjectDetail from '@/pages/ProjectDetail';
import PhaseReview from '@/pages/PhaseReview';
import Issues from '@/pages/Issues';
import Checklist from '@/pages/Checklist';
import MsiaPlan from '@/pages/MsiaPlan';
import SystemUsers from '@/pages/SystemUsers';
import Notifications from '@/pages/Notifications';
import Escalation from '@/pages/Escalation';
import Archive from '@/pages/Archive';
import ArchiveDetail from '@/pages/ArchiveDetail';
import HistoricScore from '@/pages/HistoricScore';
import SystemSettings from '@/pages/SystemSettings';
import NotFound from '@/pages/NotFound';

// 路由定义：登录页单独挂载，其余路由经 AuthRoute 鉴权 + MainLayout 布局
export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    // OIDC 回调页 (公开): 后端 302 到此并带 ?otk= 一次性码, 换取本地 JWT 后进看板
    path: '/oidc/callback',
    element: <OidcCallback />,
  },
  {
    element: <AuthRoute />,
    children: [
      {
        element: <MainLayout />,
        children: [
          { path: '/', element: <Navigate to="/dashboard" replace /> },
          { path: '/dashboard', element: <Dashboard /> },
          { path: '/workbench', element: <Workbench /> },
          { path: '/msia-plan', element: <MsiaPlan /> },
          { path: '/projects', element: <Projects /> },
          { path: '/projects/:id', element: <ProjectDetail /> },
          { path: '/projects/:id/phases/:phaseId', element: <PhaseReview /> },
          { path: '/issues', element: <Issues /> },
          { path: '/checklist', element: <Checklist /> },
          { path: '/escalation', element: <Escalation /> },
          { path: '/archive', element: <Archive /> },
          { path: '/archive/:id', element: <ArchiveDetail /> },
          { path: '/notifications', element: <Notifications /> },
          { path: '/system/users', element: <SystemUsers /> },
          { path: '/historic-score', element: <HistoricScore /> },
          { path: '/system/settings', element: <SystemSettings /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
]);
