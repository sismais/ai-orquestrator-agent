import { ReactNode } from 'react';
import TopNav from '../components/Navigation/TopNav';
import styles from './WorkspaceLayout.module.css';

export type ModuleType = 'dashboard' | 'kanban' | 'chat' | 'settings';

interface WorkspaceLayoutProps {
  children: ReactNode;
  currentModule: ModuleType;
  onNavigate: (module: ModuleType) => void;
  currentProjectId: string | null;
  onProjectSwitch: (projectId: string) => void;
}

const WorkspaceLayout = ({ children, currentModule, onNavigate, currentProjectId, onProjectSwitch }: WorkspaceLayoutProps) => {
  return (
    <div className={styles.workspace}>
      <TopNav
        currentModule={currentModule}
        onNavigate={onNavigate}
        currentProjectId={currentProjectId}
        onProjectSwitch={onProjectSwitch}
      />
      <main className={styles.content}>
        {children}
      </main>
    </div>
  );
};

export default WorkspaceLayout;
