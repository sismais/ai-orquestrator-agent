import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Folder, ArrowLeft, X } from 'lucide-react';
import { browseDirectory, type DirectoryEntry } from '../../api/filesystem';
import styles from './FolderBrowserModal.module.css';

interface FolderBrowserModalProps {
  initialPath?: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

export function FolderBrowserModal({ initialPath, onSelect, onClose }: FolderBrowserModalProps) {
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [directories, setDirectories] = useState<DirectoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async (path?: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await browseDirectory(path);
      setCurrentPath(result.path);
      setParentPath(result.parent);
      setDirectories(result.directories);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao acessar pasta.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load(initialPath || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return createPortal(
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h2 className={styles.modalTitle}>Escolher pasta</h2>
          <button className={styles.closeButton} onClick={onClose} aria-label="Fechar modal">
            <X size={16} />
          </button>
        </div>

        <div className={styles.currentPath} title={currentPath ?? ''}>
          {currentPath ?? 'Unidades'}
        </div>

        <div className={styles.list}>
          {isLoading && <div className={styles.hint}>Carregando...</div>}
          {error && <div className={styles.errorText}>{error}</div>}
          {!isLoading && !error && (
            <>
              {currentPath && (
                <button className={styles.entry} onClick={() => load(parentPath ?? undefined)}>
                  <ArrowLeft size={16} />
                  <span>..</span>
                </button>
              )}
              {directories.length === 0 && <div className={styles.hint}>Nenhuma subpasta.</div>}
              {directories.map((dir) => (
                <button key={dir.path} className={styles.entry} onClick={() => load(dir.path)}>
                  <Folder size={16} />
                  <span>{dir.name}</span>
                </button>
              ))}
            </>
          )}
        </div>

        <div className={styles.modalFooter}>
          <button className={styles.cancelButton} onClick={onClose}>
            Cancelar
          </button>
          <button
            className={styles.confirmButton}
            onClick={() => currentPath && onSelect(currentPath)}
            disabled={!currentPath}
          >
            Selecionar esta pasta
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
