import { useCallback, useState } from 'react';
import { useExecutionWebSocket } from '../../hooks/useExecutionWebSocket';
import { runPipeline, getExecution } from '../../api/pipeline';
import { LogsModal } from '../LogsModal';
import type { Card as CardType, ExecutionLog } from '../../types';
import styles from './PipelineControls.module.css';

type RawStatus = 'idle' | 'running' | 'success' | 'error' | 'paused';

interface Props {
  card: CardType;
}

/**
 * Fase 3b-resto: dispara o pipeline orquestrado pelo backend e mostra os logs ao vivo.
 * Autocontido — le o projeto atual do localStorage (mesma chave do App) para nao exigir
 * prop drilling. O avanco de coluna no board vem do WebSocket de cards (useCardWebSocket no App).
 */
export function PipelineControls({ card }: Props) {
  const projectId = typeof window !== 'undefined' ? localStorage.getItem('orq.currentProjectId') : null;
  const [status, setStatus] = useState<RawStatus>('idle');
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const [startedAt, setStartedAt] = useState<string | undefined>();
  const [completedAt, setCompletedAt] = useState<string | undefined>();
  const [wsCardId, setWsCardId] = useState<string | null>(null);

  const onLog = useCallback((msg: { logType: string; content: string; timestamp: string }) => {
    const type: ExecutionLog['type'] = msg.logType === 'error'
      ? 'error'
      : msg.logType === 'system' ? 'result' : 'info';
    setLogs(prev => [...prev, { timestamp: msg.timestamp, type, content: msg.content }]);
  }, []);

  const onComplete = useCallback((msg: { status: string; timestamp: string }) => {
    setStatus((msg.status as RawStatus) || 'success');
    setCompletedAt(msg.timestamp);
  }, []);

  useExecutionWebSocket(wsCardId, onComplete, onLog);

  const handleRun = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!projectId) return;
    setLogs([]);
    setStatus('running');
    setStartedAt(new Date().toISOString());
    setCompletedAt(undefined);
    setWsCardId(card.id);
    setLogsOpen(true);
    try {
      await runPipeline(projectId, card.id);
    } catch (err) {
      setStatus('error');
      setLogs(prev => [...prev, {
        timestamp: new Date().toISOString(), type: 'error',
        content: err instanceof Error ? err.message : 'Falha ao iniciar pipeline',
      }]);
    }
  }, [projectId, card.id]);

  const handleOpenLogs = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    // Reload: se ainda nao ha logs em memoria, busca o run persistido
    if (logs.length === 0 && projectId) {
      try {
        const state = await getExecution(projectId, card.id);
        if (state.execution) {
          setStatus((state.execution.status as RawStatus) || 'idle');
          setStartedAt(state.execution.startedAt || undefined);
          setCompletedAt(state.execution.completedAt || undefined);
        }
        setLogs(state.logs);
        if (state.execution?.isActive) setWsCardId(card.id);
      } catch { /* ignore */ }
    }
    setLogsOpen(true);
  }, [logs.length, projectId, card.id]);

  if (!projectId) return null;

  const isRunning = status === 'running';
  // LogsModal so conhece idle/running/success/error; pausa conta como concluida (motivo esta no log).
  const modalStatus: 'idle' | 'running' | 'success' | 'error' =
    status === 'paused' ? 'success' : status;

  return (
    <>
      {card.columnId === 'backlog' && (
        <button
          className={styles.runButton}
          onClick={handleRun}
          disabled={isRunning}
          aria-label="Executar pipeline"
          title="Executar o pipeline (plan -> implement -> review) no backend"
        >
          {isRunning
            ? <span className={styles.spinner} />
            : <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2l10 6-10 6V2z" /></svg>}
          {isRunning ? 'Executando...' : 'Run'}
        </button>
      )}

      {(isRunning || logs.length > 0 || status !== 'idle') && card.columnId !== 'backlog' && (
        <button className={styles.logsButton} onClick={handleOpenLogs} title="Ver logs do pipeline">
          {isRunning && <span className={styles.spinner} />}
          Logs
        </button>
      )}

      <LogsModal
        isOpen={logsOpen}
        onClose={() => setLogsOpen(false)}
        title={card.title}
        status={modalStatus}
        logs={logs}
        startedAt={startedAt}
        completedAt={completedAt}
      />
    </>
  );
}
