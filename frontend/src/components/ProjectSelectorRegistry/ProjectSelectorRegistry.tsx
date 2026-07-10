import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { FolderKanban, X } from 'lucide-react';
import { listProjects, createProject, type RegistryProject } from '../../api/projectsRegistry';
import { FolderBrowserModal } from '../FolderBrowserModal/FolderBrowserModal';
import styles from './ProjectSelectorRegistry.module.css';

const CREATE_PROJECT_ID = '__add_project__';

interface ProjectSelectorRegistryProps {
  currentProjectId: string | null;
  onSwitch: (projectId: string) => void;
}

export function ProjectSelectorRegistry({ currentProjectId, onSwitch }: ProjectSelectorRegistryProps) {
  const [projects, setProjects] = useState<RegistryProject[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [objective, setObjective] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isFolderBrowserOpen, setIsFolderBrowserOpen] = useState(false);

  const loadProjects = useCallback(async () => {
    setIsLoading(true);
    try {
      const list = await listProjects();
      setProjects(list);
    } catch (err) {
      console.error('[ProjectSelectorRegistry] Failed to list projects:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    if (!id || id === CREATE_PROJECT_ID || id === currentProjectId) {
      if (id === CREATE_PROJECT_ID) {
        setIsCreateModalOpen(true);
      }
      return;
    }

    onSwitch(id);
  };

  const handleCancel = () => {
    setIsCreateModalOpen(false);
    setName('');
    setPath('');
    setObjective('');
    setError(null);
  };

  const handleCreate = async () => {
    if (!name.trim() || !path.trim()) {
      setError('Informe nome e caminho.');
      return;
    }

    setIsCreating(true);
    setError(null);
    try {
      const project = await createProject({
        name: name.trim(),
        path: path.trim(),
        objective: objective.trim() || undefined,
      });
      await loadProjects();
      onSwitch(project.id);
      setIsCreateModalOpen(false);
      setName('');
      setPath('');
      setObjective('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao criar projeto.');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.selectGroup}>
        <FolderKanban size={16} className={styles.icon} />
        <select
          className={styles.select}
          value={currentProjectId ?? ''}
          onChange={handleSelectChange}
          disabled={isLoading}
          title="Selecionar projeto do board"
        >
          {projects.length === 0 && <option value="">Nenhum projeto cadastrado</option>}
          {projects.length > 0 && <option value="">Selecione um projeto</option>}
          {projects.map(project => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
          <option value={CREATE_PROJECT_ID}>+ Novo Projeto</option>
        </select>
      </div>

      {isCreateModalOpen && createPortal(
        <div className={styles.modalOverlay} onClick={handleCancel}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div className={styles.modalTitleGroup}>
                <span className={styles.modalIcon}>＋</span>
                <div>
                  <h2 className={styles.modalTitle}>Cadastrar novo projeto</h2>
                  <p className={styles.modalSubtitle}>Informe nome e caminho local do projeto.</p>
                </div>
              </div>
              <button className={styles.closeButton} onClick={handleCancel} aria-label="Fechar modal">
                <X size={16} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <label className={styles.fieldLabel}>
                Nome
                <input
                  className={styles.input}
                  type="text"
                  placeholder="Nome do projeto"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={isCreating}
                />
              </label>
              <label className={styles.fieldLabel}>
                Caminho local
                <div className={styles.pathField}>
                  <input
                    className={styles.input}
                    type="text"
                    placeholder="Caminho local"
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    disabled={isCreating}
                  />
                  <button
                    type="button"
                    className={styles.browseButton}
                    onClick={() => setIsFolderBrowserOpen(true)}
                    disabled={isCreating}
                  >
                    Escolher pasta
                  </button>
                </div>
              </label>
              <label className={styles.fieldLabel}>
                Objetivo (opcional)
                <textarea
                  className={styles.input}
                  rows={2}
                  placeholder="Objetivo de negócio do projeto — os agentes usam isso para calibrar decisões"
                  value={objective}
                  onChange={(e) => setObjective(e.target.value)}
                  disabled={isCreating}
                />
              </label>
              {error && <div className={styles.errorText}>{error}</div>}
            </div>

            <div className={styles.modalFooter}>
              <button className={styles.cancelButton} onClick={handleCancel} disabled={isCreating}>
                Cancelar
              </button>
              <button className={styles.confirmButton} onClick={handleCreate} disabled={isCreating}>
                {isCreating ? 'Criando...' : 'Criar projeto'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {isFolderBrowserOpen && (
        <FolderBrowserModal
          initialPath={path.trim() || undefined}
          onSelect={(selectedPath) => {
            setPath(selectedPath);
            setIsFolderBrowserOpen(false);
          }}
          onClose={() => setIsFolderBrowserOpen(false)}
        />
      )}
    </div>
  );
}
