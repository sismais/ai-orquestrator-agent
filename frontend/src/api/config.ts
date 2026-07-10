/**
 * Configuração centralizada de APIs
 */
const isProduction = () => {
  if (typeof window === 'undefined') return false;
  return window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1';
};

const getBaseUrl = () => {
  // Se tem variável de ambiente, usar ela
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  // Em produção, usar a mesma origem (URLs relativas via proxy nginx)
  if (isProduction()) {
    return '';  // URL relativa - nginx faz proxy para backend
  }
  // Default para desenvolvimento
  return 'http://localhost:3001';
};

const getWsUrl = () => {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL;
  }
  // Em produção, usar mesmo host com protocolo ws/wss
  if (isProduction()) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}`;
  }
  return 'ws://localhost:3001';
};

export const API_CONFIG = {
  // URL base do backend - getter para avaliação em runtime
  get BASE_URL() { return getBaseUrl(); },

  // URL base do WebSocket - getter para avaliação em runtime
  get WS_URL() { return getWsUrl(); },

  // Timeouts padrão
  TIMEOUT: 30000,

  // Retry configuration
  RETRY_ATTEMPTS: 3,
  RETRY_DELAY: 1000,
};

// Endpoints específicos - usando getters para avaliação em runtime
export const API_ENDPOINTS = {
  // Cards
  get cards() { return `${API_CONFIG.BASE_URL}/api/cards`; },

  // Projects
  projects: {
    get load() { return `${API_CONFIG.BASE_URL}/api/projects/load`; },
    get current() { return `${API_CONFIG.BASE_URL}/api/projects/current`; },
    get recent() { return `${API_CONFIG.BASE_URL}/api/projects/recent`; },
  },

  // Images
  get images() { return `${API_CONFIG.BASE_URL}/api/images`; },

  // Agent
  agent: {
    get stream() { return `${API_CONFIG.BASE_URL}/api/cards`; },
  },

  // Logs
  get logs() { return `${API_CONFIG.BASE_URL}/api/logs`; },

  // Git worktree isolation endpoints
  get branches() { return `${API_CONFIG.BASE_URL}/api/branches`; },
  get cleanupWorktrees() { return `${API_CONFIG.BASE_URL}/api/cleanup-orphan-worktrees`; },

  // Expert agents endpoints
  experts: {
    get triage() { return `${API_CONFIG.BASE_URL}/api/expert-triage`; },
    get sync() { return `${API_CONFIG.BASE_URL}/api/expert-sync`; },
  },

  // Live spectator endpoints
  live: {
    get status() { return `${API_CONFIG.BASE_URL}/api/live/status`; },
    get projects() { return `${API_CONFIG.BASE_URL}/api/live/projects`; },
    get voting() { return `${API_CONFIG.BASE_URL}/api/live/voting`; },
    get vote() { return `${API_CONFIG.BASE_URL}/api/live/vote`; },
  },
};

// WebSocket endpoints centralizados - usando getters para avaliação em runtime
export const WS_ENDPOINTS = {
  // Cards WebSocket
  get cards() { return `${API_CONFIG.WS_URL}/api/cards/ws`; },

  // Execution WebSocket (com cardId dinâmico)
  execution: (cardId: string) => `${API_CONFIG.WS_URL}/api/execution/ws/${cardId}`,

  // Chat WebSocket (com sessionId dinâmico)
  chat: (sessionId: string) => `${API_CONFIG.WS_URL}/api/chat/ws/${sessionId}`,

  // Live spectator WebSocket
  get live() { return `${API_CONFIG.WS_URL}/api/live/ws`; },
};