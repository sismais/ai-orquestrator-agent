/**
 * Pricing constants for different AI models.
 * Prices are in USD per 1M tokens (input, output).
 */

import { ModelType } from '../types';

export interface ModelPricing {
  inputPricePerMillion: number;
  outputPricePerMillion: number;
}

export const MODEL_PRICING: Record<ModelType, ModelPricing> = {
  // Claude Models
  'opus-4.8': {
    inputPricePerMillion: 5.00,
    outputPricePerMillion: 25.00,
  },
  'sonnet-5': {
    inputPricePerMillion: 3.00,
    outputPricePerMillion: 15.00,
  },
  'haiku-4.5': {
    inputPricePerMillion: 1.00,
    outputPricePerMillion: 5.00,
  },
  'fable-5': {
    inputPricePerMillion: 10.00,
    outputPricePerMillion: 50.00,
  },
};

/**
 * Calculate cost based on model and token usage.
 */
export function calculateModelCost(
  model: ModelType,
  tokens: { input: number; output: number }
): number {
  const pricing = MODEL_PRICING[model];
  if (!pricing) return 0;

  const inputCost = (tokens.input / 1_000_000) * pricing.inputPricePerMillion;
  const outputCost = (tokens.output / 1_000_000) * pricing.outputPricePerMillion;

  return inputCost + outputCost;
}

/**
 * Estimate cost for a full workflow based on selected models.
 * Uses average token estimates.
 */
export function estimateWorkflowCost(
  modelPlan: ModelType,
  modelImplement: ModelType,
  modelTest: ModelType,
  modelReview: ModelType
): number {
  // Estimativas médias baseadas em histórico
  const avgTokens = {
    plan: { input: 5000, output: 2000 },
    implement: { input: 10000, output: 5000 },
    test: { input: 8000, output: 3000 },
    review: { input: 7000, output: 2500 },
  };

  return (
    calculateModelCost(modelPlan, avgTokens.plan) +
    calculateModelCost(modelImplement, avgTokens.implement) +
    calculateModelCost(modelTest, avgTokens.test) +
    calculateModelCost(modelReview, avgTokens.review)
  );
}
