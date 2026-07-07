const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:3001';

export interface CreateSessionResponse {
  sessionId: string;
  createdAt: string;
}

export interface SessionHistoryResponse {
  sessionId: string;
  messages: Array<{
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
  }>;
}

/**
 * Create a new chat session scoped to a project
 */
export async function createChatSession(projectId: string): Promise<CreateSessionResponse> {
  const response = await fetch(`${API_URL}/api/chat/sessions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ projectId }),
  });

  if (!response.ok) {
    throw new Error('Failed to create chat session');
  }

  return response.json();
}

/**
 * Get chat session history
 */
export async function getChatHistory(sessionId: string): Promise<SessionHistoryResponse> {
  const response = await fetch(`${API_URL}/api/chat/sessions/${sessionId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error('Failed to fetch chat history');
  }

  return response.json();
}

/**
 * Delete chat session
 */
export async function deleteChatSession(sessionId: string): Promise<void> {
  const response = await fetch(`${API_URL}/api/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    throw new Error('Failed to delete chat session');
  }
}

export const chatApi = {
  createSession: createChatSession,
  getHistory: getChatHistory,
  deleteSession: deleteChatSession,
};
