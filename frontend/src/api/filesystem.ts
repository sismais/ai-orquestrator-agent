/**
 * API client for local filesystem browsing (folder picker for project registration).
 */
import { API_CONFIG } from './config';

export interface DirectoryEntry {
  name: string;
  path: string;
}

export interface BrowseResult {
  path: string | null;
  parent: string | null;
  directories: DirectoryEntry[];
}

export async function browseDirectory(path?: string): Promise<BrowseResult> {
  const url = new URL(`${API_CONFIG.BASE_URL}/api/fs/browse`);
  if (path) url.searchParams.set('path', path);
  const r = await fetch(url);
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(e.detail || `Failed to browse directory: ${r.statusText}`);
  }
  return r.json();
}
