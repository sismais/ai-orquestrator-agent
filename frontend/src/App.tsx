import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { DragEndEvent, DragOverEvent, DragStartEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { Card as CardType, Column, ColumnId, ExecutionStatus, WorkflowStatus, WorkflowStage } from './types';
import { useAgentExecution } from './hooks/useAgentExecution';
import { useWorkflowAutomation } from './hooks/useWorkflowAutomation';
import { useChat } from './hooks/useChat';
import { useViewPersistence } from './hooks/useViewPersistence';
import { useCardWebSocket, CardMovedMessage, CardUpdatedMessage, CardCreatedMessage } from './hooks/useCardWebSocket';
import { listProjects, type RegistryProject } from './api/projectsRegistry';
import * as cardsApi from './api/cards';
import WorkspaceLayout, { ModuleType } from './layouts/WorkspaceLayout';
import HomePage from './pages/HomePage';
import KanbanPage from './pages/KanbanPage';
import ChatPage from './pages/ChatPage';
import SettingsPage from './pages/SettingsPage';
import styles from './App.module.css';

// Fase 3b: execucao migra para o runner no backend
const AUTO_RUN_ON_DRAG = false;

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
  const [initialExecutions, setInitialExecutions] = useState<Map<string, ExecutionStatus> | undefined>();
  const [initialWorkflowStatuses, setInitialWorkflowStatuses] = useState<Map<string, WorkflowStatus> | undefined>();
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

  // Callback para atualizar cards quando uma execução completar
  const handleExecutionComplete = async (cardId: string, status: ExecutionStatus) => {
    if (status.status === 'success') {
      try {
        const updatedCard = await cardsApi.fetchCard(cardId);
        setCards(prev => prev.map(card =>
          card.id === cardId ? updatedCard : card
        ));
      } catch (error) {
        console.error('[App] Failed to fetch updated card:', error);
      }
    }
  };

  const { executePlan, executeImplement, executeTest, executeReview, getExecutionStatus, registerCompletionCallback, executions, fetchLogsHistory, executeExpertTriage, executeExpertSync } = useAgentExecution({
    initialExecutions,
    onExecutionComplete: handleExecutionComplete,
  });

  // Estado para controlar loading de experts
  const [loadingExpertsCardId, setLoadingExpertsCardId] = useState<string | null>(null);
  const {
    state: chatState,
    sessions: chatSessions,
    sendMessage,
    handleModelChange,
    createSession,
    deleteSession,
  } = useChat(currentProjectId, urlChatSessionId);

  // Define moveCard and updateCardSpecPath BEFORE useWorkflowAutomation
  const moveCard = (cardId: string, newColumnId: ColumnId) => {
    setCards(prev =>
      prev.map(card =>
        card.id === cardId ? { ...card, columnId: newColumnId } : card
      )
    );
  };

  const updateCardSpecPath = (cardId: string, specPath: string) => {
    setCards(prev =>
      prev.map(card =>
        card.id === cardId ? { ...card, specPath } : card
      )
    );
  };

  const updateCardExperts = (cardId: string, experts: CardType['experts']) => {
    setCards(prev =>
      prev.map(card =>
        card.id === cardId ? { ...card, experts } : card
      )
    );
  };

  const {
    runWorkflow,
    getWorkflowStatus,
    handleCompletedReview,
    // clearWorkflowStatus, // Não está sendo usado no momento
  } = useWorkflowAutomation({
    executePlan,
    executeImplement,
    executeTest,
    executeReview,
    executeExpertTriage,
    onCardMove: moveCard,
    onSpecPathUpdate: updateCardSpecPath,
    onExpertsUpdate: updateCardExperts,
    onLoadingExpertsChange: setLoadingExpertsCardId,
    initialStatuses: initialWorkflowStatuses,
    cards,
    registerCompletionCallback,
    executions,
  });

  // WebSocket para sincronização de cards em tempo real
  const { isConnected: cardsWsConnected } = useCardWebSocket({
    enabled: true,
    onCardMoved: useCallback(async (message: CardMovedMessage) => {
      console.log(`[App] Card moved via WebSocket: ${message.cardId}`);

      // Atualizar o card na lista local
      setCards(prev => prev.map(card =>
        card.id === message.cardId ? message.card : card
      ));

      // Se for um card com workflow em andamento, pode precisar de ações adicionais
      const workflowStatus = getWorkflowStatus(message.cardId);
      if (workflowStatus && workflowStatus.stage !== 'idle') {
        console.log(`[App] Card ${message.cardId} has active workflow, may need recovery`);
      }
    }, [getWorkflowStatus]),

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

        // Construir mapa de execuções ativas e workflow statuses
        // IMPORTANTE: Incluir cards em "done" para manter histórico de logs acessível
        const executionsMap = new Map<string, ExecutionStatus>();
        const workflowMap = new Map<string, WorkflowStatus>();

        for (const card of loadedCards) {
          // Carregar execução para TODOS os cards com activeExecution, incluindo os em "done"
          if (card.activeExecution) {
            console.log(`[App] Found card ${card.id} with activeExecution:`, card.activeExecution);

            // Buscar logs completos da execução se estiver em andamento
            if (card.activeExecution.status === 'running') {
              console.log(`[App] Card ${card.id} is running, fetching logs...`);
              try {
                const logsData = await cardsApi.fetchLogs(card.id);
                console.log(`[App] Fetched logs for card ${card.id}:`, logsData);
                executionsMap.set(card.id, {
                  cardId: card.id,
                  status: logsData.status,
                  startedAt: logsData.startedAt,
                  completedAt: logsData.completedAt,
                  logs: logsData.logs || [],
                  result: logsData.result,
                  workflowStage: logsData.workflowStage, // Incluir workflow stage
                });
              } catch (error) {
                console.warn(`[App] Failed to fetch logs for card ${card.id}:`, error);
                // Usar informações básicas da execução ativa
                executionsMap.set(card.id, {
                  cardId: card.id,
                  status: card.activeExecution.status,
                  startedAt: card.activeExecution.startedAt,
                  completedAt: card.activeExecution.completedAt,
                  logs: [],
                  workflowStage: card.activeExecution.workflowStage, // Incluir workflow stage
                });
              }
            } else {
              // Para execuções completas, apenas usar as informações básicas
              executionsMap.set(card.id, {
                cardId: card.id,
                status: card.activeExecution.status,
                startedAt: card.activeExecution.startedAt,
                completedAt: card.activeExecution.completedAt,
                logs: [],
                workflowStage: card.activeExecution.workflowStage, // Incluir workflow stage
              });
            }

            // Restaurar workflow state se existir
            const activeExecWithWorkflow = card.activeExecution as any;
            if (activeExecWithWorkflow.workflowStage) {
              // Mapear valores antigos para os novos (compatibilidade)
              const stageMap: Record<string, WorkflowStage> = {
                'plan': 'planning',
                'implement': 'implementing',
                'test': 'testing',
                'test-implementation': 'testing',
                'review': 'reviewing',
                // Valores já corretos
                'planning': 'planning',
                'implementing': 'implementing',
                'testing': 'testing',
                'reviewing': 'reviewing',
                'completed': 'completed',
                'error': 'error',
                'idle': 'idle',
              };
              const mappedStage = stageMap[activeExecWithWorkflow.workflowStage] || 'planning';

              workflowMap.set(card.id, {
                cardId: card.id,
                stage: mappedStage,
                currentColumn: card.columnId,
                error: activeExecWithWorkflow.workflowError,
              });
            }
          }
        }

        if (executionsMap.size > 0) {
          setInitialExecutions(executionsMap);
        }

        if (workflowMap.size > 0) {
          setInitialWorkflowStatuses(workflowMap);
        }
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

  // Polling para monitorar merge automático em background
  const mergingCardsRef = useRef<CardType[]>([]);

  useEffect(() => {
    // Atualizar ref
    mergingCardsRef.current = cards.filter(c =>
      c.mergeStatus === 'resolving' || c.mergeStatus === 'merging'
    );

    if (mergingCardsRef.current.length === 0) {
      return; // Nada para monitorar
    }

    console.log(`[App] Monitoring ${mergingCardsRef.current.length} card(s) with merges in progress`);

    const pollMergeStatus = async () => {
      try {
        const updatedCards = await cardsApi.fetchCards();
        const currentMergingCards = mergingCardsRef.current;

        for (const oldCard of currentMergingCards) {
          const updatedCard = updatedCards.find(c => c.id === oldCard.id);

          if (!updatedCard) continue;

          // Se o merge foi completado com sucesso
          if (updatedCard.mergeStatus === 'merged' && updatedCard.columnId === 'review') {
            console.log(`[App] Merge completed for card ${updatedCard.id}, moving to Done`);

            // Mover para done
            await cardsApi.moveCard(updatedCard.id, 'done');

            // Atualizar estado local
            setCards(prev => prev.map(c =>
              c.id === updatedCard.id
                ? { ...updatedCard, columnId: 'done', mergeStatus: 'merged' }
                : c
            ));
          }
          // Se o merge falhou
          else if (updatedCard.mergeStatus === 'failed') {
            console.error(`[App] Merge failed for card ${updatedCard.id}`);

            // Atualizar estado local com o status de falha
            setCards(prev => prev.map(c =>
              c.id === updatedCard.id
                ? { ...updatedCard }
                : c
            ));
          }
          // Se ainda está resolvendo, atualizar o card
          else if (updatedCard.mergeStatus === 'resolving') {
            setCards(prev => prev.map(c =>
              c.id === updatedCard.id
                ? { ...updatedCard }
                : c
            ));
          }
        }
      } catch (error) {
        console.error('[App] Error polling merge status:', error);
      }
    };

    const interval = setInterval(pollMergeStatus, 5000);
    return () => clearInterval(interval);
  }, [cards.filter(c => c.mergeStatus === 'resolving' || c.mergeStatus === 'merging').length]); // Dependência mais específica

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

    // Triggers baseados na transição
    // Fase 3b: pipeline SDLC deixa de ser disparado pelo drag no browser;
    // execução migra para o runner no backend. Ladder mantida (desligada) até lá.
    if (AUTO_RUN_ON_DRAG) {
      if (startColumn === 'backlog' && finalColumnId === 'plan') {
        console.log(`[App] Card moved from backlog to plan: ${card.title}`);

        // 1. Execute expert triage first (blocking)
        setLoadingExpertsCardId(card.id);
        console.log(`[App] Starting expert triage for card: ${card.title}`);
        const triageResult = await executeExpertTriage(card);
        setLoadingExpertsCardId(null);

        // 2. Update card with identified experts
        if (triageResult.success && Object.keys(triageResult.experts).length > 0) {
          updateCardExperts(card.id, triageResult.experts);
          console.log(`[App] Identified experts:`, Object.keys(triageResult.experts));
        }

        // 3. Execute plan with expert context
        const cardWithExperts = { ...card, experts: triageResult.experts };
        const result = await executePlan(cardWithExperts);
        if (result.success && result.specPath) {
          updateCardSpecPath(card.id, result.specPath);
          console.log(`[App] Spec path saved: ${result.specPath}`);
        }
      } else if (startColumn === 'plan' && finalColumnId === 'implement') {
        // Buscar o card atualizado (pode ter specPath agora)
        const updatedCard = cards.find(c => c.id === activeId);
        if (updatedCard?.specPath) {
          console.log(`[App] Card moved from plan to implement: ${updatedCard.title}`);
          console.log(`[App] Executing /implement with spec: ${updatedCard.specPath}`);
          executeImplement(updatedCard);
        } else {
          alert('Este card não possui um plano associado. Execute primeiro a etapa de planejamento.');
          moveCard(activeId, startColumn);
        }
      } else if (startColumn === 'implement' && finalColumnId === 'test') {
        // Trigger: implement → test - Executar /test-implementation
        const updatedCard = cards.find(c => c.id === activeId);
        if (updatedCard?.specPath) {
          console.log(`[App] Card moved from implement to test: ${updatedCard.title}`);
          console.log(`[App] Executing /test-implementation with spec: ${updatedCard.specPath}`);
          executeTest(updatedCard);
        } else {
          alert('Este card não possui um plano associado. Execute primeiro a etapa de planejamento.');
          moveCard(activeId, startColumn);
        }
      } else if (startColumn === 'test' && finalColumnId === 'review') {
        // Trigger: test → review - Executar /review
        const updatedCard = cards.find(c => c.id === activeId);
        if (updatedCard?.specPath) {
          console.log(`[App] Card moved from test to review: ${updatedCard.title}`);
          console.log(`[App] Executing /review with spec: ${updatedCard.specPath}`);
          executeReview(updatedCard);
        } else {
          alert('Este card não possui um plano associado. Execute primeiro a etapa de planejamento.');
          moveCard(activeId, startColumn);
        }
      } else if (startColumn === 'review' && finalColumnId === 'done') {
        // Trigger: review → done - Fazer merge automático e sync de experts
        const updatedCard = cards.find(c => c.id === activeId);
        if (updatedCard?.branchName) {
          console.log(`[App] Card moved from review to done: ${updatedCard.title}`);
          console.log(`[App] Starting automatic merge for branch: ${updatedCard.branchName}`);

          // Tentar fazer merge
          const mergeResult = await handleCompletedReview(updatedCard.id);

          if (mergeResult.success) {
            console.log(`[App] Merge successful for card: ${updatedCard.title}`);
          } else if (mergeResult.status === 'resolving') {
            console.log(`[App] Merge has conflicts, AI is resolving automatically`);
            // Card já está em done, merge será completado em background
          } else {
            console.error(`[App] Merge failed: ${mergeResult.error}`);
            alert(`Falha ao fazer merge: ${mergeResult.error}\nO card foi movido para Done, mas o merge precisa ser feito manualmente.`);
          }
        } else {
          console.log(`[App] Card has no branch, skipping merge`);
        }

        // Execute expert sync in background (non-blocking)
        if (updatedCard?.experts && Object.keys(updatedCard.experts).length > 0) {
          console.log(`[App] Starting expert sync for card: ${updatedCard.title}`);
          executeExpertSync(updatedCard).then(result => {
            if (result.success) {
              console.log(`[App] Expert sync completed:`, result.syncedExperts);
            } else {
              console.error(`[App] Expert sync failed:`, result.error);
            }
          });
        }
      }
    }
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
            getExecutionStatus={getExecutionStatus}
            getWorkflowStatus={getWorkflowStatus}
            onRunWorkflow={runWorkflow}
            isArchivedCollapsed={isArchivedCollapsed}
            onToggleArchivedCollapse={() => setIsArchivedCollapsed(!isArchivedCollapsed)}
            isCanceladoCollapsed={isCanceladoCollapsed}
            onToggleCanceladoCollapse={() => setIsCanceladoCollapsed(!isCanceladoCollapsed)}
            fetchLogsHistory={fetchLogsHistory}
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
    <WorkspaceLayout
      currentModule={currentView}
      onNavigate={handleNavigate}
      currentProjectId={currentProjectId}
      onProjectSwitch={setCurrentProjectId}
    >
      {renderView()}
      <div id="modal-root" />
    </WorkspaceLayout>
  );
}

export default App;
