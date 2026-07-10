import { useState, useRef, useEffect } from 'react';
import { AIModel, ModelSelectorProps } from './ModelSelector.types';
import { useClickOutside } from '../../hooks/useClickOutside';
import styles from './ModelSelector.module.css';

/**
 * Lista de modelos disponíveis com informações detalhadas
 */
export const AVAILABLE_MODELS: AIModel[] = [
  // Claude Models
  {
    id: 'opus-4.8',
    name: 'Claude Opus 4.8',
    displayName: 'Opus 4.8',
    provider: 'anthropic',
    maxTokens: 1000000,
    description: 'Most capable for complex tasks',
    performance: 'powerful',
    icon: '🧠',
    accent: 'opus',
    badge: 'Most Capable'
  },
  {
    id: 'sonnet-5',
    name: 'Claude Sonnet 5',
    displayName: 'Sonnet 5',
    provider: 'anthropic',
    maxTokens: 1000000,
    description: 'Balanced performance',
    performance: 'balanced',
    icon: '⚡',
    accent: 'sonnet',
    badge: 'Best Value'
  },
  {
    id: 'haiku-4.5',
    name: 'Claude Haiku 4.5',
    displayName: 'Haiku 4.5',
    provider: 'anthropic',
    maxTokens: 200000,
    description: 'Fast and efficient',
    performance: 'fastest',
    icon: '🚀',
    accent: 'haiku'
  },
  {
    id: 'fable-5',
    name: 'Claude Fable 5',
    displayName: 'Fable 5',
    provider: 'anthropic',
    maxTokens: 1000000,
    description: 'Beta model for creative and narrative tasks',
    performance: 'powerful',
    icon: '📖',
    accent: 'fable',
    badge: 'Novo'
  }
];

/**
 * Retorna o ícone correspondente ao nível de performance
 */
function getPerformanceIcon(performance: AIModel['performance']): string {
  switch (performance) {
    case 'fastest':
      return '⚡';
    case 'balanced':
      return '⚖️';
    case 'powerful':
      return '💪';
  }
}

/**
 * Componente de seleção de modelo de IA com dropdown customizado
 */
export function ModelSelector({ selectedModel, onModelChange, disabled = false }: ModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const currentModel = AVAILABLE_MODELS.find(m => m.id === selectedModel) || AVAILABLE_MODELS[0];

  // Fecha o dropdown quando clicar fora
  useClickOutside(dropdownRef, () => setIsOpen(false));

  // Suporte a teclado
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen]);

  return (
    <div className={styles.modelSelector} ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        className={styles.trigger}
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-label="Select AI Model"
      >
        <div className={styles.triggerContent}>
          <span className={styles.label}>AI MODEL:</span>
          <div className={styles.selected}>
            <span className={styles.modelIcon}>{currentModel.icon}</span>
            <span className={styles.modelName}>{currentModel.displayName}</span>
            <span className={`${styles.providerBadge} ${styles[currentModel.accent]}`}>
              {currentModel.provider}
            </span>
          </div>
          <svg
            className={`${styles.chevron} ${isOpen ? styles.rotate : ''}`}
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M4 6L8 10L12 6"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className={styles.dropdown} role="listbox">
          <div className={styles.dropdownHeader}>
            <h3>Select AI Model</h3>
            <p>Choose the best model for your task</p>
          </div>

          <div className={styles.modelList}>
            {AVAILABLE_MODELS.map(model => (
              <button
                key={model.id}
                className={`${styles.modelCard} ${model.id === selectedModel ? styles.selectedCard : ''}`}
                onClick={() => {
                  if (model.disabled) return;
                  onModelChange(model.id);
                  setIsOpen(false);
                }}
                disabled={model.disabled}
                role="option"
                aria-selected={model.id === selectedModel}
                aria-disabled={model.disabled}
              >
                <div className={styles.modelHeader}>
                  <span className={styles.modelCardIcon}>{model.icon}</span>
                  <div className={styles.modelTitle}>
                    <h4>{model.name}</h4>
                    {model.badge && <span className={styles.badge}>{model.badge}</span>}
                  </div>
                </div>

                <p className={styles.description}>{model.description}</p>

                <div className={styles.modelMeta}>
                  <span className={`${styles.provider} ${styles[model.accent]}`}>
                    {model.provider}
                  </span>
                  <span className={styles.performance}>
                    <span className={styles.performanceIcon}>{getPerformanceIcon(model.performance)}</span>
                    {model.performance}
                  </span>
                  <span className={styles.tokens}>
                    {(model.maxTokens / 1000).toFixed(0)}K
                  </span>
                </div>

                {model.id === selectedModel && (
                  <div className={styles.selectedIndicator}>
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <path
                        d="M13 4L6 11L3 8"
                        stroke="white"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
