import { ModelType } from '../../types';
import styles from './ModelCard.module.css';

export interface ModelCardData {
  value: ModelType;
  label: string;
  provider: 'anthropic';
  tagline: string;
  performance: string;
  icon: string;
  accent: string;
  description?: string;
  maxTokens?: number;
  disabled?: boolean; // Modelo em beta, aparece na lista mas não é selecionável
}

interface ModelCardProps {
  model: ModelCardData;
  selected: boolean;
  onSelect: () => void;
  compact?: boolean;
}

// Helper icons for performance indicators
const PerformanceIcon = ({ type }: { type: string }) => {
  const iconClass = styles.perfIcon;

  if (type.toLowerCase().includes('fast') || type.toLowerCase().includes('rapid') || type.toLowerCase().includes('quick')) {
    // Lightning icon for fast models
    return (
      <svg className={iconClass} viewBox="0 0 20 20" fill="none">
        <path d="M10 2L8 8H2L10 18L12 12H18L10 2Z" fill="currentColor"/>
      </svg>
    );
  }

  if (type.toLowerCase().includes('balance') || type.toLowerCase().includes('smart')) {
    // Balanced circle icon
    return (
      <svg className={iconClass} viewBox="0 0 20 20" fill="none">
        <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="2"/>
        <circle cx="10" cy="10" r="3" fill="currentColor"/>
      </svg>
    );
  }

  if (type.toLowerCase().includes('high') || type.toLowerCase().includes('quality') || type.toLowerCase().includes('intelligence')) {
    // Star icon for powerful models
    return (
      <svg className={iconClass} viewBox="0 0 20 20" fill="none">
        <path d="M10 2L12.5 7.5L18 10L12.5 12.5L10 18L7.5 12.5L2 10L7.5 7.5L10 2Z" fill="currentColor"/>
      </svg>
    );
  }

  // Default icon
  return (
    <svg className={iconClass} viewBox="0 0 20 20" fill="none">
      <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="2"/>
    </svg>
  );
};

// Check icon for selected state
const CheckIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M13 4L6 11L3 8" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

export const ModelCard = ({ model, selected, onSelect, compact = false }: ModelCardProps) => {
  return (
    <div
      className={`${styles.modelCard} ${styles[model.accent]} ${selected ? styles.selected : ''} ${compact ? styles.compact : ''} ${model.disabled ? styles.disabled : ''}`}
      onClick={() => {
        if (model.disabled) return;
        onSelect();
      }}
      role="button"
      tabIndex={model.disabled ? -1 : 0}
      aria-selected={selected}
      aria-disabled={model.disabled}
      onKeyDown={(e) => {
        if (model.disabled) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className={styles.cardGlow} />

      <div className={styles.cardHeader}>
        <span className={styles.modelIcon}>{model.icon}</span>
        <div className={styles.modelInfo}>
          <h4 className={styles.modelName}>{model.label}</h4>
          <span className={styles.providerBadge}>{model.provider}</span>
        </div>
      </div>

      <p className={styles.tagline}>{model.tagline}</p>

      <div className={styles.cardFooter}>
        <div className={styles.performanceIndicator}>
          <PerformanceIcon type={model.performance} />
          <span className={styles.performanceLabel}>{model.performance}</span>
        </div>
      </div>

      {selected && (
        <div className={styles.selectedIndicator}>
          <CheckIcon />
        </div>
      )}
    </div>
  );
};
