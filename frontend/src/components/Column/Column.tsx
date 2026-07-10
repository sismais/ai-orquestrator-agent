import { useDroppable } from '@dnd-kit/core';
import { Card as CardType, Column as ColumnType, ColumnId } from '../../types';
import { Card } from '../Card/Card';
import styles from './Column.module.css';

interface ColumnProps {
  column: ColumnType;
  cards: CardType[];
  onAddCard: (title: string, description: string, columnId: ColumnId) => void;
  onRemoveCard: (cardId: string) => void;
  onUpdateCard?: (card: CardType) => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  loadingExpertsCardId?: string | null;
}

export function Column({ column, cards, onRemoveCard, onUpdateCard, isCollapsed, onToggleCollapse, loadingExpertsCardId }: ColumnProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: column.id,
  });

  // Colapsável apenas quando o chamador fornece um handler de toggle
  // (deixou de depender de ids fixos como 'archived'/'cancelado'/'completed')
  const isCollapsible = Boolean(onToggleCollapse);

  return (
    <div
      ref={setNodeRef}
      className={`${styles.column} ${styles[`column_${column.id}`]} ${isOver ? styles.columnOver : ''} ${isCollapsed ? styles.collapsed : ''}`}
    >
      <div
        className={`${styles.header} ${isCollapsible ? styles.clickableHeader : ''}`}
        onClick={isCollapsible ? onToggleCollapse : undefined}
        style={isCollapsible ? { cursor: 'pointer' } : undefined}
      >
        <div className={styles.headerLeft}>
          <div className={styles.colorDot} />
          <h2 className={styles.title}>{column.title}</h2>
          <span className={styles.count}>{cards.length}</span>
        </div>

        {isCollapsible && (
          <span className={styles.collapseIndicator}>
            {isCollapsed ? '▶' : '▼'}
          </span>
        )}
      </div>

      {!isCollapsed && (
        <div className={styles.cards}>
          {cards.map(card => (
            <Card
              key={card.id}
              card={card}
              onRemove={() => onRemoveCard(card.id)}
              onUpdateCard={onUpdateCard}
              isLoadingExperts={loadingExpertsCardId === card.id}
            />
          ))}
        </div>
      )}

    </div>
  );
}
