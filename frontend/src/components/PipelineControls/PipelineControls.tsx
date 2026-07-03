import { useCallback, useEffect, useState } from 'react';
import { useExecutionWebSocket } from '../../hooks/useExecutionWebSocket';
import {
  runPipeline, getExecution, answerPipeline, getCardComments, type CardComment,
} from '../../api/pipeline';
import { LogsModal } from '../LogsModal';
import type { Card as CardType, ExecutionLog } from '../../types';
import styles from './PipelineControls.module.css';

type RawStatus = 'idle' | 'running' | 'success' | 'error' | 'paused';

interface Props {
  card: CardType;
}

/**
 * Fase 3b-resto + interacao humana: dispara o pipeline, mostra os logs ao vivo, e quando o card
 * esta pausado exibe a pergunta do agente + caixa de resposta (responder retoma o pipeline).
 * Autocontido — le o projeto atual do localStorage. O avanco de coluna vem do WebSocket de cards.
 */
export function PipelineControls({ card }: Props) {
  const projectId = typeof window !== 'undefined' ? localStorage.getItem('orq.currentProjectId') : null;
  const [status, setStatus] = useState<RawStatus>('idle');
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const [startedAt, setStartedAt] = useState<string | undefined>();
  const [completedAt, setCompletedAt] = useState<string | undefined>();
  const [wsCardId, setWsCardId] = useState<string | null>(null);
  const [comments, setComments] = useState<CardComment[]>([]);
  const [answer, setAnswer] = useState('');
  const [sending, setSending] = useState(false);

  const isPaused = card.columnId === 'paused';

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

  // Carrega o thread de comentarios quando o card esta pausado (pergunta do agente + respostas).
  useEffect(() => {
    if (!isPaused) return;
    let alive = true;
    getCardComments(card.id).then(c => { if (alive) setComments(c); }).catch(() => {});
    return () => { alive = false; };
  }, [isPaused, card.id]);

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

  const handleAnswer = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    const msg = answer.trim();
    if (!projectId || !msg || sending) return;
    setSending(true);
    // otimista: mostra a resposta no thread e liga o WS de logs
    setComments(prev => [...prev, { id: 'local', author: 'human', text: msg, timestamp: new Date().toISOString() }]);
    setAnswer('');
    setWsCardId(card.id);
    try {
      await answerPipeline(projectId, card.id, msg);
    } catch (err) {
      setComments(prev => [...prev, {
        id: 'err', author: 'agent',
        text: err instanceof Error ? err.message : 'Falha ao responder', timestamp: new Date().toISOString(),
      }]);
    } finally {
      setSending(false);
    }
  }, [answer, projectId, card.id, sending]);

  if (!projectId) return null;

  const isRunning = status === 'running';
  const modalStatus: 'idle' | 'running' | 'success' | 'error' =
    status === 'paused' ? 'success' : status;
  const agentQuestion = [...comments].reverse().find(c => c.author === 'agent');

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

      {isPaused && (
        <div className={styles.pausePanel} onClick={(e) => e.stopPropagation()}>
          <div className={styles.pauseHeader}>⏸ Aguardando você</div>
          {agentQuestion && <div className={styles.question}>{agentQuestion.text}</div>}
          {comments.filter(c => c.author === 'human').length > 0 && (
            <div className={styles.thread}>
              {comments.filter(c => c.author === 'human').map((c, i) => (
                <div key={i} className={styles.human}>você: {c.text}</div>
              ))}
            </div>
          )}
          <textarea
            className={styles.answerInput}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Responda para retomar…"
            rows={2}
            onPointerDown={(e) => e.stopPropagation()}
          />
          <button className={styles.answerButton} onClick={handleAnswer} disabled={sending || !answer.trim()}>
            {sending ? 'Enviando…' : 'Responder e retomar'}
          </button>
        </div>
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
