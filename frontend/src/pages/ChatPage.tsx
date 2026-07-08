import { useEffect, useRef } from 'react';
import { Message } from '../types/chat';
import { type ChatSessionSummary } from '../api/chat';
import ChatMessage from '../components/Chat/ChatMessage';
import ChatInput from '../components/Chat/ChatInput';
import { ModelSelector } from '../components/Chat/ModelSelector';
import { MessageSquarePlus, Trash2, ArrowLeft } from 'lucide-react';
import styles from './ChatPage.module.css';

interface ChatPageProps {
  sessions: ChatSessionSummary[];
  activeSessionId: string | null;
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  onSendMessage: (content: string) => void;
  selectedModel: string;
  onModelChange: (model: string) => void;
  onOpenSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  onBackToList: () => void;
  currentProjectId: string | null;
}

/** Formata data em texto relativo simples (ex.: "ha 2h", "ontem"). */
function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) return 'agora';
  if (diffMin < 60) return `há ${diffMin}min`;

  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `há ${diffH}h`;

  const diffD = Math.floor(diffH / 24);
  if (diffD === 1) return 'ontem';
  if (diffD < 7) return `há ${diffD}d`;

  return date.toLocaleDateString('pt-BR');
}

const ChatPage = ({
  sessions,
  activeSessionId,
  messages,
  isLoading,
  error,
  onSendMessage,
  selectedModel,
  onModelChange,
  onOpenSession,
  onNewChat,
  onDeleteSession,
  onBackToList,
  currentProjectId,
}: ChatPageProps) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isConversationView = !!activeSessionId;

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className={styles.chatPage}>
      <div className={styles.chatHeader}>
        <div className={styles.chatInfo}>
          {isConversationView && (
            <button className={styles.backButton} onClick={onBackToList}>
              <ArrowLeft size={16} />
              <span>Conversas</span>
            </button>
          )}
          <h1 className={styles.chatTitle}>{isConversationView ? 'AI Assistant' : 'Conversas'}</h1>
          <p className={styles.chatSubtitle}>
            {isConversationView
              ? 'Converse com o assistente inteligente do projeto'
              : 'Suas conversas com o assistente do projeto'}
          </p>
        </div>
        <div className={styles.chatActions}>
          <button
            className={styles.newChatButton}
            onClick={onNewChat}
            title="Iniciar nova conversa"
            disabled={isLoading || !currentProjectId}
          >
            <MessageSquarePlus size={18} />
            <span>New Chat</span>
          </button>
          {isConversationView && (
            <>
              <ModelSelector
                selectedModel={selectedModel}
                onModelChange={onModelChange}
                disabled={isLoading}
              />
              <div className={styles.chatStatus}>
                <div className={styles.statusIndicator}></div>
                <span className={styles.statusText}>Online</span>
              </div>
            </>
          )}
        </div>
      </div>

      <div className={styles.chatContainer}>
        {!currentProjectId ? (
          <div className={styles.messagesArea}>
            <div className={styles.messagesContainer}>
              <div className={styles.emptyState}>
                <div className={styles.emptyIcon}>📁</div>
                <h2 className={styles.emptyTitle}>Selecione um projeto</h2>
                <p className={styles.emptyText}>
                  Escolha um projeto no topo da tela para conversar com o assistente.
                </p>
              </div>
            </div>
          </div>
        ) : !isConversationView ? (
          <div className={styles.messagesArea}>
            <div className={styles.sessionListContainer}>
              {sessions.length === 0 ? (
                <div className={styles.emptyState}>
                  <div className={styles.emptyIcon}>💬</div>
                  <h2 className={styles.emptyTitle}>Nenhuma conversa ainda</h2>
                  <p className={styles.emptyText}>Clique em "New Chat" pra começar.</p>
                </div>
              ) : (
                <ul className={styles.sessionList}>
                  {sessions.map((s) => (
                    <li
                      key={s.sessionId}
                      className={styles.sessionItem}
                      onClick={() => onOpenSession(s.sessionId)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') onOpenSession(s.sessionId);
                      }}
                    >
                      <div className={styles.sessionInfo}>
                        <span className={styles.sessionTitle}>{s.title || 'Nova conversa'}</span>
                        <span className={styles.sessionDate}>{formatRelativeTime(s.updatedAt)}</span>
                      </div>
                      <button
                        className={styles.deleteSessionButton}
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(s.sessionId);
                        }}
                        title="Excluir conversa"
                        aria-label="Excluir conversa"
                      >
                        <Trash2 size={16} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className={styles.messagesArea}>
              <div className={styles.messagesContainer}>
                {messages.length === 0 ? (
                  <div className={styles.emptyState}>
                    <div className={styles.emptyIcon}>💬</div>
                    <h2 className={styles.emptyTitle}>Bem-vindo ao AI Assistant</h2>
                    <p className={styles.emptyText}>
                      Inicie uma conversa com seu assistente de IA
                    </p>
                    <p className={styles.emptySubtext}>
                      Faça perguntas sobre seu projeto, peça ajuda com código, ou explore ideias!
                    </p>
                    <div className={styles.suggestions}>
                      <h3 className={styles.suggestionsTitle}>Sugestões:</h3>
                      <button
                        className={styles.suggestionButton}
                        onClick={() => onSendMessage("Como posso melhorar meu código?")}
                      >
                        Como posso melhorar meu código?
                      </button>
                      <button
                        className={styles.suggestionButton}
                        onClick={() => onSendMessage("Explique o padrão SDLC")}
                      >
                        Explique o padrão SDLC
                      </button>
                      <button
                        className={styles.suggestionButton}
                        onClick={() => onSendMessage("Ajude-me a organizar minhas tarefas")}
                      >
                        Ajude-me a organizar minhas tarefas
                      </button>
                    </div>
                  </div>
                ) : (
                  messages.map((message) => (
                    <ChatMessage key={message.id} message={message} />
                  ))
                )}
                {isLoading && (
                  <div className={styles.typingIndicator}>
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                )}
                {error && (
                  <div className={styles.errorMessage}>
                    <span className={styles.errorIcon}>⚠️</span>
                    {error}
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            </div>

            <div className={styles.inputArea}>
              <ChatInput onSend={onSendMessage} disabled={isLoading} />
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ChatPage;
