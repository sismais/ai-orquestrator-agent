import { Card as CardType, Column as ColumnType, ColumnId, ExecutionStatus, WorkflowStatus, ExecutionHistory } from '../../types';
import { Column } from '../Column/Column';
import styles from './Board.module.css';

interface BoardProps {
  columns: ColumnType[];
  cards: CardType[];
  onAddCard: (title: string, description: string, columnId: ColumnId) => void;
  onRemoveCard: (cardId: string) => void;
  onUpdateCard?: (card: CardType) => void;
  getExecutionStatus?: (cardId: string) => ExecutionStatus | undefined;
  getWorkflowStatus?: (cardId: string) => WorkflowStatus | undefined;
  onRunWorkflow?: (card: CardType) => void;
  isArchivedCollapsed?: boolean;
  onToggleArchivedCollapse?: () => void;
  isCanceladoCollapsed?: boolean;
  onToggleCanceladoCollapse?: () => void;
  fetchLogsHistory?: (cardId: string) => Promise<{ cardId: string; history: ExecutionHistory[] } | null>;
  loadingExpertsCardId?: string | null;
}

export function Board({ columns, cards, onAddCard, onRemoveCard, onUpdateCard, getExecutionStatus, getWorkflowStatus, onRunWorkflow, fetchLogsHistory, loadingExpertsCardId }: BoardProps) {
  return (
    <div className={styles.board}>
      {columns.map(column => (
        <Column
          key={column.id}
          column={column}
          cards={cards.filter(card => card.columnId === column.id)}
          onAddCard={onAddCard}
          onRemoveCard={onRemoveCard}
          onUpdateCard={onUpdateCard}
          getExecutionStatus={getExecutionStatus}
          getWorkflowStatus={getWorkflowStatus}
          onRunWorkflow={onRunWorkflow}
          fetchLogsHistory={fetchLogsHistory}
          loadingExpertsCardId={loadingExpertsCardId}
        />
      ))}
    </div>
  );
}
