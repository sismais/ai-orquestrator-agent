# Painel — Fase 2b-2: Frontend multi-projeto (seletor + projectId nas chamadas) — Plano

> Parte **2b-2** da Fase 2 (ver spec `2026-07-02-panel-fase2-multiprojeto-workflow-design.md`). Executada **inline com verificação visual** (frontend intrincado). Backend 2b-1 já pronto (`/api/registry/projects`, `/api/workflows/{id}`, `GET /api/cards?projectId=`, create com `projectId`).

**Goal:** O board vira **multi-projeto**: registrar N projetos, um **seletor** no topo, trocar de projeto **sem reload** re-buscando os cards daquele projeto (`?projectId=`), e cards criados carimbam `projectId`.

**Escopo (durável, seguro):** api client do registry + workflow; `projectId` em `fetchCards`/`createCard`; estado `currentProjectId` (persistido em localStorage); seletor de projeto no header; troca re-busca cards sem reload.

**Fora (Fase 3 — reescrita do runner):** board dirigido por config/colunas novas, validação de move por config, escopo dos endpoints `execute-*`/worktree por projeto, remoção do `ActiveProject`/`database_manager`, runner no backend. O board mantém colunas atuais e a automação atual roda no projeto ativo do backend (legado) até a Fase 3.

## Tarefas
1. **`src/api/projectsRegistry.ts`** — `listProjects()`, `createProject({name, path, workflowId?})`, `deleteProject(id)` contra `/api/registry/projects`. Tipo `RegistryProject {id,name,path,workflowId,rulesFile,baseBranch,favorite}`.
2. **`src/api/cards.ts`** — `fetchCards(projectId?)` → anexa `?projectId=` quando dado; `createCard(..., projectId?)` → inclui `projectId` no body.
3. **`src/components/ProjectSelectorRegistry/`** — dropdown no header: lista projetos do registry, troca (callback), e "adicionar projeto" (name + path).
4. **`App.tsx`** — estado `currentProjectId` (localStorage `orq.currentProjectId`); carrega projetos no mount; `fetchCards(currentProjectId)`; `createCard` passa `currentProjectId`; trocar projeto → set state + re-fetch (sem `window.location.reload()`); renderiza o seletor no header do Kanban.

## Aceitação
- Registrar 2 projetos; trocar no seletor; cada board mostra só os cards do projeto (isolados por `project_id`); criar card no projeto A não aparece no B; sem reload de página na troca. Verificação visual via Chrome MCP.
