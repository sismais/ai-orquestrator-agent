import { useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Card as CardType } from '../../types';
import { PipelineControls } from '../PipelineControls';
import { CardEditModal } from '../CardEditModal';
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
  isLoadingExperts?: boolean;
}

export function Card({ card, onRemove, onUpdateCard, isDragging = false, isLoadingExperts }: CardProps) {
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [removingImageId, setRemovingImageId] = useState<string | null>(null);

  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: card.id,
  });

  const style = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
      }
    : undefined;

  // Click no card abre o modal de edicao (exceto se clicar em botao/area interativa)
  const handleCardClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    // Ignora apenas clicks em elementos <button> reais (nao o proprio card, que tem role=button do dnd)
    if (target.closest('button')) return;
    setIsEditOpen(true);
  };

  // Enter/Space abre o modal (acessibilidade)
  const handleCardKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setIsEditOpen(true);
    }
  };

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

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        className={`${styles.card} ${isDragging ? styles.dragging : ''} ${card.isFixCard ? styles.fixCard : ''} ${card.columnId === 'paused' ? styles.paused : ''}`}
        onClick={handleCardClick}
        onKeyDown={handleCardKeyDown}
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
        {/* Card pausado: selo ambar que abre o modal na aba Interacao */}
        {card.columnId === 'paused' && (
          <button
            className={styles.pausedBadge}
            onClick={(e) => { e.stopPropagation(); setIsEditOpen(true); }}
            title="Responder para retomar o trabalho"
          >
            ⏸ Aguardando você — responder
          </button>
        )}
        {/* Fase 3b-resto: execucao via pipeline orquestrado no backend */}
        <PipelineControls card={card} />
      </div>
      {onUpdateCard && (
        <CardEditModal
          isOpen={isEditOpen}
          onClose={() => setIsEditOpen(false)}
          card={card}
          onUpdateCard={onUpdateCard}
          onRemove={onRemove}
        />
      )}
    </>
  );
}
