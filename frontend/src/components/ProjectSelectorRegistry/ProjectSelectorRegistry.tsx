import { useState, useEffect, useCallback } from 'react';
import { FolderKanban, X } from 'lucide-react';
import { listProjects, createProject, type RegistryProject } from '../../api/projectsRegistry';
import styles from './ProjectSelectorRegistry.module.css';

interface ProjectSelectorRegistryProps {
  currentProjectId: string | null;
  onSwitch: (projectId: string) => void;
}

export function ProjectSelectorRegistry({ currentProjectId, onSwitch }: ProjectSelectorRegistryProps) {
  const [projects, setProjects] = useState<RegistryProject[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    if (id && id !== currentProjectId) {
      onSwitch(id);
    }
  };

  const handleOpenForm = () => {
    setIsFormOpen(true);
    setError(null);
  };

  const handleCancel = () => {
    setIsFormOpen(false);
    setName('');
    setPath('');
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
      const project = await createProject({ name: name.trim(), path: path.trim() });
      await loadProjects();
      onSwitch(project.id);
      setIsFormOpen(false);
      setName('');
      setPath('');
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
          disabled={isLoading || projects.length === 0}
          title="Selecionar projeto do board"
        >
          {projects.length === 0 && <option value="">Nenhum projeto cadastrado</option>}
          {projects.length > 0 && !currentProjectId && <option value="">Selecione um projeto</option>}
          {projects.map(project => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>

      {isFormOpen ? (
        <div className={styles.inlineForm}>
          <input
            className={styles.input}
            type="text"
            placeholder="Nome"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={isCreating}
          />
          <input
            className={styles.input}
            type="text"
            placeholder="Caminho local"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            disabled={isCreating}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !isCreating) handleCreate();
            }}
          />
          <button className={styles.confirmButton} onClick={handleCreate} disabled={isCreating}>
            {isCreating ? '...' : 'Criar'}
          </button>
          <button className={styles.cancelButton} onClick={handleCancel} disabled={isCreating} title="Cancelar">
            <X size={14} />
          </button>
          {error && <span className={styles.errorText}>{error}</span>}
        </div>
      ) : (
        <button className={styles.addButton} onClick={handleOpenForm} title="Cadastrar novo projeto">
          ＋ Projeto
        </button>
      )}
    </div>
  );
}
