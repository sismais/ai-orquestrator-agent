# Sismais AI Orquestrador — "Projeto = escopo do app" + modelos atualizados — Design

**Data:** 2026-07-07
**Status:** Aprovado (usuário aprovou o design + as 3 decisões-chave; execução via subagent-driven-development)
**Relação:** Fecha a 3d-final (remoção do `ActiveProject`) transformando-a numa feature: o chat vira project-scoped e o
seletor de projeto sobe pra o nível do app, então o cwd do agente de chat passa a vir do **Project selecionado** e o
`ActiveProject` perde a função. Junto, atualiza as versões dos modelos LLM e liga o modelo-por-etapa no pipeline.

## Objetivo

1. **Seletor de projeto app-level:** move o `ProjectSelectorRegistry` do `KanbanPage` pro `TopNav` (via
   `WorkspaceLayout`), escopando **todos** os módulos (Kanban, Chat, Dashboard).
2. **Chat project-scoped e persistido:** cada projeto tem suas conversas; as sessões passam a viver em DB (hoje é um
   dict em memória) com `project_id`; o cwd do agente de chat vem do `Project.path` selecionado.
3. **Remover o `ActiveProject`:** sem função após (2). Migrar o FK do `metrics` pra `projects.id`; remover o fluxo
   antigo em `routes/projects.py` e o `database_manager`.
4. **Atualizar modelos LLM:** opus-4.8, sonnet-5, haiku-4.5, +fable-5 (desabilitado), −gemini; **1M de contexto** em
   opus/sonnet; e **ligar o modelo-por-etapa** no pipeline (o `card.model_*` passa a controlar a execução).

## Decisões (aprovadas)

- **Persistência do chat:** DB (tabelas `chat_session`/`chat_message` com `project_id`). Durável, sobrevive a restart.
- **Chat sem projeto selecionado:** exige projeto (mostra "selecione um projeto"; não roda sem um).
- **FK do metrics:** repontar `project_metrics.project_id`/`execution_metrics.project_id` de `active_project.id` →
  `projects.id` (migração leve; dados de dev, volume baixo).
- **Modelo-por-etapa no pipeline:** além de atualizar versões, o `run_stage` passa a receber e usar o `card.model_*`.
- **fable-5 desabilitado:** aparece nos tipos/pricing/mapa e **no picker porém `disabled`** (visível, não selecionável —
  sinaliza que está por vir) — beta + provável cobrança por créditos fora da assinatura.

## Contexto do código (mapeado)

- **Chat hoje:** `services/chat_service.py` guarda sessões num **dict em memória** (`self.sessions`); `routes/chat.py`
  expõe REST + WS sem `project_id`; `agent_chat.py::stream_response(messages, model, system_prompt)` resolve o cwd
  **dentro** dele consultando `ActiveProject` (2 ramos: Claude e Gemini). Não há model/tabela de chat.
- **Projetos:** `models/project_registry.py::Project` (tabela `projects`, tem `path`) é o registry; `ProjectRepository`
  já tem `get_by_id`. `models/project.py::ActiveProject` (tabela `active_project`) é o legado usado só pro cwd do chat +
  fluxo antigo em `routes/projects.py` (load/current/recent).
- **Layout:** `WorkspaceLayout` → `TopNav` (logo · abas de módulo · ações). `App.tsx` já tem `currentProjectId` +
  `setCurrentProjectId` (localStorage `orq.currentProjectId`); hoje passa pro `KanbanPage`, que renderiza o seletor.
- **Métricas:** `project_metrics`/`execution_metrics` com FK → `active_project.id`. `metrics_collector` escrevia via
  `agent.py` (removido) → hoje o pipeline **não** popula métricas (dado ~vazio; migração do FK é trivial).
- **Modelos (espalhados):** `schemas/card.py::ModelType` (Literal, back) e `frontend/types/index.ts::ModelType` (union);
  defaults do Card em `models/card.py`+`schemas/card.py`+`migrations/002_*.sql`+`hooks/useDraft.ts`+`AddCardModal`;
  chat default `sonnet-4.5` em `useChat.ts`/`routes/chat.py`/`chat_service.py`/`agent_chat.py`; **mapa alias→id no
  `agent_chat.py::model_mapping`** (único ponto de conversão); pricing em `config/pricing.py` (back) e
  `constants/pricing.ts` (front, `Record<ModelType,…>` — força atualizar junto). O pipeline **não** usa `card.model_*`
  hoje (`stage_runner` não passa `model` ao SDK).

## Arquitetura / componentes

### Fase A — Seletor de projeto app-level (frontend, sem risco de dados)
- `WorkspaceLayout` recebe `currentProjectId` + `onProjectSwitch`; passa pro `TopNav`, que renderiza o
  `ProjectSelectorRegistry` (numa área própria, ex.: à direita das abas ou entre logo e abas).
- `App.tsx` passa `currentProjectId`/`setCurrentProjectId` pro `WorkspaceLayout` (já tem o estado).
- `KanbanPage` deixa de renderizar o seletor (continua recebendo `currentProjectId`).
- Sem projeto selecionado: um estado app-level "selecione um projeto" (o board e o chat mostram um empty state).

### Fase B — Chat project-scoped + persistido (backend)
- **Models novos** (`models/chat.py`): `ChatSession(id, project_id FK→projects.id, title, created_at, updated_at)`,
  `ChatMessage(id, session_id FK→chat_session.id, role, content, model, created_at)`. Registrar no `models/__init__.py`
  + `create_all`. (Sem Alembic — `create_all` cria as tabelas novas.)
- **Repositório** `repositories/chat_repository.py`: criar sessão (com project_id), listar sessões por projeto, buscar
  histórico, adicionar mensagem.
- **chat_service.py** deixa de usar o dict: passa a persistir via repo. `send_message` recebe/usa o `project_id` da
  sessão. O contexto do Kanban no system_prompt fica **scoped** ao projeto (só cards daquele `project_id`).
- **agent_chat.py**: `stream_response` ganha um parâmetro **`cwd`** explícito; remove as 2 consultas a `ActiveProject`
  (e o ramo Gemini some — ver Fase D). O cwd = `Project.path` (via `ProjectRepository.get_by_id(project_id)`),
  resolvido no `chat_service` e repassado.
- **routes/chat.py** passa a exigir/carregar `projectId`: criar sessão vinculada ao projeto via
  `POST /api/chat/sessions` com `{projectId}` no body; listar por projeto via `GET /api/chat/sessions?projectId=`; o
  WS/send usa o projeto da própria sessão (resolvido pelo `session_id`). Mantém as rotas do chat coesas em `/api/chat`.
- **Frontend chat** (`useChat`/`api/chat`/ChatPage): usa `currentProjectId`; ao trocar de projeto, recarrega as
  conversas daquele projeto; sem projeto → empty state.

### Fase C — Remover ActiveProject + migrar FK do metrics (backend)
- **Migração leve** (`light_migrations.py`): repontar `project_metrics.project_id`/`execution_metrics.project_id` de
  `active_project.id` → `projects.id`. Em SQLite (sem FK enforcement por padrão + tabelas ~vazias), a mudança é no
  **model** (`ForeignKey("projects.id")`) + um passo idempotente que garante o schema. Descrever o passo exato no plano.
- Remover `models/project.py::ActiveProject`, o fluxo antigo em `routes/projects.py` (endpoints load/current/recent que
  setavam ActiveProject) + `get_active_project` remanescente, e `database_manager.py` (multi-arquivo legado). Verificar
  boot + Chat + testes após.

### Fase D — Modelos LLM (back + front) + modelo-por-etapa
- **`ModelType`** (back `schemas/card.py` + front `types/index.ts`): `opus-4.8 | sonnet-5 | haiku-4.5 | fable-5`.
  Remover as entradas Gemini (`gemini-3-*`) e o provider `google`.
- **Defaults do Card:** `opus-4.5` → `opus-4.8` em `models/card.py`, `schemas/card.py`, `migrations/002_*.sql`,
  `hooks/useDraft.ts`, `AddCardModal`. Chat default → `sonnet-5`.
- **Mapa alias→id do SDK** (`agent_chat.py::model_mapping`, único ponto):
  `opus-4.8 → claude-opus-4-8[1m]`, `sonnet-5 → claude-sonnet-5[1m]`, `haiku-4.5 → claude-haiku-4-5`,
  `fable-5 → claude-fable-5`. (1M é a notação do Claude Code CLI/SDK; **verificar** a string exata contra o SDK ao
  implementar — se `[1m]` não for aceito, cair pro base `claude-opus-4-8`, que já é 1M na API.) Fallback do mapa passa a
  `claude-sonnet-5[1m]`.
- **Pricing:** atualizar `config/pricing.py` e `constants/pricing.ts` (`Record<ModelType,…>` — obrigatório atualizar
  junto ou o tsc quebra). Incluir fable-5.
- **Pickers:** `ModelSelector.tsx` (chat) e `MODEL_CARDS` (AddCardModal) — novos rótulos, **fable-5 aparece disabled**,
  sem Gemini. Ajustar acentos de estilo em `ModelCard.module.css` (remover `.gemini-*`, add fable).
- **Remover Gemini:** deletar `gemini_agent.py` e `services/gemini_service.py` (órfão); remover o ramo
  `_stream_response_gemini` + `if model.startswith("gemini")` de `agent_chat.py`.
- **Modelo-por-etapa no pipeline:** `stage_runner.run_stage` ganha param `model` e o passa em
  `ClaudeAgentOptions(model=<id do SDK>)`; `pipeline_service` lê o `card.model_plan/implement/review` da etapa
  corrente, mapeia alias→id (reusar o `model_mapping`, extraído p/ um módulo compartilhado se preciso), e passa. Sem
  `card.model_*` definido → default do CLI (comportamento atual).
- **Dados existentes:** migração leve remapeia aliases antigos nos cards (`opus-4.5→opus-4.8`, `sonnet-4.5→sonnet-5`) +
  no default do workflow, pra não sumir custo/consistência. `String(20)` comporta os novos nomes.

## Ordem de execução (fases independentes onde der)

A (frontend seletor) → D (modelos; independente, pode ir cedo) → B (chat persistido/scoped) → C (remover ActiveProject).
C **depende** de B (o chat precisa parar de usar ActiveProject antes de removê-lo).

## Testes

- **A:** tsc; QA visual (seletor no TopNav escopa Kanban+Chat; sem projeto → empty state).
- **B:** unit dos repos de chat (criar/listar por projeto/histórico); `chat_service` persiste e scoping por projeto;
  `stream_response` usa o cwd passado (sem tocar ActiveProject); smoke real: criar sessão num projeto, trocar de
  projeto, ver as conversas trocarem + o chat responder no cwd do projeto.
- **C:** boot OK + Chat vivo + testes após remover ActiveProject; migração do FK do metrics idempotente.
- **D:** ModelType/pricing consistentes (tsc); `model_mapping` cobre os 4 aliases (+ remap dos antigos); pipeline passa
  o `model` da etapa ao SDK (unit com stub); smoke real: rodar um card com um modelo escolhido e ver o custo/execução.

## Critérios de aceitação

1. Seletor de projeto no TopNav escopa Kanban **e** Chat; sem projeto → empty state coerente; board usa o `currentProjectId`.
2. Conversas do chat são **por projeto e persistidas** (sobrevivem a restart); trocar de projeto troca as conversas.
3. O agente de chat roda no **cwd do projeto selecionado** (sem `ActiveProject`).
4. `ActiveProject`/`database_manager` removidos; FK do metrics aponta pra `projects.id`; boot + Chat + testes OK.
5. Modelos: opus-4.8/sonnet-5/haiku-4.5 nos tipos/pricing/pickers; fable-5 presente porém **desabilitado**; Gemini
   removido; **1M** em opus/sonnet; o **modelo escolhido por etapa controla a execução** do pipeline; dados antigos remapeados.

## Fora de escopo

Título automático "inteligente" de sessão de chat (usar um default simples, ex.: primeira mensagem truncada);
multi-provider (só Claude); reintroduzir `/say` do chat ao vivo; UI de histórico de chat avançada (busca, pastas).
