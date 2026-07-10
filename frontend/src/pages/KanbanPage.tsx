import { DndContext, DragOverlay, closestCorners } from '@dnd-kit/core';
import { Card as CardType, Column, ColumnId } from '../types';
import { Board } from '../components/Board/Board';
import { Card } from '../components/Card/Card';
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
  isArchivedCollapsed: boolean;
  onToggleArchivedCollapse: () => void;
  isCanceladoCollapsed: boolean;
  onToggleCanceladoCollapse: () => void;
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
  isArchivedCollapsed,
  onToggleArchivedCollapse,
  isCanceladoCollapsed,
  onToggleCanceladoCollapse,
  loadingExpertsCardId,
  currentProjectId,
  onProjectIdSwitch: _onProjectIdSwitch,
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
            isArchivedCollapsed={isArchivedCollapsed}
            onToggleArchivedCollapse={onToggleArchivedCollapse}
            isCanceladoCollapsed={isCanceladoCollapsed}
            onToggleCanceladoCollapse={onToggleCanceladoCollapse}
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
