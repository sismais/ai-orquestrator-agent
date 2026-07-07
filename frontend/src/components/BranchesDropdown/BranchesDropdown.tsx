import React, { useState, useEffect, useRef } from 'react';
import styles from './BranchesDropdown.module.css';
import { ActiveBranch, MergeStatus } from '../../types';
import { API_ENDPOINTS } from '../../api/config';

export const BranchesDropdown: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [branches, setBranches] = useState<ActiveBranch[]>([]);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchBranches();
    }
  }, [isOpen]);

  const fetchBranches = async () => {
    try {
      const projectId = typeof window !== 'undefined' ? localStorage.getItem('orq.currentProjectId') : null;
      const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
      const response = await fetch(`${API_ENDPOINTS.branches}${qs}`);
      const data = await response.json();
      setBranches(data.branches || []);
    } catch (error) {
      console.error('Failed to fetch branches:', error);
    }
  };

  const getStatusIcon = (status: MergeStatus) => {
    switch (status) {
      case 'merging': return '\u23F3';
      case 'resolving': return '\uD83E\uDD16';
      case 'merged': return '\u2713';
      case 'failed': return '\u274C';
      default: return '\uD83D\uDD00';
    }
  };

  const hasConflicts = branches.some(b => b.mergeStatus === 'failed');
  const hasResolving = branches.some(b => b.mergeStatus === 'resolving');

  return (
    <div className={styles.dropdown} ref={dropdownRef}>
      <button
        className={`${styles.trigger} ${hasConflicts ? styles.hasConflicts : ''} ${hasResolving ? styles.hasResolving : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className={styles.triggerIcon}>{'\uD83D\uDD00'}</span>
        <span className={styles.count}>{branches.length}</span>
        {hasConflicts && <span className={styles.warning}>{'\u26A0\uFE0F'}</span>}
        {hasResolving && <span className={styles.resolving}>{'\uD83E\uDD16'}</span>}
      </button>

      {isOpen && (
        <div className={styles.menu}>
          <div className={styles.menuHeader}>Branches Ativas</div>
          {branches.length === 0 ? (
            <div className={styles.empty}>Nenhuma branch ativa</div>
          ) : (
            branches.map((branch) => (
              <div
                key={branch.cardId}
                className={`${styles.branchItem} ${styles[branch.mergeStatus || 'none']}`}
              >
                <span className={styles.icon}>
                  {getStatusIcon(branch.mergeStatus || 'none')}
                </span>
                <div className={styles.branchInfo}>
                  <div className={styles.branchName}>
                    {branch.branch.replace('agent/', '')}
                  </div>
                  <div className={styles.cardTitle}>{branch.cardTitle}</div>
                </div>
                <span className={styles.column}>{branch.cardColumn}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};
