import { Card as CardType, Column as ColumnType, ColumnId } from '../../types';
import { Column } from '../Column/Column';
import styles from './Board.module.css';
import { useRef, useEffect } from 'react';

interface BoardProps {
  columns: ColumnType[];
  cards: CardType[];
  onAddCard: (title: string, description: string, columnId: ColumnId) => void;
  onRemoveCard: (cardId: string) => void;
  onUpdateCard?: (card: CardType) => void;
  isArchivedCollapsed?: boolean;
  onToggleArchivedCollapse?: () => void;
  isCanceladoCollapsed?: boolean;
  onToggleCanceladoCollapse?: () => void;
  loadingExpertsCardId?: string | null;
}

export function Board({ columns, cards, onAddCard, onRemoveCard, onUpdateCard, loadingExpertsCardId }: BoardProps) {
  const boardRef = useRef<HTMLDivElement | null>(null);
  const footerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const board = boardRef.current;
    const footer = footerRef.current;
    if (!board || !footer) return;

    const spacer = footer.querySelector(`.${styles.footerSpacer}`) as HTMLDivElement | null;

    const updateSpacer = () => {
      if (spacer) spacer.style.width = `${board.scrollWidth}px`;
    };

    const onBoardScroll = () => {
      if (footer) footer.scrollLeft = board.scrollLeft;
    };

    const onFooterScroll = () => {
      if (board) board.scrollLeft = footer.scrollLeft;
    };

    board.addEventListener('scroll', onBoardScroll, { passive: true });
    footer.addEventListener('scroll', onFooterScroll, { passive: true });
    window.addEventListener('resize', updateSpacer);

    // Resize observer to detect content width changes
    let ro: ResizeObserver | null = null;
    try {
      ro = new ResizeObserver(() => updateSpacer());
      ro.observe(board);
    } catch (e) {
      // ignore if ResizeObserver not available
    }

    // initial sync
    updateSpacer();
    footer.scrollLeft = board.scrollLeft;

    return () => {
      board.removeEventListener('scroll', onBoardScroll);
      footer.removeEventListener('scroll', onFooterScroll);
      window.removeEventListener('resize', updateSpacer);
      if (ro) ro.disconnect();
    };
  }, []);

  return (
    <>
      <div className={styles.board} ref={boardRef}>
        {columns.map(column => (
          <Column
            key={column.id}
            column={column}
            cards={cards.filter(card => card.columnId === column.id)}
            onAddCard={onAddCard}
            onRemoveCard={onRemoveCard}
            onUpdateCard={onUpdateCard}
            loadingExpertsCardId={loadingExpertsCardId}
          />
        ))}
      </div>

      {/* Footer scroller: always-visible horizontal scrollbar synced with board */}
      <div className={styles.footerScroller} ref={footerRef} aria-hidden>
        <div className={styles.footerSpacer} />
      </div>
    </>
  );
}
