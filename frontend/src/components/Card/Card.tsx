import { useState, useEffect } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Card as CardType, ExecutionStatus, WorkflowStatus, ExecutionHistory } from '../../types';
import { LogsModal } from '../LogsModal';
import { PipelineControls } from '../PipelineControls';
import { CardEditModal } from '../CardEditModal';
import { BranchIndicator } from '../BranchIndicator';
import { ExpertBadges } from '../ExpertBadges';
import { removeImage } from '../../utils/imageHandler';
import { API_ENDPOINTS } from '../../api/config';
import { formatCost } from '../../utils/costCalculator';
import styles from './Card.module.css';

interface CardProps {
  card: CardType;
  onRemove: () => void;
  onUpdateCard?: (card: CardType) => void;
  isDragging?: boolean;
  executionStatus?: ExecutionStatus;
  workflowStatus?: WorkflowStatus;
  onRunWorkflow?: (card: CardType) => void;
  fetchLogsHistory?: (cardId: string) => Promise<{ cardId: string; history: ExecutionHistory[] } | null>;
  isLoadingExperts?: boolean;
}

export function Card({ card, onRemove, onUpdateCard, isDragging = false, executionStatus, workflowStatus, fetchLogsHistory, isLoadingExperts }: CardProps) {
  const [isLogsOpen, setIsLogsOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [removingImageId, setRemovingImageId] = useState<string | null>(null);
  const [logsHistory, setLogsHistory] = useState<ExecutionHistory[] | undefined>(undefined);
  const [hasHistoricalLogs, setHasHistoricalLogs] = useState(false);

  // Card só é desabilitado se estiver ATIVAMENTE em execução
  // Permitir arrastar se: idle, completed, error, ou se a execução já terminou
  const isActivelyRunning = workflowStatus
    && workflowStatus.stage !== 'idle'
    && workflowStatus.stage !== 'completed'
    && workflowStatus.stage !== 'error'
    && executionStatus?.status === 'running'; // Só bloquear se a execução ainda está rodando

  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: card.id,
    disabled: isActivelyRunning // Apenas desabilitar drag durante execução ativa
  });

  const style = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
      }
    : undefined;

  const getStatusClass = () => {
    if (!executionStatus) return '';
    switch (executionStatus.status) {
      case 'running': return styles.statusRunning;
      case 'success': return styles.statusSuccess;
      case 'error': return styles.statusError;
      default: return '';
    }
  };

  const hasLogs = executionStatus && executionStatus.logs && executionStatus.logs.length > 0;

  // Buscar logs históricos para cards em done sem executionStatus ativo
  useEffect(() => {
    if (card.columnId === 'done' && !executionStatus && fetchLogsHistory) {
      fetchLogsHistory(card.id).then(history => {
        if (history && history.history.length > 0) {
          setHasHistoricalLogs(true);
          setLogsHistory(history.history);
        }
      }).catch(err => {
        console.error('Failed to fetch historical logs:', err);
      });
    }
  }, [card.columnId, card.id, executionStatus, fetchLogsHistory]);

  // Determinar se deve mostrar botão de logs
  const shouldShowLogs = hasLogs || (card.columnId === 'done' && hasHistoricalLogs);

  const handleRemoveImage = async (imageId: string) => {
    try {
      setRemovingImageId(imageId);
      await removeImage(imageId);

      // Atualizar o card removendo a imagem
      if (onUpdateCard && card.images) {
        const updatedCard = {
          ...card,
          images: card.images.filter(img => img.id !== imageId)
        };
        onUpdateCard(updatedCard);
      }
    } catch (error) {
      console.error('Failed to remove image:', error);
    } finally {
      setRemovingImageId(null);
    }
  };

  // Função helper para determinar a mensagem de execução
  const getExecutionMessage = () => {
    if (!executionStatus || executionStatus.status === 'idle') return null;

    const { status } = executionStatus;
    const stage = workflowStatus?.stage;

    // Mapear stage para comando
    const stageToCommand: Record<string, { running: string; success: string; error: string }> = {
      planning: {
        running: 'Executing /plan...',
        success: 'Plan completed',
        error: 'Plan failed',
      },
      implementing: {
        running: 'Executing /implement...',
        success: 'Implementation completed',
        error: 'Implementation failed',
      },
      testing: {
        running: 'Executing /test-implementation...',
        success: 'Tests completed',
        error: 'Tests failed',
      },
      reviewing: {
        running: 'Executing /review...',
        success: 'Review completed',
        error: 'Review failed',
      },
    };

    // Se temos workflowStatus.stage, usar ele para determinar a mensagem
    if (stage && stage in stageToCommand) {
      return stageToCommand[stage][status];
    }

    // Fallback: determinar com base na coluna do card (para execuções manuais)
    const columnToCommand: Record<string, { running: string; success: string; error: string }> = {
      plan: {
        running: 'Executing /plan...',
        success: 'Plan completed',
        error: 'Plan failed',
      },
      implement: {
        running: 'Executing /implement...',
        success: 'Implementation completed',
        error: 'Implementation failed',
      },
      test: {
        running: 'Executing /test-implementation...',
        success: 'Tests completed',
        error: 'Tests failed',
      },
      review: {
        running: 'Executing /review...',
        success: 'Review completed',
        error: 'Review failed',
      },
    };

    if (card.columnId in columnToCommand) {
      return columnToCommand[card.columnId][status];
    }

    // Fallback genérico
    const genericMessages: Record<string, string> = {
      running: 'Executing...',
      success: 'Execution completed',
      error: 'Execution failed',
    };

    return genericMessages[status];
  };

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        className={`${styles.card} ${isDragging ? styles.dragging : ''} ${getStatusClass()} ${card.isFixCard ? styles.fixCard : ''}`}
        {...listeners}
        {...attributes}
      >
        {card.isFixCard && (
          <div className={styles.fixBadge}>
            🔧 Correção
          </div>
        )}
        <div className={styles.content}>
          <div className={styles.cardHeader}>
            <h3 className={styles.title}>{card.title}</h3>
            {card.branchName && (
              <BranchIndicator
                branchName={card.branchName}
              />
            )}
          </div>
          {(card.experts || isLoadingExperts) && (
            <ExpertBadges
              experts={card.experts}
              isLoading={isLoadingExperts}
              size="small"
            />
          )}
          {card.description && (
            <p className={styles.description}>{card.description}</p>
          )}
          {card.mergeStatus === 'failed' && (
            <div className={styles.failedBanner}>
              IA nao conseguiu resolver conflitos. Verificar manualmente.
            </div>
          )}
          {card.images && card.images.length > 0 && (
            <div className={styles.imagePreview}>
              {card.images.map(image => (
                <div key={image.id} className={styles.imageThumb}>
                  <img
                    src={`${API_ENDPOINTS.images}/${image.id}`}
                    alt={image.filename}
                    title={image.filename}
                  />
                  <button
                    className={styles.removeImageButton}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRemoveImage(image.id);
                    }}
                    disabled={removingImageId === image.id}
                    aria-label={`Remove ${image.filename}`}
                  >
                    {removingImageId === image.id ? '...' : '✕'}
                  </button>
                </div>
              ))}
            </div>
          )}
          {executionStatus && executionStatus.status !== 'idle' && (
            <div className={styles.executionStatus}>
              {(() => {
                const message = getExecutionMessage();
                if (!message) return null;

                return (
                  <>
                    {executionStatus.status === 'running' && (
                      <span className={styles.statusBadge}>
                        <span className={styles.spinner} />
                        {message}
                      </span>
                    )}
                    {executionStatus.status === 'success' && (
                      <span className={styles.statusBadge}>
                        <span className={styles.checkIcon}>✓</span>
                        {message}
                      </span>
                    )}
                    {executionStatus.status === 'error' && (
                      <span className={styles.statusBadge}>
                        <span className={styles.errorIcon}>✗</span>
                        {message}
                      </span>
                    )}
                    {shouldShowLogs && (
                      <button
                        className={styles.viewLogsButton}
                        onClick={async (e) => {
                          e.stopPropagation();

                          // Buscar histórico completo antes de abrir o modal
                          if (fetchLogsHistory) {
                            const history = await fetchLogsHistory(card.id);
                            if (history) {
                              setLogsHistory(history.history);
                            }
                          }

                          setIsLogsOpen(true);
                        }}
                        aria-label="View execution logs"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                          <polyline points="14 2 14 8 20 8"/>
                          <line x1="16" y1="13" x2="8" y2="13"/>
                          <line x1="16" y1="17" x2="8" y2="17"/>
                          <line x1="10" y1="9" x2="8" y2="9"/>
                        </svg>
                        View Logs
                      </button>
                    )}
                  </>
                );
              })()}
            </div>
          )}
          {card.tokenStats && card.tokenStats.totalTokens > 0 && (
            <div className={styles.tokenStats}>
              <span className={styles.tokenIcon}>T</span>
              <span>{card.tokenStats.totalTokens.toLocaleString()} tokens</span>
            </div>
          )}
          {card.costStats && card.costStats.totalCost > 0 && (
            <div className={styles.costStats}>
              <span className={styles.costIcon}>$</span>
              <span>{formatCost(card.costStats.totalCost)}</span>
            </div>
          )}
        </div>
        {/* Fase 3b-resto: execucao via pipeline orquestrado no backend */}
        <PipelineControls card={card} />
        {card.columnId === 'done' && (
          <>
            <button
              className={styles.createPrButton}
              onClick={(e) => {
                e.stopPropagation();
                // Placeholder: funcionalidade será implementada futuramente
              }}
              aria-label="Create Pull Request"
              title="Criar Pull Request para esta feature"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <path d="M13 3a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm0-1a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM3 13a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm0-1a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm0-10a1 1 0 1 1 0 2 1 1 0 0 1 0-2zM3 1a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm9.5 4.5V8h-1V5.5h1zM4 4.5v7h-1v-7h1zm8.5 8V10h1v2.5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 0-1.5 1.5v.5h-1v-.5A2.5 2.5 0 0 1 5 13h7a.5.5 0 0 0 .5-.5z"/>
              </svg>
              Create PR
            </button>
            {!executionStatus && hasHistoricalLogs && (
              <button
                className={styles.viewLogsButton}
                onClick={async (e) => {
                  e.stopPropagation();
                  setIsLogsOpen(true);
                }}
                aria-label="View execution logs"
                title="Ver histórico de execução"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="16" y1="13" x2="8" y2="13"/>
                  <line x1="16" y1="17" x2="8" y2="17"/>
                  <line x1="10" y1="9" x2="8" y2="9"/>
                </svg>
                View Logs
              </button>
            )}
          </>
        )}
        {workflowStatus && workflowStatus.stage !== 'idle' && (
          <div className={styles.workflowProgress}>
            <span className={styles.progressBadge}>
              {workflowStatus.stage === 'planning' && '📋 Planning...'}
              {workflowStatus.stage === 'implementing' && '⚙️ Implementing...'}
              {workflowStatus.stage === 'testing' && '🧪 Testing...'}
              {workflowStatus.stage === 'reviewing' && '👁️ Reviewing...'}
              {workflowStatus.stage === 'completed' && '✅ Completed'}
              {workflowStatus.stage === 'error' && '❌ Failed'}
            </span>
          </div>
        )}
        <button
          className={styles.editButton}
          onClick={(e) => {
            e.stopPropagation();
            setIsEditOpen(true);
          }}
          aria-label="Edit card"
          title="Edit card (add images)"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M10.5 1.5l2 2-8 8H2.5v-2l8-8z" />
          </svg>
        </button>
        <button
          className={styles.removeButton}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label="Remove card"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M1 1l12 12M13 1L1 13" />
          </svg>
        </button>
      </div>
      {(executionStatus || (card.columnId === 'done' && hasHistoricalLogs)) && (
        <LogsModal
          isOpen={isLogsOpen}
          onClose={() => setIsLogsOpen(false)}
          title={card.title}
          status={executionStatus?.status || 'success'}
          logs={executionStatus?.logs || []}
          startedAt={executionStatus?.startedAt}
          completedAt={executionStatus?.completedAt}
          history={logsHistory}
          costStats={card.costStats}
        />
      )}
      {onUpdateCard && (
        <CardEditModal
          isOpen={isEditOpen}
          onClose={() => setIsEditOpen(false)}
          card={card}
          onUpdateCard={onUpdateCard}
        />
      )}
    </>
  );
}
