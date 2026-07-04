import { DndContext, DragOverlay, closestCorners } from '@dnd-kit/core';
import { Card as CardType, Column, ColumnId, ExecutionStatus, WorkflowStatus } from '../types';
import { Board } from '../components/Board/Board';
import { Card } from '../components/Card/Card';
import { ProjectSelectorRegistry } from '../components/ProjectSelectorRegistry/ProjectSelectorRegistry';
import { AddCard } from '../components/AddCard/AddCard';
import styles from './KanbanPage.module.css';

interface KanbanPageProps {
  columns: Column[];
  cards: CardType[];
  activeCard: CardType | null;
  sensors: any;
  onDragStart: (event: any) => void;
  onDragOver: (event: any) => void;
  onDragEnd: (event: any) => void;
  onAddCard: (title: string, description: string, columnId: ColumnId) => void;
  onRemoveCard: (cardId: string) => void;
  onUpdateCard: (card: CardType) => void;
  getExecutionStatus: (cardId: string) => ExecutionStatus | undefined;
  getWorkflowStatus: (cardId: string) => WorkflowStatus | undefined;
  onRunWorkflow: (card: CardType) => void;
  isArchivedCollapsed: boolean;
  onToggleArchivedCollapse: () => void;
  isCanceladoCollapsed: boolean;
  onToggleCanceladoCollapse: () => void;
  fetchLogsHistory?: (cardId: string) => Promise<{ cardId: string; history: any[] } | null>;
  loadingExpertsCardId?: string | null;
  currentProjectId: string | null;
  onProjectIdSwitch: (projectId: string) => void;
}

const KanbanPage = ({
  columns,
  cards,
  activeCard,
  sensors,
  onDragStart,
  onDragOver,
  onDragEnd,
  onAddCard,
  onRemoveCard,
  onUpdateCard,
  getExecutionStatus,
  getWorkflowStatus,
  onRunWorkflow,
  isArchivedCollapsed,
  onToggleArchivedCollapse,
  isCanceladoCollapsed,
  onToggleCanceladoCollapse,
  fetchLogsHistory,
  loadingExpertsCardId,
  currentProjectId,
  onProjectIdSwitch,
}: KanbanPageProps) => {
  return (
    <div className={styles.kanbanPage}>
      <div className={styles.kanbanHeader}>
        <div className={styles.kanbanInfo}>
          <h1 className={styles.kanbanTitle}>Workflow Board</h1>
          <p className={styles.kanbanSubtitle}>
            Gerencie seu workflow com automação SDLC
          </p>
        </div>
        <div className={styles.projectActions}>
          <ProjectSelectorRegistry
            currentProjectId={currentProjectId}
            onSwitch={onProjectIdSwitch}
          />
          <AddCard columnId="backlog" onAdd={onAddCard} projectId={currentProjectId} />
        </div>
      </div>

      <div className={styles.kanbanContent}>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={onDragStart}
          onDragOver={onDragOver}
          onDragEnd={onDragEnd}
        >
          <Board
            columns={columns}
            cards={cards}
            onAddCard={onAddCard}
            onRemoveCard={onRemoveCard}
            onUpdateCard={onUpdateCard}
            getExecutionStatus={getExecutionStatus}
            getWorkflowStatus={getWorkflowStatus}
            onRunWorkflow={onRunWorkflow}
            isArchivedCollapsed={isArchivedCollapsed}
            onToggleArchivedCollapse={onToggleArchivedCollapse}
            isCanceladoCollapsed={isCanceladoCollapsed}
            onToggleCanceladoCollapse={onToggleCanceladoCollapse}
            fetchLogsHistory={fetchLogsHistory}
            loadingExpertsCardId={loadingExpertsCardId}
          />
          <DragOverlay>
            {activeCard ? (
              <Card
                card={activeCard}
                onRemove={() => {}}
                isDragging
              />
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>
    </div>
  );
};

export default KanbanPage;
