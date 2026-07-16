/**
 * API client do pipeline orquestrado pelo backend (Fase 3b-resto).
 * Dispara o runner (plan -> implement -> review, com fix-loop/pause) e consulta o run.
 */

import { API_CONFIG } from './config';
import type { ExecutionLog } from '../types';

export interface PipelineExecution {
  id: string;
  status: 'idle' | 'running' | 'success' | 'error' | 'paused' | null;
  workflowStage?: string | null;
  workflowError?: string | null;
  prUrl?: string | null;
  costUsd?: number | null;
  fixIterations?: number | null;
  modelUsed?: string | null;
  totalTokens?: number | null;
  isActive?: boolean;
  startedAt?: string | null;
  completedAt?: string | null;
}

export interface PipelineExecutionState {
  execution: PipelineExecution | null;
  logs: ExecutionLog[];
}

function base(projectId: string, cardId: string): string {
  return `${API_CONFIG.BASE_URL}/api/projects/${encodeURIComponent(projectId)}/cards/${encodeURIComponent(cardId)}`;
}

/** Dispara o pipeline em background; retorna o executionId (o progresso vem por WS). */
export async function runPipeline(projectId: string, cardId: string): Promise<{ executionId: string }> {
  const response = await fetch(`${base(projectId, cardId)}/execute`, { method: 'POST' });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Falha ao iniciar pipeline: ${response.statusText}`);
  }
  return response.json();
}

export interface CardComment {
  id: string;
  author: string | null;   // 'agent' | 'human' | null
  text: string;
  timestamp: string;
  /** Respostas sugeridas pelo agente (renderizadas como chips clicáveis no card pausado). */
  options?: string[];
}

/** `new_value` do comentário carrega as respostas sugeridas como JSON (array de strings). */
function parseOptions(raw: string | null | undefined): string[] | undefined {
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      const clean = parsed.filter((o): o is string => typeof o === 'string' && o.trim().length > 0);
      return clean.length > 0 ? clean : undefined;
    }
  } catch { /* new_value de outros tipos de atividade não é JSON — ignora */ }
  return undefined;
}

/** Interrompe (Stop) o agente da etapa em execução; o pipeline pausa o card para correção. */
export async function stopPipeline(projectId: string, cardId: string): Promise<void> {
  const response = await fetch(`${base(projectId, cardId)}/stop`, { method: 'POST' });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Falha ao interromper: ${response.statusText}`);
  }
}

/** Responde a pausa do card e RETOMA o pipeline automaticamente. */
export async function answerPipeline(projectId: string, cardId: string, message: string): Promise<{ executionId: string }> {
  const response = await fetch(`${base(projectId, cardId)}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Falha ao responder: ${response.statusText}`);
  }
  return response.json();
}

/** Thread de comentarios do card (pergunta do agente / resposta humana), mais antigo primeiro. */
export async function getCardComments(cardId: string): Promise<CardComment[]> {
  const response = await fetch(`${API_CONFIG.BASE_URL}/api/activities/card/${encodeURIComponent(cardId)}`);
  if (!response.ok) return [];
  const data = await response.json();
  const rows: Array<{ id: string; type: string; userId: string | null; description: string | null; timestamp: string; newValue?: string | null }> =
    data.activities || data || [];
  return rows
    .filter(r => r.type === 'commented')
    .map(r => ({ id: r.id, author: r.userId, text: r.description || '', timestamp: r.timestamp, options: parseOptions(r.newValue) }))
    .reverse(); // endpoint devolve desc; queremos cronologico
}

/** Detecta se o PR do card foi mergeado no GitHub; se sim, o backend move o card para done. */
export async function checkMerge(projectId: string, cardId: string): Promise<{ merged: boolean; state?: string }> {
  try {
    const response = await fetch(`${base(projectId, cardId)}/check-merge`, { method: 'POST' });
    if (!response.ok) return { merged: false };
    return await response.json();
  } catch {
    return { merged: false }; // resiliente: erro de rede nunca quebra o poll
  }
}

/** Ultimo run do card + logs persistidos (para reload/historico do painel). */
export async function getExecution(projectId: string, cardId: string): Promise<PipelineExecutionState> {
  const response = await fetch(`${base(projectId, cardId)}/execution`);
  if (!response.ok) {
    throw new Error(`Falha ao carregar execucao: ${response.statusText}`);
  }
  const data = await response.json();
  const logs: ExecutionLog[] = (data.logs || []).map((lg: { type: string; content: string }) => ({
    timestamp: new Date().toISOString(),
    type: lg.type,
    content: lg.content,
  }));
  return { execution: data.execution, logs };
}
