export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  isStreaming?: boolean;
  model?: string;
}

export interface ChatSession {
  id: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
  model?: string;
  projectId?: string | null;
  projectName?: string | null;
}

export interface ChatState {
  isOpen: boolean;
  session: ChatSession | null;
  isLoading: boolean;
  error: string | null;
  selectedModel: string;
  unreadCount: number;
}
