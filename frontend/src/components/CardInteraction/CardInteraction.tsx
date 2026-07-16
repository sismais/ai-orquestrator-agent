import { useCallback, useEffect, useState } from 'react';
import { getCardComments, answerPipeline, type CardComment } from '../../api/pipeline';
import type { Card as CardType } from '../../types';
import styles from './CardInteraction.module.css';

interface Props {
  card: CardType;
}

/**
 * Conversa da interacao humana do card (pergunta do agente <-> resposta humana).
 * Renderizada como aba do modal do card. Quando o card esta pausado, mostra a caixa de
 * resposta que RETOMA o pipeline. Le o projeto atual do localStorage (mesma chave do App).
 */
export function CardInteraction({ card }: Props) {
  const projectId = typeof window !== 'undefined' ? localStorage.getItem('orq.currentProjectId') : null;
  const [comments, setComments] = useState<CardComment[]>([]);
  const [answer, setAnswer] = useState('');
  const [sending, setSending] = useState(false);
  const [resumed, setResumed] = useState(false);
  const isPaused = card.columnId === 'paused';
  // Chips: respostas sugeridas da ULTIMA pergunta do agente (só faz sentido no card pausado,
  // e só se ninguem respondeu depois dela).
  const lastComment = comments[comments.length - 1];
  const suggestions = isPaused && lastComment?.author === 'agent' && lastComment.options ? lastComment.options : [];

  useEffect(() => {
    let alive = true;
    getCardComments(card.id).then(c => { if (alive) setComments(c); }).catch(() => {});
    return () => { alive = false; };
  }, [card.id]);

  const handleSend = useCallback(async () => {
    const msg = answer.trim();
    if (!projectId || !msg || sending) return;
    setSending(true);
    setComments(prev => [...prev, { id: 'local', author: 'human', text: msg, timestamp: new Date().toISOString() }]);
    setAnswer('');
    try {
      await answerPipeline(projectId, card.id, msg);
      setResumed(true);
    } catch (err) {
      setComments(prev => [...prev, {
        id: 'err', author: 'agent',
        text: err instanceof Error ? err.message : 'Falha ao responder', timestamp: new Date().toISOString(),
      }]);
    } finally {
      setSending(false);
    }
  }, [answer, projectId, card.id, sending]);

  return (
    <div className={styles.wrap}>
      {comments.length === 0 && (
        <div className={styles.empty}>Sem conversa ainda. Quando o agente precisar de uma decisão, a pergunta aparece aqui.</div>
      )}

      {comments.length > 0 && (
        <div className={styles.thread}>
          {comments.map((c, i) => (
            <div key={i} className={c.author === 'human' ? styles.human : styles.agent}>
              <span className={styles.who}>{c.author === 'human' ? 'Você' : 'Agente'}</span>
              <div className={styles.bubble}>{c.text}</div>
            </div>
          ))}
        </div>
      )}

      {isPaused ? (
        <div className={styles.answerRow}>
          {suggestions.length > 0 && (
            <>
              <div className={styles.chipsHint}>Sugestões do agente — clique para preencher (você pode editar antes de enviar):</div>
              <div className={styles.chips}>
                {suggestions.map((opt, i) => (
                  <button key={i} type="button" className={styles.chip} onClick={() => setAnswer(opt)}>
                    {opt.length > 80 ? `${opt.slice(0, 77)}…` : opt}
                  </button>
                ))}
              </div>
            </>
          )}
          <textarea
            className={styles.input}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Responda para retomar o trabalho…"
            rows={3}
          />
          <button className={styles.button} onClick={handleSend} disabled={sending || !answer.trim()}>
            {sending ? 'Enviando…' : 'Responder e retomar'}
          </button>
        </div>
      ) : resumed ? (
        <div className={styles.resumed}>Resposta enviada — retomando o pipeline…</div>
      ) : (
        <div className={styles.note}>Este card não está aguardando resposta no momento.</div>
      )}
    </div>
  );
}
