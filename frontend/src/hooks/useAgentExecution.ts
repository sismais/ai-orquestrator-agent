import { useState, useCallback, useRef, useEffect } from "react";
import { Card, ExecutionStatus, ExecutionLog, CardExecutionHistory, CardExperts } from "../types";
import { API_ENDPOINTS } from "../api/config";

const POLLING_INTERVAL = 1500; // Poll every 1.5 seconds

interface ExecutePlanResult {
  success: boolean;
  specPath?: string;
  result?: string;
  error?: string;
}

interface ExpertTriageResult {
  success: boolean;
  cardId: string;
  experts: CardExperts;
  error?: string;
}

interface SyncedExpert {
  expertId: string;
  synced: boolean;
  filesChanged: string[];
  message?: string;
}

interface ExpertSyncResult {
  success: boolean;
  cardId: string;
  syncedExperts: SyncedExpert[];
  error?: string;
}

interface ExecuteImplementResult {
  success: boolean;
  result?: string;
  error?: string;
}

// Callback type for execution completion
type ExecutionCompletionCallback = (execution: ExecutionStatus) => void;

interface UseAgentExecutionProps {
  initialExecutions?: Map<string, ExecutionStatus>;
  onExecutionComplete?: (cardId: string, status: ExecutionStatus) => void;
}

export function useAgentExecution(props?: UseAgentExecutionProps | Map<string, ExecutionStatus>) {
  // Support both old API (just Map) and new API (props object)
  const initialExecutions = props instanceof Map ? props : props?.initialExecutions;
  const onExecutionComplete = props instanceof Map ? undefined : props?.onExecutionComplete;
  const [executions, setExecutions] = useState<Map<string, ExecutionStatus>>(new Map());
  const pollingIntervalsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // Callbacks to be called when an execution completes (for workflow recovery)
  const completionCallbacksRef = useRef<Map<string, ExecutionCompletionCallback>>(new Map());
  // Track executions that completed while waiting for callback registration
  const pendingCompletionsRef = useRef<Map<string, ExecutionStatus>>(new Map());
  // Track if initial load is done to prevent duplicate polling
  const initialLoadDoneRef = useRef(false);

  // Cleanup polling intervals on unmount
  useEffect(() => {
    return () => {
      pollingIntervalsRef.current.forEach((interval) => clearInterval(interval));
      pollingIntervalsRef.current.clear();
    };
  }, []);

  // Update executions state when initialExecutions becomes available
  useEffect(() => {
    if (initialExecutions && initialExecutions.size > 0 && !initialLoadDoneRef.current) {
      console.log(`[useAgentExecution] Loading ${initialExecutions.size} initial executions`);
      setExecutions(new Map(initialExecutions));
    }
  }, [initialExecutions]);

  // Restore polling for running executions when initialExecutions becomes available
  useEffect(() => {
    if (initialExecutions && initialExecutions.size > 0 && !initialLoadDoneRef.current) {
      initialLoadDoneRef.current = true;
      console.log(`[useAgentExecution] Restoring ${initialExecutions.size} executions`);

      // Small delay to allow callback registration from useWorkflowAutomation
      setTimeout(() => {
        initialExecutions.forEach((execution, cardId) => {
          if (execution.status === 'running') {
            console.log(`[useAgentExecution] Restoring polling for card: ${cardId}`, execution);
            startPolling(cardId);
          }
        });
      }, 100);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialExecutions]); // startPolling is stable, we only care about initialExecutions changing

  // Function to fetch logs from API
  const fetchLogs = useCallback(async (cardId: string) => {
    try {
      const response = await fetch(`${API_ENDPOINTS.logs}/${cardId}`);
      if (!response.ok) return null;
      const data = await response.json();
      if (data.success && data.execution) {
        return data.execution;
      }
      return null;
    } catch (error) {
      console.error(`[useAgentExecution] Failed to fetch logs for ${cardId}:`, error);
      return null;
    }
  }, []);

  // Function to fetch full execution history from API
  const fetchLogsHistory = useCallback(async (cardId: string): Promise<CardExecutionHistory | null> => {
    try {
      const response = await fetch(`${API_ENDPOINTS.logs}/${cardId}/history`);
      if (!response.ok) return null;
      const data = await response.json();
      if (data.success) {
        return {
          cardId: data.cardId,
          history: data.history
        };
      }
      return null;
    } catch (error) {
      console.error(`[useAgentExecution] Failed to fetch logs history for ${cardId}:`, error);
      return null;
    }
  }, []);

  // Start polling for a card
  const startPolling = useCallback((cardId: string) => {
    // Don't start if already polling
    if (pollingIntervalsRef.current.has(cardId)) return;

    console.log(`[useAgentExecution] Starting log polling for card: ${cardId}`);

    // Immediate fetch to update UI right away (don't wait for interval)
    const doFetch = async () => {
      const execution = await fetchLogs(cardId);
      if (execution) {
        setExecutions((prev) => {
          const next = new Map(prev);
          const current = next.get(cardId);

          // Only update if we have new logs or status changed
          if (!current || execution.logs.length > (current.logs?.length || 0) || current.status !== execution.status) {
            next.set(cardId, {
              cardId: execution.cardId,
              status: execution.status,
              result: execution.result,
              logs: execution.logs || [],
              startedAt: execution.startedAt,
              completedAt: execution.completedAt,
            });
          }

          // Stop polling if execution completed
          if (execution.status !== 'running') {
            stopPolling(cardId);

            // Call global onExecutionComplete callback if provided
            const completedExecution = next.get(cardId);
            if (onExecutionComplete && completedExecution) {
              console.log(`[useAgentExecution] Calling global onExecutionComplete for card: ${cardId}`);
              setTimeout(() => onExecutionComplete(cardId, completedExecution), 0);
            }

            // Call completion callback if registered
            const callback = completionCallbacksRef.current.get(cardId);
            if (callback && completedExecution) {
              console.log(`[useAgentExecution] Calling completion callback for card: ${cardId}`);
              setTimeout(() => callback(completedExecution), 0);
              completionCallbacksRef.current.delete(cardId);
            } else if (completedExecution) {
              console.log(`[useAgentExecution] No callback registered for card: ${cardId}, saving as pending completion`);
              pendingCompletionsRef.current.set(cardId, completedExecution);
            }
          }

          return next;
        });
      }
    };

    // Do immediate fetch
    doFetch();

    const interval = setInterval(async () => {
      const execution = await fetchLogs(cardId);
      if (execution) {
        setExecutions((prev) => {
          const next = new Map(prev);
          const current = next.get(cardId);

          // Only update if we have new logs
          if (!current || execution.logs.length > (current.logs?.length || 0)) {
            next.set(cardId, {
              cardId: execution.cardId,
              status: execution.status,
              result: execution.result,
              logs: execution.logs || [],
              startedAt: execution.startedAt,
              completedAt: execution.completedAt,
            });
          }

          // Stop polling if execution completed
          if (execution.status !== 'running') {
            stopPolling(cardId);

            // Call global onExecutionComplete callback if provided
            const completedExecution = next.get(cardId);
            if (onExecutionComplete && completedExecution) {
              console.log(`[useAgentExecution] Calling global onExecutionComplete for card: ${cardId}`);
              setTimeout(() => onExecutionComplete(cardId, completedExecution), 0);
            }

            // Call completion callback if registered (for workflow recovery)
            const callback = completionCallbacksRef.current.get(cardId);
            if (callback && completedExecution) {
              console.log(`[useAgentExecution] Calling completion callback for card: ${cardId}`);
              // Use setTimeout to ensure state is updated before callback
              setTimeout(() => callback(completedExecution), 0);
              completionCallbacksRef.current.delete(cardId);
            } else if (completedExecution) {
              // Save completion for later if callback not yet registered
              console.log(`[useAgentExecution] No callback registered for card: ${cardId}, saving as pending completion`);
              pendingCompletionsRef.current.set(cardId, completedExecution);
            }
          }

          return next;
        });
      }
    }, POLLING_INTERVAL);

    pollingIntervalsRef.current.set(cardId, interval);
  }, [fetchLogs]);

  // Stop polling for a card
  const stopPolling = useCallback((cardId: string) => {
    const interval = pollingIntervalsRef.current.get(cardId);
    if (interval) {
      console.log(`[useAgentExecution] Stopping log polling for card: ${cardId}`);
      clearInterval(interval);
      pollingIntervalsRef.current.delete(cardId);
    }
  }, []);

  const executePlan = useCallback(async (card: Card): Promise<ExecutePlanResult> => {
    console.log(`[useAgentExecution] Starting plan execution for: ${card.title}`);

    // Set status to running with initial log
    const initialLogs: ExecutionLog[] = [
      {
        timestamp: new Date().toISOString(),
        type: "info",
        content: `Iniciando execução do plano para: ${card.title}`,
      },
    ];

    setExecutions((prev) => {
      const next = new Map(prev);
      next.set(card.id, {
        cardId: card.id,
        status: "running",
        logs: initialLogs,
        startedAt: new Date().toISOString(),
      });
      return next;
    });

    // Start polling for real-time logs
    startPolling(card.id);

    try {
      const response = await fetch(API_ENDPOINTS.execution.plan, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cardId: card.id,
          title: card.title,
          description: card.description,
        }),
      });

      const result = await response.json();
      const logs: ExecutionLog[] = result.logs || [];

      // Stop polling and update final state
      stopPolling(card.id);

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: result.success ? "success" : "error",
          result: result.result || result.error,
          logs: logs,
          completedAt: new Date().toISOString(),
        });
        return next;
      });

      console.log(`[useAgentExecution] Plan execution completed:`, result);
      return {
        success: result.success,
        specPath: result.specPath,
        result: result.result,
        error: result.error,
      };
    } catch (error) {
      stopPolling(card.id);
      const errorMessage =
        error instanceof Error ? error.message : "Unknown error";

      const errorLogs: ExecutionLog[] = [
        ...initialLogs,
        {
          timestamp: new Date().toISOString(),
          type: "error",
          content: `Erro de conexão: ${errorMessage}`,
        },
      ];

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: "error",
          result: errorMessage,
          logs: errorLogs,
        });
        return next;
      });

      console.error(`[useAgentExecution] Error:`, errorMessage);
      return { success: false, error: errorMessage };
    }
  }, [startPolling, stopPolling]);

  const executeImplement = useCallback(async (card: Card): Promise<ExecuteImplementResult> => {
    if (!card.specPath) {
      console.error("[useAgentExecution] Card does not have a specPath");
      return { success: false, error: "Card não possui um plano associado" };
    }

    console.log(`[useAgentExecution] Starting implementation for: ${card.specPath}`);

    // Set status to running with initial log
    const initialLogs: ExecutionLog[] = [
      {
        timestamp: new Date().toISOString(),
        type: "info",
        content: `Iniciando implementação do plano: ${card.specPath}`,
      },
    ];

    setExecutions((prev) => {
      const next = new Map(prev);
      next.set(card.id, {
        cardId: card.id,
        status: "running",
        logs: initialLogs,
        startedAt: new Date().toISOString(),
      });
      return next;
    });

    // Start polling for real-time logs
    startPolling(card.id);

    try {
      const response = await fetch(API_ENDPOINTS.execution.implement, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cardId: card.id,
          specPath: card.specPath,
        }),
      });

      const result = await response.json();
      const logs: ExecutionLog[] = result.logs || [];

      // Stop polling and update final state
      stopPolling(card.id);

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: result.success ? "success" : "error",
          result: result.result || result.error,
          logs: logs,
          completedAt: new Date().toISOString(),
        });
        return next;
      });

      console.log(`[useAgentExecution] Implementation completed:`, result);
      return {
        success: result.success,
        result: result.result,
        error: result.error,
      };
    } catch (error) {
      stopPolling(card.id);
      const errorMessage =
        error instanceof Error ? error.message : "Unknown error";

      const errorLogs: ExecutionLog[] = [
        ...initialLogs,
        {
          timestamp: new Date().toISOString(),
          type: "error",
          content: `Erro de conexão: ${errorMessage}`,
        },
      ];

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: "error",
          result: errorMessage,
          logs: errorLogs,
        });
        return next;
      });

      console.error(`[useAgentExecution] Error:`, errorMessage);
      return { success: false, error: errorMessage };
    }
  }, [startPolling, stopPolling]);

  const getExecutionStatus = useCallback(
    (cardId: string): ExecutionStatus | undefined => {
      return executions.get(cardId);
    },
    [executions]
  );

  const executeTest = useCallback(async (card: Card): Promise<ExecuteImplementResult> => {
    if (!card.specPath) {
      console.error("[useAgentExecution] Card does not have a specPath");
      return { success: false, error: "Card não possui um plano associado" };
    }

    console.log(`[useAgentExecution] Starting test-implementation for: ${card.specPath}`);

    const initialLogs: ExecutionLog[] = [
      {
        timestamp: new Date().toISOString(),
        type: "info",
        content: `Iniciando validação do plano: ${card.specPath}`,
      },
    ];

    setExecutions((prev) => {
      const next = new Map(prev);
      next.set(card.id, {
        cardId: card.id,
        status: "running",
        logs: initialLogs,
        startedAt: new Date().toISOString(),
      });
      return next;
    });

    // Start polling for real-time logs
    startPolling(card.id);

    try {
      const response = await fetch(API_ENDPOINTS.execution.test, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cardId: card.id,
          specPath: card.specPath,
        }),
      });

      const result = await response.json();
      const logs: ExecutionLog[] = result.logs || [];

      // Stop polling and update final state
      stopPolling(card.id);

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: result.success ? "success" : "error",
          result: result.result || result.error,
          logs: logs,
          completedAt: new Date().toISOString(),
        });
        return next;
      });

      console.log(`[useAgentExecution] Test-implementation completed:`, result);
      return {
        success: result.success,
        result: result.result,
        error: result.error,
      };
    } catch (error) {
      stopPolling(card.id);
      const errorMessage =
        error instanceof Error ? error.message : "Unknown error";

      const errorLogs: ExecutionLog[] = [
        ...initialLogs,
        {
          timestamp: new Date().toISOString(),
          type: "error",
          content: `Erro de conexão: ${errorMessage}`,
        },
      ];

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: "error",
          result: errorMessage,
          logs: errorLogs,
        });
        return next;
      });

      console.error(`[useAgentExecution] Error:`, errorMessage);
      return { success: false, error: errorMessage };
    }
  }, [startPolling, stopPolling]);

  const executeReview = useCallback(async (card: Card): Promise<ExecuteImplementResult> => {
    if (!card.specPath) {
      console.error("[useAgentExecution] Card does not have a specPath");
      return { success: false, error: "Card não possui um plano associado" };
    }

    console.log(`[useAgentExecution] Starting review for: ${card.specPath}`);

    const initialLogs: ExecutionLog[] = [
      {
        timestamp: new Date().toISOString(),
        type: "info",
        content: `Iniciando revisão do plano: ${card.specPath}`,
      },
    ];

    setExecutions((prev) => {
      const next = new Map(prev);
      next.set(card.id, {
        cardId: card.id,
        status: "running",
        logs: initialLogs,
        startedAt: new Date().toISOString(),
      });
      return next;
    });

    // Start polling for real-time logs
    startPolling(card.id);

    try {
      const response = await fetch(API_ENDPOINTS.execution.review, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cardId: card.id,
          specPath: card.specPath,
        }),
      });

      const result = await response.json();
      const logs: ExecutionLog[] = result.logs || [];

      // Stop polling and update final state
      stopPolling(card.id);

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: result.success ? "success" : "error",
          result: result.result || result.error,
          logs: logs,
          completedAt: new Date().toISOString(),
        });
        return next;
      });

      console.log(`[useAgentExecution] Review completed:`, result);
      return {
        success: result.success,
        result: result.result,
        error: result.error,
      };
    } catch (error) {
      stopPolling(card.id);
      const errorMessage =
        error instanceof Error ? error.message : "Unknown error";

      const errorLogs: ExecutionLog[] = [
        ...initialLogs,
        {
          timestamp: new Date().toISOString(),
          type: "error",
          content: `Erro de conexão: ${errorMessage}`,
        },
      ];

      setExecutions((prev) => {
        const next = new Map(prev);
        next.set(card.id, {
          cardId: card.id,
          status: "error",
          result: errorMessage,
          logs: errorLogs,
        });
        return next;
      });

      console.error(`[useAgentExecution] Error:`, errorMessage);
      return { success: false, error: errorMessage };
    }
  }, [startPolling, stopPolling]);

  const clearExecution = useCallback((cardId: string) => {
    stopPolling(cardId);
    completionCallbacksRef.current.delete(cardId);
    setExecutions((prev) => {
      const next = new Map(prev);
      next.delete(cardId);
      return next;
    });
  }, [stopPolling]);

  // Register a callback to be called when an execution completes
  // Used for workflow recovery after page refresh
  const registerCompletionCallback = useCallback((cardId: string, callback: ExecutionCompletionCallback) => {
    console.log(`[useAgentExecution] Registering completion callback for card: ${cardId}`);
    completionCallbacksRef.current.set(cardId, callback);

    // Check if execution already completed while waiting for callback registration
    const pendingCompletion = pendingCompletionsRef.current.get(cardId);
    if (pendingCompletion) {
      console.log(`[useAgentExecution] Found pending completion for card: ${cardId}, calling callback immediately`);
      pendingCompletionsRef.current.delete(cardId);
      setTimeout(() => callback(pendingCompletion), 0);
    }
  }, []);

  // Unregister a completion callback
  const unregisterCompletionCallback = useCallback((cardId: string) => {
    completionCallbacksRef.current.delete(cardId);
  }, []);

  // Execute AI-powered expert triage to identify relevant experts for a card
  // This uses Claude to analyze the card and decide which experts are relevant
  const executeExpertTriage = useCallback(async (card: Card): Promise<ExpertTriageResult> => {
    console.log(`[useAgentExecution] Starting AI expert triage for: ${card.title}`);

    try {
      // Use the new AI-powered endpoint
      const response = await fetch(API_ENDPOINTS.execution.expertTriage, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          card_id: card.id,
          title: card.title,
          description: card.description,
        }),
      });

      const result = await response.json();
      console.log(`[useAgentExecution] AI expert triage completed:`, result);

      return {
        success: result.success,
        cardId: result.cardId,
        experts: result.experts || {},
        error: result.error,
      };
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      console.error(`[useAgentExecution] AI expert triage error:`, errorMessage);
      return {
        success: false,
        cardId: card.id,
        experts: {},
        error: errorMessage,
      };
    }
  }, []);

  // Execute expert sync to update expert knowledge bases after card completion
  const executeExpertSync = useCallback(async (card: Card): Promise<ExpertSyncResult> => {
    console.log(`[useAgentExecution] Starting expert sync for: ${card.title}`);

    if (!card.experts || Object.keys(card.experts).length === 0) {
      console.log(`[useAgentExecution] No experts to sync for card: ${card.id}`);
      return {
        success: true,
        cardId: card.id,
        syncedExperts: [],
      };
    }

    try {
      const response = await fetch(API_ENDPOINTS.experts.sync, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cardId: card.id,
          experts: card.experts,
        }),
      });

      const result = await response.json();
      console.log(`[useAgentExecution] Expert sync completed:`, result);

      return {
        success: result.success,
        cardId: result.cardId,
        syncedExperts: result.syncedExperts || [],
        error: result.error,
      };
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      console.error(`[useAgentExecution] Expert sync error:`, errorMessage);
      return {
        success: false,
        cardId: card.id,
        syncedExperts: [],
        error: errorMessage,
      };
    }
  }, []);

  return {
    executions,
    executePlan,
    executeImplement,
    executeTest,
    executeReview,
    getExecutionStatus,
    clearExecution,
    registerCompletionCallback,
    unregisterCompletionCallback,
    fetchLogsHistory,
    executeExpertTriage,
    executeExpertSync,
  };
}
