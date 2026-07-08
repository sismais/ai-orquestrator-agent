import { useCallback, useEffect, useState } from 'react';
import { useExecutionWebSocket } from '../../hooks/useExecutionWebSocket';
import { runPipeline, getExecution, stopPipeline } from '../../api/pipeline';
import { LogsModal } from '../LogsModal';
import type { Card as CardType, ExecutionLog } from '../../types';
import styles from './PipelineControls.module.css';

type RawStatus = 'idle' | 'running' | 'success' | 'error' | 'paused';

const ACTIVE_STAGE_COLUMNS = ['plan', 'implement', 'review'];

interface Props {
  card: CardType;
}

/**
 * Fase 3b-resto: dispara o pipeline orquestrado pelo backend e mostra os logs ao vivo.
 * A interacao humana (card pausado) vive no modal do card (aba Interacao) — aqui ficam so
 * o Run (backlog) e o botao de Logs. Le o projeto atual do localStorage (sem prop drilling).
 */
export function PipelineControls({ card }: Props) {
  const projectId = typeof window !== 'undefined' ? localStorage.getItem('orq.currentProjectId') : null;
  const [status, setStatus] = useState<RawStatus>('idle');
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const [startedAt, setStartedAt] = useState<string | undefined>();
  const [completedAt, setCompletedAt] = useState<string | undefined>();
  const [wsCardId, setWsCardId] = useState<string | null>(null);
  const [prUrl, setPrUrl] = useState<string | null>(null);

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

  // Card numa etapa ativa (plan/implement/review): se ha execucao rodando, liga o Stop + logs ao vivo.
  useEffect(() => {
    if (status !== 'idle' || !projectId || !ACTIVE_STAGE_COLUMNS.includes(card.columnId)) return;
    let alive = true;
    getExecution(projectId, card.id).then(state => {
      if (alive && state.execution?.isActive && state.execution.status === 'running') {
        setStatus('running');
        setWsCardId(card.id);
      }
    }).catch(() => {});
    return () => { alive = false; };
  }, [card.columnId, card.id, projectId, status]);

  // Limpa "running" preso quando o card sai de uma etapa ativa (evita Stop fantasma em validate_ci/done).
  const isActiveStage = ACTIVE_STAGE_COLUMNS.includes(card.columnId);
  useEffect(() => {
    if (!isActiveStage && status === 'running') {
      setStatus('idle');
      setWsCardId(null);
    }
  }, [isActiveStage, status]);

  // Busca o link do PR quando o card chega no ready_to_merge (Fase 3c).
  useEffect(() => {
    if (card.columnId !== 'ready_to_merge' || !projectId || prUrl) return;
    let alive = true;
    getExecution(projectId, card.id).then(state => {
      if (alive && state.execution?.prUrl) setPrUrl(state.execution.prUrl);
    }).catch(() => {});
    return () => { alive = false; };
  }, [card.columnId, card.id, projectId, prUrl]);

  const handleStop = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!projectId) return;
    try {
      await stopPipeline(projectId, card.id);
    } catch { /* 409 = nada rodando; ignore */ }
  }, [projectId, card.id]);

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

      {isRunning && isActiveStage && (
        <button className={styles.stopButton} onClick={handleStop} title="Interromper o agente para corrigir">
          <span className={styles.runningDot} />
          Running
          <svg width="11" height="11" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
            <rect x="2" y="2" width="10" height="10" rx="1.5" />
          </svg>
        </button>
      )}

      {prUrl && (
        <a
          className={styles.prLink}
          href={prUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="Abrir o Pull Request (draft) no GitHub"
        >
          🔗 Ver PR
        </a>
      )}

      {(isRunning || logs.length > 0 || status !== 'idle' || !!card.branchName) && card.columnId !== 'backlog' && (
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
