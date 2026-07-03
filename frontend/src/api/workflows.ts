import { API_CONFIG } from './config';

export interface WorkflowColumn {
  key: string;
  label: string;
  order: number;
  agentKey: string | null;
  provider: string;
  model: string | null;
  isPausedState: boolean;
  isTerminal: boolean;
}

export interface WorkflowConfig {
  id: string;
  name: string;
  columns: WorkflowColumn[];
  transitions: Record<string, string[]>;
}

export async function getWorkflow(id: string = 'dev'): Promise<WorkflowConfig> {
  const r = await fetch(`${API_CONFIG.BASE_URL}/api/workflows/${id}`);
  if (!r.ok) throw new Error(`Failed to fetch workflow: ${r.statusText}`);
  return (await r.json()).workflow;
}
