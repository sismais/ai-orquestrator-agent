import { useState, useRef, useCallback, useEffect } from 'react';
import { ChatState, Message } from '../types/chat';
import { v4 as uuidv4 } from 'uuid';
import { useWebSocketBase } from './useWebSocketBase';
import { WS_ENDPOINTS } from '../api/config';
import {
  createChatSession,
  listChatSessions,
  getChatHistory,
  deleteChatSession,
  type ChatSessionSummary,
} from '../api/chat';

interface ChatWebSocketMessage {
  type: 'chunk' | 'end' | 'error';
  content?: string;
  messageId?: string;
  message?: string;
}

export function useChat(projectId: string | null, activeSessionId: string | null) {
  const [state, setState] = useState<ChatState>({
    isOpen: false,
    session: null,
    isLoading: false,
    error: null,
    selectedModel: 'sonnet-5',
    unreadCount: 0,
  });

  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);

  // sessionId só existe depois que a sessão é criada no backend (REST),
  // por isso é estado (não ref): precisa disparar re-render para o WS conectar.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const currentMessageId = useRef<string | null>(null);
  const pendingMessage = useRef<string | null>(null);

  // Lista de conversas do projeto (tela /chat sem conversa aberta).
  useEffect(() => {
    let cancelled = false;

    if (!projectId) {
      setSessions([]);
      return;
    }

    listChatSessions(projectId)
      .then((s) => {
        if (!cancelled) setSessions(s);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Conversa ativa, dirigida pela rota (/chat/:sessionId). Sem sessão ativa,
  // mostra a lista (nenhuma conversa aberta, sem WS conectado).
  useEffect(() => {
    let cancelled = false;
    currentMessageId.current = null;

    if (!projectId || !activeSessionId) {
      setSessionId(null);
      setState((prev) => ({ ...prev, session: null, isLoading: false, error: null }));
      return;
    }

    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    getChatHistory(activeSessionId)
      .then((history) => {
        if (cancelled) return;
        const messages: Message[] = history.messages.map((m) => ({
          id: uuidv4(),
          role: m.role,
          content: m.content,
          timestamp: m.timestamp,
          isStreaming: false,
        }));
        setSessionId(activeSessionId);
        setState((prev) => ({
          ...prev,
          session: {
            id: activeSessionId,
            messages,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            model: prev.selectedModel,
          },
          isLoading: false,
          error: null,
        }));
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('[useChat] Failed to load session:', err);
        setSessionId(null);
        setState((prev) => ({ ...prev, session: null, isLoading: false, error: 'Conversa nao encontrada.' }));
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, activeSessionId]);

  // Keyboard shortcut (Cmd+K or Ctrl+K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        toggleChat();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleMessage = useCallback((data: unknown) => {
    const chatData = data as ChatWebSocketMessage;

    if (chatData.type === 'chunk') {
      // Update streaming message
      setState((prev) => {
        if (!prev.session) return prev;

        const messages = [...prev.session.messages];
        const lastMessage = messages[messages.length - 1];

        if (lastMessage && lastMessage.id === currentMessageId.current) {
          lastMessage.content += chatData.content || '';
          lastMessage.isStreaming = true;
        } else {
          // Start new assistant message
          const newMessage: Message = {
            id: chatData.messageId || uuidv4(),
            role: 'assistant',
            content: chatData.content || '',
            timestamp: new Date().toISOString(),
            isStreaming: true,
          };
          currentMessageId.current = newMessage.id;
          messages.push(newMessage);
        }

        return {
          ...prev,
          session: {
            ...prev.session,
            messages,
            updatedAt: new Date().toISOString(),
          },
        };
      });
    } else if (chatData.type === 'end') {
      // Mark streaming as complete
      setState((prev) => {
        if (!prev.session) return prev;

        const messages = prev.session.messages.map((msg) =>
          msg.id === currentMessageId.current
            ? { ...msg, isStreaming: false }
            : msg
        );

        currentMessageId.current = null;

        return {
          ...prev,
          session: {
            ...prev.session,
            messages,
            updatedAt: new Date().toISOString(),
          },
          isLoading: false,
        };
      });

      // Recarrega a lista pra refletir titulo/updatedAt da conversa recem-respondida.
      if (projectId) {
        listChatSessions(projectId).then(setSessions).catch(() => {});
      }
    } else if (chatData.type === 'error') {
      setState((prev) => ({
        ...prev,
        error: chatData.message || 'An error occurred',
        isLoading: false,
      }));
      currentMessageId.current = null;
    }
  }, [projectId]);

  const handleOpen = useCallback(() => {
    console.log('[ChatWS] Connected');
    setState((prev) => ({ ...prev, error: null }));

    // Clear pending message flag on connect
    pendingMessage.current = null;
  }, []);

  const handleClose = useCallback(() => {
    console.log('[ChatWS] Disconnected');
  }, []);

  const handleError = useCallback(() => {
    setState((prev) => ({
      ...prev,
      error: 'Connection error. Please try again.',
      isLoading: false,
    }));
  }, []);

  const { isConnected, send } = useWebSocketBase({
    url: WS_ENDPOINTS.chat(sessionId ?? ''),
    // Conecta quando a sessão do projeto existe. O Chat é uma página (só visível
    // na aba Chat), então o antigo gate `state.isOpen` (widget flutuante) não se aplica.
    enabled: !!sessionId,
    onMessage: handleMessage,
    onOpen: handleOpen,
    onClose: handleClose,
    onError: handleError,
    name: 'ChatWS',
    maxReconnectAttempts: 10,
    heartbeatInterval: 30000,
  });

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || state.isLoading || !projectId || !sessionId) return;

      // Add user message
      const userMessage: Message = {
        id: uuidv4(),
        role: 'user',
        content: content.trim(),
        timestamp: new Date().toISOString(),
      };

      setState((prev) => {
        if (!prev.session) return prev;

        return {
          ...prev,
          session: {
            ...prev.session,
            messages: [...prev.session.messages, userMessage],
            updatedAt: new Date().toISOString(),
          },
          isLoading: true,
          error: null,
        };
      });

      // Send message (useWebSocketBase handles queuing if not connected)
      const sent = send({
        type: 'message',
        content: content.trim(),
        model: state.selectedModel,
        projectId,
      });

      if (!sent) {
        // Message was queued, it will be sent when connected
        console.log('[ChatWS] Message queued for sending');
      }
    },
    [state.isLoading, state.selectedModel, projectId, sessionId, send]
  );

  const toggleChat = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isOpen: !prev.isOpen,
    }));
  }, []);

  const handleModelChange = useCallback((model: string) => {
    // O modelo vai por mensagem (payload do send); trocar de modelo apenas atualiza
    // o selecionado, sem reiniciar a conversa nem criar sessao nova.
    setState((prev) => ({ ...prev, selectedModel: model }));
  }, []);

  const createSession = useCallback(async (): Promise<string | null> => {
    if (!projectId) return null;

    try {
      const res = await createChatSession(projectId);
      const list = await listChatSessions(projectId);
      setSessions(list);
      return res.sessionId;
    } catch (err) {
      console.error('[useChat] Failed to create session:', err);
      setState((prev) => ({ ...prev, error: 'Falha ao criar nova conversa.' }));
      return null;
    }
  }, [projectId]);

  const deleteSession = useCallback(async (id: string): Promise<void> => {
    try {
      await deleteChatSession(id);
      if (projectId) setSessions(await listChatSessions(projectId));
    } catch (err) {
      console.error('[useChat] Failed to delete session:', err);
    }
  }, [projectId]);

  return {
    state,
    sessions,
    sendMessage,
    handleModelChange,
    createSession,
    deleteSession,
    isConnected,
  };
}
