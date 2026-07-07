/**
 * Git API client for branch operations
 */
import { API_CONFIG } from './config';

export interface GitBranch {
  name: string;
  type: 'local' | 'remote';
}

export interface BranchesResponse {
  success: boolean;
  branches: GitBranch[];
  defaultBranch: string;
}

export async function fetchGitBranches(projectId: string | null): Promise<BranchesResponse> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  const response = await fetch(`${API_CONFIG.BASE_URL}/api/git/branches${qs}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch branches: ${response.statusText}`);
  }

  return response.json();
}
