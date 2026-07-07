import { useState, useRef, useCallback, useEffect } from 'react';
import { ChatState, Message } from '../types/chat';
import { v4 as uuidv4 } from 'uuid';
import { useWebSocketBase } from './useWebSocketBase';
import { WS_ENDPOINTS } from '../api/config';
import { createChatSession } from '../api/chat';

interface ChatWebSocketMessage {
  type: 'chunk' | 'end' | 'error';
  content?: string;
  messageId?: string;
  message?: string;
}

export function useChat(projectId: string | null) {
  const [state, setState] = useState<ChatState>({
    isOpen: false,
    session: null,
    isLoading: false,
    error: null,
    selectedModel: 'sonnet-5',
    unreadCount: 0,
  });

  // sessionId só existe depois que a sessão é criada no backend (REST),
  // por isso é estado (não ref): precisa disparar re-render para o WS conectar.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const currentMessageId = useRef<string | null>(null);
  const pendingMessage = useRef<string | null>(null);

  // Cria a sessão de chat no backend sempre que o projeto selecionado mudar.
  // Sem projeto: nao ha sessao, nao ha conexao WS (empty state fica a cargo da UI).
  useEffect(() => {
    let cancelled = false;

    setSessionId(null);
    currentMessageId.current = null;

    if (!projectId) {
      setState((prev) => ({ ...prev, session: null, error: null, isLoading: false }));
      return;
    }

    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    createChatSession(projectId)
      .then((res) => {
        if (cancelled) return;
        setSessionId(res.sessionId);
        setState((prev) => ({
          ...prev,
          session: {
            id: res.sessionId,
            messages: [],
            createdAt: res.createdAt,
            updatedAt: res.createdAt,
            model: prev.selectedModel,
          },
          isLoading: false,
          error: null,
        }));
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('[useChat] Failed to create chat session:', err);
        setState((prev) => ({ ...prev, isLoading: false, error: 'Falha ao iniciar sessao de chat.' }));
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

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
    } else if (chatData.type === 'error') {
      setState((prev) => ({
        ...prev,
        error: chatData.message || 'An error occurred',
        isLoading: false,
      }));
      currentMessageId.current = null;
    }
  }, []);

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

  const { isConnected, send, reconnect } = useWebSocketBase({
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

  const closeChat = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isOpen: false,
    }));
  }, []);

  const handleModelChange = useCallback((model: string) => {
    setState((prev) => ({ ...prev, selectedModel: model }));

    if (!projectId) return;

    // Reset session when model changes (nova sessão no backend, escopada ao projeto)
    currentMessageId.current = null;
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    createChatSession(projectId)
      .then((res) => {
        setSessionId(res.sessionId);
        setState((prev) => ({
          ...prev,
          session: {
            id: res.sessionId,
            messages: [],
            createdAt: res.createdAt,
            updatedAt: res.createdAt,
            model,
          },
          isLoading: false,
        }));
      })
      .catch((err) => {
        console.error('[useChat] Failed to reset session on model change:', err);
        setState((prev) => ({ ...prev, isLoading: false, error: 'Falha ao trocar de modelo.' }));
      });
  }, [projectId]);

  const createNewSession = useCallback(() => {
    if (!projectId) return;

    currentMessageId.current = null;
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    createChatSession(projectId)
      .then((res) => {
        setSessionId(res.sessionId);
        setState((prev) => ({
          ...prev,
          session: {
            id: res.sessionId,
            messages: [],
            createdAt: res.createdAt,
            updatedAt: res.createdAt,
            model: prev.selectedModel,
          },
          isLoading: false,
          error: null,
        }));

        // Reconnect com a nova sessão (o hook de WS também reage à troca de url/enabled)
        reconnect();
      })
      .catch((err) => {
        console.error('[useChat] Failed to create new session:', err);
        setState((prev) => ({ ...prev, isLoading: false, error: 'Falha ao criar nova sessao.' }));
      });
  }, [projectId, reconnect]);

  return {
    state,
    sendMessage,
    toggleChat,
    closeChat,
    handleModelChange,
    createNewSession,
    isConnected,
  };
}
