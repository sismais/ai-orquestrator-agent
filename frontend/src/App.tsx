import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { DragEndEvent, DragOverEvent, DragStartEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { Card as CardType, Column, ColumnId } from './types';
import { useChat } from './hooks/useChat';
import { useViewPersistence } from './hooks/useViewPersistence';
import { useCardWebSocket, CardMovedMessage, CardUpdatedMessage, CardCreatedMessage } from './hooks/useCardWebSocket';
import { useToast } from './hooks/useToast';
import { ToastContainer } from './components/Toast/ToastContainer';
import { listProjects, type RegistryProject } from './api/projectsRegistry';
import * as cardsApi from './api/cards';
import WorkspaceLayout, { ModuleType } from './layouts/WorkspaceLayout';
import HomePage from './pages/HomePage';
import KanbanPage from './pages/KanbanPage';
import ChatPage from './pages/ChatPage';
import SettingsPage from './pages/SettingsPage';
import styles from './App.module.css';

function App() {
  const { getSavedView, saveView } = useViewPersistence();
  const location = useLocation();
  const navigate = useNavigate();
  const chatMatch = location.pathname.match(/^\/chat(?:\/([^/]+))?\/?$/);
  const isChatRoute = chatMatch !== null;
  const urlChatSessionId = chatMatch?.[1] ?? null;

  // Inicializar com view salva (ou chat, se a URL apontar pra /chat)
  const [currentView, setCurrentView] = useState<ModuleType>(() =>
    window.location.pathname.startsWith('/chat') ? 'chat' : getSavedView()
  );
  const [cards, setCards] = useState<CardType[]>([]);
  const [activeCard, setActiveCard] = useState<CardType | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isArchivedCollapsed, setIsArchivedCollapsed] = useState(false);
  const [isCanceladoCollapsed, setIsCanceladoCollapsed] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(() => localStorage.getItem('orq.currentProjectId'));
  const [registryProjects, setRegistryProjects] = useState<RegistryProject[]>([]);
  const [boardColumns, setBoardColumns] = useState<Column[]>([]);
  const [boardTransitions, setBoardTransitions] = useState<Record<string, string[]>>({});
  const didMountProjectIdEffect = useRef(false);
  const dragStartColumnRef = useRef<ColumnId | null>(null);

  const isValidMove = (from: string, to: string) => (boardTransitions[from] ?? []).includes(to);

  // Mantém currentView em sync quando a navegação do browser (back/forward,
  // link direto) leva pra rota do chat.
  useEffect(() => {
    if (isChatRoute) setCurrentView('chat');
  }, [isChatRoute]);

  // Carrega a configuração do workflow (colunas + transições) do backend
  useEffect(() => {
    import('./api/workflows').then(({ getWorkflow }) =>
      getWorkflow('dev').then(wf => {
        setBoardColumns(wf.columns
          .sort((a, b) => a.order - b.order)
          .map(c => ({ id: c.key as ColumnId, title: c.label } as Column)));
        setBoardTransitions(wf.transitions);
      }).catch(err => console.error('[App] getWorkflow failed', err))
    );
  }, []);

  // Estado para controlar loading de experts
  const [loadingExpertsCardId] = useState<string | null>(null);
  const {
    state: chatState,
    sessions: chatSessions,
    sendMessage,
    handleModelChange,
    createSession,
    deleteSession,
  } = useChat(currentProjectId, urlChatSessionId);

  // Atualiza a coluna do card no estado local (usado pelo drag e pelo WS)
  const moveCard = (cardId: string, newColumnId: ColumnId) => {
    setCards(prev =>
      prev.map(card =>
        card.id === cardId ? { ...card, columnId: newColumnId } : card
      )
    );
  };

  // Toasts globais + contador de cards pausados (A3)
  const { toasts, addToast, removeToast } = useToast();
  const pausedCount = cards.filter(c => c.columnId === 'paused').length;

  // WebSocket para sincronização de cards em tempo real
  const { isConnected: cardsWsConnected } = useCardWebSocket({
    enabled: true,
    onCardMoved: useCallback(async (message: CardMovedMessage) => {
      console.log(`[App] Card moved via WebSocket: ${message.cardId}`);

      // Avisar quando um card pausa e passa a aguardar resposta do usuário.
      // O broadcast WS é global — só avisa se o card for do projeto atual (ou sem projeto).
      const cardProject = message.card?.projectId;
      if (
        message.toColumn === 'paused' &&
        message.fromColumn !== 'paused' &&
        (!cardProject || cardProject === currentProjectId)
      ) {
        addToast({
          type: 'info',
          title: '⏸ Aguardando você',
          message: `"${message.card?.title ?? 'Card'}" pausou e precisa da sua resposta.`,
        });
      }

      // Atualizar o card na lista local
      setCards(prev => prev.map(card =>
        card.id === message.cardId ? message.card : card
      ));
    }, [addToast, currentProjectId]),

    onCardUpdated: useCallback((message: CardUpdatedMessage) => {
      console.log(`[App] Card updated via WebSocket: ${message.cardId}`);

      // Atualizar o card na lista local
      setCards(prev => prev.map(card =>
        card.id === message.cardId ? message.card : card
      ));
    }, []),

    onCardCreated: useCallback((message: CardCreatedMessage) => {
      console.log(`[App] Card created via WebSocket: ${message.cardId}`);

      // Adicionar o novo card à lista (evitar duplicatas)
      setCards(prev => {
        // Verificar se o card já existe (pode ter sido criado localmente)
        if (prev.some(card => card.id === message.cardId)) {
          return prev;
        }
        return [...prev, message.card];
      });
    }, [])
  });

  // Indicador de conexão (opcional - para debug)
  useEffect(() => {
    if (cardsWsConnected) {
      console.log('[App] Cards WebSocket connected');
    } else {
      console.log('[App] Cards WebSocket disconnected');
    }
  }, [cardsWsConnected]);

  // Load cards, active executions, and current project from API on mount
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        // Carrega o catalogo de projetos (registry) para resolver nomes na UI
        // (ex.: badge de projeto no chat). Independente do projeto selecionado.
        listProjects()
          .then(setRegistryProjects)
          .catch(err => console.error('[App] listProjects failed', err));

        // Load cards (scoped to the selected project, when one is set)
        const loadedCards = await cardsApi.fetchCards(currentProjectId ?? undefined);
        setCards(loadedCards);
      } catch (error) {
        console.error('[App] Failed to load cards:', error);
      } finally {
        setIsLoading(false);
      }
    };
    loadInitialData();
  }, []);

  // Re-fetch cards (sem reload de página) sempre que o projeto selecionado mudar.
  // Na primeira montagem, o loadInitialData acima já buscou os cards do projeto
  // salvo em localStorage, então pulamos o fetch duplicado nesse primeiro disparo.
  useEffect(() => {
    if (currentProjectId === null) return;
    localStorage.setItem('orq.currentProjectId', currentProjectId);

    if (!didMountProjectIdEffect.current) {
      didMountProjectIdEffect.current = true;
      return;
    }

    cardsApi.fetchCards(currentProjectId)
      .then(setCards)
      .catch(err => console.error('[App] refetch on project switch failed', err));
  }, [currentProjectId]);

  // Polling para atualizar token stats em tempo real (a cada 2 segundos)
  const hasActiveExecutions = cards.some(c => c.activeExecution?.status === 'running');

  useEffect(() => {
    if (!hasActiveExecutions) {
      return; // Não faz polling se não há execuções ativas
    }

    console.log('[App] Starting token stats polling (active executions detected)');

    const pollTokenStats = async () => {
      try {
        const updatedCards = await cardsApi.fetchCards();

        setCards(prev => {
          // Só atualizar se houver mudanças reais
          const hasChanges = prev.some(card => {
            const updated = updatedCards.find(c => c.id === card.id);
            if (!updated) return false;

            return (
              JSON.stringify(card.tokenStats) !== JSON.stringify(updated.tokenStats) ||
              JSON.stringify(card.activeExecution) !== JSON.stringify(updated.activeExecution) ||
              JSON.stringify(card.diffStats) !== JSON.stringify(updated.diffStats)
            );
          });

          if (!hasChanges) return prev;

          return prev.map(card => {
            const updated = updatedCards.find(c => c.id === card.id);
            return updated ? {
              ...card,
              tokenStats: updated.tokenStats,
              activeExecution: updated.activeExecution,
              diffStats: updated.diffStats,
            } : card;
          });
        });
      } catch (error) {
        console.error('[App] Error polling token stats:', error);
      }
    };

    // Primeira execução imediata
    pollTokenStats();

    const interval = setInterval(pollTokenStats, 2000);
    return () => {
      console.log('[App] Stopping token stats polling');
      clearInterval(interval);
    };
  }, [hasActiveExecutions]); // Dependência mais estável

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    })
  );

  const addCard = async (
    _title: string,
    _description: string,
    columnId: ColumnId
  ) => {
    // Nota: Esta função agora é apenas para compatibilidade
    // O AddCard.tsx cria o card diretamente via API e faz reload da página
    if (columnId !== 'backlog') {
      console.warn('Cards só podem ser criados na raia backlog');
      return;
    }
    // O AddCard já gerencia tudo internamente
  };

  const removeCard = async (cardId: string) => {
    try {
      await cardsApi.deleteCard(cardId);
      setCards(prev => prev.filter(card => card.id !== cardId));
    } catch (error) {
      console.error('[App] Failed to delete card:', error);
      alert('Falha ao remover card.');
    }
  };

  const updateCard = (updatedCard: CardType) => {
    setCards(prev =>
      prev.map(card =>
        card.id === updatedCard.id ? updatedCard : card
      )
    );
  };

  // Função para navegar entre views com persistência
  const handleNavigate = (module: ModuleType) => {
    setCurrentView(module);
    saveView(module);
    navigate(module === 'chat' ? '/chat' : '/');
  };

  // Nome do projeto atualmente selecionado no dropdown (para exibir no chat).
  const currentProjectName = registryProjects.find(p => p.id === currentProjectId)?.name ?? null;

  // Navegação da lista/conversa do chat
  const openChatSession = (id: string) => navigate(`/chat/${id}`);
  const backToChatList = () => navigate('/chat');
  const handleNewChat = async () => {
    const id = await createSession();
    if (id) navigate(`/chat/${id}`);
  };
  const handleDeleteChatSession = async (id: string) => {
    await deleteSession(id);
    if (urlChatSessionId === id) navigate('/chat');
  };

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event;
    const card = cards.find(c => c.id === active.id);
    if (card) {
      setActiveCard(card);
      dragStartColumnRef.current = card.columnId;
    }
  };

  const handleDragOver = (event: DragOverEvent) => {
    const { active, over } = event;
    if (!over) return;

    const activeId = active.id as string;
    const overId = over.id as string;
    const startColumn = dragStartColumnRef.current;

    const activeCardData = cards.find(c => c.id === activeId);
    if (!activeCardData || !startColumn) return;

    // Check if we're over a column
    const isOverColumn = boardColumns.some(col => col.id === overId);
    if (isOverColumn) {
      const newColumnId = overId as ColumnId;
      // Só move visualmente se for uma transição válida ou mesma coluna
      if (activeCardData.columnId !== newColumnId) {
        if (isValidMove(startColumn, newColumnId)) {
          moveCard(activeId, newColumnId);
        }
      }
      return;
    }

    // Check if we're over another card
    const overCard = cards.find(c => c.id === overId);
    if (overCard && activeCardData.columnId !== overCard.columnId) {
      if (isValidMove(startColumn, overCard.columnId)) {
        moveCard(activeId, overCard.columnId);
      }
    }
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    const startColumn = dragStartColumnRef.current;
    setActiveCard(null);
    dragStartColumnRef.current = null;

    if (!over || !startColumn) return;

    const activeId = active.id as string;
    const overId = over.id as string;

    // Get the card and determine final column
    const card = cards.find(c => c.id === activeId);
    if (!card) return;

    let finalColumnId: ColumnId | null = null;

    // Check if dropped on a column
    const isOverColumn = boardColumns.some(col => col.id === overId);
    if (isOverColumn) {
      finalColumnId = overId as ColumnId;
    } else {
      // Dropped on another card - get that card's column
      const overCard = cards.find(c => c.id === overId);
      if (overCard) {
        finalColumnId = overCard.columnId;
      }
    }

    if (!finalColumnId || finalColumnId === startColumn) return;

    // Validar transição conforme config do workflow (backend)
    if (!isValidMove(startColumn, finalColumnId)) {
      // Reverter para coluna original
      moveCard(activeId, startColumn);
      alert(`Transição inválida: ${startColumn} → ${finalColumnId}.\nSiga o fluxo SDLC: backlog → plan → implement → test → review → done`);
      return;
    }

    // Mover card para a coluna final (visual update)
    moveCard(activeId, finalColumnId);

    // Persist move to API
    try {
      await cardsApi.moveCard(activeId, finalColumnId);
    } catch (error) {
      console.error('[App] Failed to persist move:', error);
      moveCard(activeId, startColumn);
      alert('Falha ao mover card. Verifique se o servidor está rodando.');
      return;
    }

    // Fase 3b: o pipeline SDLC deixou de ser disparado pelo drag no browser;
    // a execucao (plan/implement/test/review/PR) roda no runner do backend via PipelineControls.
  };

  const renderView = () => {
    switch (currentView) {
      case 'dashboard':
        return <HomePage cards={cards} onNavigate={handleNavigate} />;

      case 'kanban':
        return (
          <KanbanPage
            columns={boardColumns}
            cards={cards}
            activeCard={activeCard}
            sensors={sensors}
            onDragStart={handleDragStart}
            onDragOver={handleDragOver}
            onDragEnd={handleDragEnd}
            onAddCard={addCard}
            onRemoveCard={removeCard}
            onUpdateCard={updateCard}
            isArchivedCollapsed={isArchivedCollapsed}
            onToggleArchivedCollapse={() => setIsArchivedCollapsed(!isArchivedCollapsed)}
            isCanceladoCollapsed={isCanceladoCollapsed}
            onToggleCanceladoCollapse={() => setIsCanceladoCollapsed(!isCanceladoCollapsed)}
            loadingExpertsCardId={loadingExpertsCardId}
            currentProjectId={currentProjectId}
            onProjectIdSwitch={setCurrentProjectId}
          />
        );

      case 'chat':
        return (
          <ChatPage
            sessions={chatSessions}
            activeSessionId={urlChatSessionId}
            messages={chatState.session?.messages || []}
            isLoading={chatState.isLoading}
            error={chatState.error}
            onSendMessage={sendMessage}
            selectedModel={chatState.selectedModel}
            onModelChange={handleModelChange}
            onOpenSession={openChatSession}
            onNewChat={handleNewChat}
            onDeleteSession={handleDeleteChatSession}
            onBackToList={backToChatList}
            currentProjectId={currentProjectId}
            currentProjectName={currentProjectName}
            sessionProjectId={chatState.session?.projectId ?? null}
            sessionProjectName={chatState.session?.projectName ?? null}
          />
        );

      case 'settings':
        return <SettingsPage />;

      default:
        return <HomePage cards={cards} onNavigate={setCurrentView} />;
    }
  };

  if (isLoading) {
    return (
      <div className={styles.app}>
        <div className={styles.loader}>
          <div className={styles.loaderSpinner}></div>
          <p>Carregando workspace...</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <WorkspaceLayout
        currentModule={currentView}
        onNavigate={handleNavigate}
        currentProjectId={currentProjectId}
        onProjectSwitch={setCurrentProjectId}
        pausedCount={pausedCount}
      >
        {renderView()}
        <div id="modal-root" />
      </WorkspaceLayout>
      <ToastContainer toasts={toasts} onDismiss={removeToast} />
    </>
  );
}

export default App;
