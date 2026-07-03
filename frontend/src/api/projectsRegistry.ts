/**
 * API client for the project registry endpoints.
 *
 * Distinct from `api/projects.ts` (which loads a single filesystem project
 * into the running backend process). The registry tracks multiple projects
 * so the board can be scoped per project via `projectId`.
 */
import { API_CONFIG } from './config';

export interface RegistryProject {
  id: string;
  name: string;
  path: string;
  rulesFile: string;
  validateCommand: string | null;
  baseBranch: string;
  workflowId: string | null;
  favorite: boolean;
}

const base = () => `${API_CONFIG.BASE_URL}/api/registry/projects`;

export async function listProjects(): Promise<RegistryProject[]> {
  const r = await fetch(base());
  if (!r.ok) throw new Error(`Failed to list projects: ${r.statusText}`);
  return (await r.json()).projects;
}

export async function createProject(input: { name: string; path: string; workflowId?: string }): Promise<RegistryProject> {
  const r = await fetch(base(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: input.name, path: input.path, workflowId: input.workflowId ?? 'dev' }),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(e.detail || `Failed to create project: ${r.statusText}`);
  }
  return (await r.json()).project;
}

export async function deleteProject(id: string): Promise<void> {
  const r = await fetch(`${base()}/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`Failed to delete project: ${r.statusText}`);
}
