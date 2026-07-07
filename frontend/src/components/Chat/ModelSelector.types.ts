/**
 * Interface para definir um modelo de IA disponível
 */
export interface AIModel {
  id: string;
  name: string;
  displayName: string; // Nome mais curto para o trigger
  provider: 'anthropic';
  maxTokens: number;
  description: string;
  performance: 'fastest' | 'balanced' | 'powerful';
  badge?: string; // Ex: "Most Popular", "Best Value"
  icon: string; // Emoji ou símbolo
  accent: string; // Classe CSS para cor do provider
  disabled?: boolean; // Modelo em beta, aparece na lista mas não é selecionável
}

/**
 * Props do componente ModelSelector
 */
export interface ModelSelectorProps {
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  disabled?: boolean;
}
