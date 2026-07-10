import { createPortal } from 'react-dom';
import type { Toast } from '../../hooks/useToast';
import styles from './Toast.module.css';

interface Props {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

/** Toasts globais (canto inferior direito). Hoje usado para avisar pausa de card (A3). */
export function ToastContainer({ toasts, onDismiss }: Props) {
  if (toasts.length === 0) return null;
  return createPortal(
    <div className={styles.container} role="status" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className={`${styles.toast} ${styles[t.type]}`} onClick={() => onDismiss(t.id)}>
          <div className={styles.title}>{t.title}</div>
          {t.message && <div className={styles.message}>{t.message}</div>}
        </div>
      ))}
    </div>,
    document.body
  );
}
