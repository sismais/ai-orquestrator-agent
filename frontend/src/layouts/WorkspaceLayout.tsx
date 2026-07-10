import { ReactNode, useEffect } from 'react';
import TopNav from '../components/Navigation/TopNav';
import styles from './WorkspaceLayout.module.css';

export type ModuleType = 'dashboard' | 'kanban' | 'chat' | 'settings';

interface WorkspaceLayoutProps {
  children: ReactNode;
  currentModule: ModuleType;
  onNavigate: (module: ModuleType) => void;
  currentProjectId: string | null;
  onProjectSwitch: (projectId: string) => void;
  pausedCount?: number;
}

const WorkspaceLayout = ({ children, currentModule, onNavigate, currentProjectId, onProjectSwitch, pausedCount = 0 }: WorkspaceLayoutProps) => {
  useWorkspaceBodyClass(currentModule);
  return (
    <div className={styles.workspace}>
      <TopNav
        currentModule={currentModule}
        onNavigate={onNavigate}
        currentProjectId={currentProjectId}
        onProjectSwitch={onProjectSwitch}
        pausedCount={pausedCount}
      />
      <main className={`${styles.content} ${currentModule === 'kanban' ? styles.kanbanContentWrapper : ''}`}>
        {children}
      </main>
    </div>
  );
};

// Add/remove body class to scope global overflow to Kanban only
// (keeps Dashboard/Settings using normal body scroll)
export function useWorkspaceBodyClass(currentModule: any) {
  useEffect(() => {
    const cls = 'kanban-mode';
    if (currentModule === 'kanban') {
      document.body.classList.add(cls);
      // enforce style directly to avoid stylesheet ordering issues
      document.body.style.overflowY = 'hidden';
    } else {
      document.body.classList.remove(cls);
      document.body.style.overflowY = '';
    }
    return () => document.body.classList.remove(cls);
  }, [currentModule]);
}

export default WorkspaceLayout;
