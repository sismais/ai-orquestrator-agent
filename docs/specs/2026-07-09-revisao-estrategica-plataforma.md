# Revisão estratégica da plataforma — análise de gap (visão de produto × estado atual)

**Data:** 2026-07-09
**Método:** análise somente-leitura (sem implementação), executada com Claude Code + Fable 5. Estado atual
verificado no código por 10 frentes de exploração paralelas com regra de grounding (`arquivo:linha` lido nesta
sessão); evidências conferidas por amostragem por um subagente verificador de contexto limpo.
**Prompt de origem:** `docs/prompts/2026-07-09-revisao-estrategica-plataforma.prompt.md`

> **Convenção de grounding:** toda afirmação sobre o estado atual cita `arquivo:linha` verificado. O que foi
> procurado e não existe está marcado como **não encontrado** (com a busca feita). Nada abaixo é inferido do
> comportamento do fork original.

---

## Resumo do estado atual (checkpoint)

1. **Existe:** board Kanban config-driven (workflow `dev` semeado) com o backend orquestrando `plan → implement → review → validate_ci → ready_to_merge` em worktree isolada por card, com fix-loop (teto 4), Pause-or-Decide com resposta humana no card retomando o pipeline, Stop interrompível, PR draft + espera de CI com ci-triage — parando sempre no ready-to-merge (humano decide o merge).
2. **Existe:** chat project-scoped persistido em DB, seletor de projeto app-level, modelo-por-etapa via `config/model_ids.py` (chat e pipeline), logs de execução em `executions`/`execution_logs`, custo real do run persistido.
3. **Parcial:** etapa `plan` é só planner (specifier/clarifier/tasker do DevKit existem mas estão órfãos), logs capturam só texto (sem tool calls), custo não aparece na UI, métricas de baseline quebradas.
4. **Não existe:** roteamento por complexidade, revisor de escalação + memória de decisões, contexto de quem pede, métricas de autonomia, criação de projeto do zero, tratamento de recusa/perfis por modelo, recovery pós-restart.
5. **Legado Zenflow removido** (orchestrator autônomo, Gemini, `ActiveProject`, multi-DB); banco único tenant-shaped; DevKit em `devkit/.claude` não é injetado na worktree (worktree pristina).

---

## Sumário executivo

As cinco melhorias que mais aumentam autonomia e fluidez, em ordem:

1. **Blindar o loop** — hoje uma exceção fora do estágio deixa a `Execution` como `RUNNING` órfã para sempre (sem try/except de topo em `run_pipeline` + `create_task` sem handler; sem recovery no boot), um review sem JSON parseável **aprova o diff** em silêncio, e não há instrução anti-parada-prematura em nenhum prompt. "Trabalhar até estar pronto" não é confiável antes disso — e é tudo barato (P).
2. **Tornar a pausa visível** — a descoberta de que um card precisa do humano é 100% passiva (card âmbar numa coluna depois de Done; `useToast` órfão, sino decorativo). O tempo de resposta humana é o gargalo do pipeline inteiro; toast + contador "aguardando você" muda a fluidez percebida mais que qualquer outra mudança de UX.
3. **Perfis por modelo + tratamento de recusa com fallback** — `ResultMessage` só é lido para custo; recusa/erro suave passa como sucesso ou vira pausa sem explicação. Estender `config/model_ids.py` (já o ponto único parcial) para perfis `{id, snippets, fallback}` e inspecionar o resultado do turno destrava o multi-modelo real e o fable-5.
4. **Router de complexidade no `/execute`** — o conceito Leve/Padrão/Exploratória já existe pronto como prosa no DevKit; `run_pipeline` já aceita começar em etapa arbitrária (`resume_stage`). Um estágio de triagem barato dá workflow proporcional à tarefa.
5. **Escalação inteligente + memória de decisões** — o clarifier com score 0–3 existe no DevKit e está órfão; o Q&A humano já é persistido em `activity_logs` e nunca reinjetado. Ligar os dois reduz pausas desnecessárias — o multiplicador de autonomia mais promissor.

---

## Padrões oficiais da Anthropic — status na plataforma

| # | Padrão | Status verificado |
|---|--------|-------------------|
| 1 | Snippet anti-parada-prematura | **Ausente.** Nenhuma instrução do tipo em `devkit/.claude/agents/*.md` nem nos prompts de `stage_runner.build_stage_prompt` (busca por `autonom`/`não encerre`/etc. = 0 hits). Fim de turno = estágio concluído (`pipeline_service.py:307-325`). |
| 2 | Ferramenta `send_to_user` | **Ausente.** Nenhuma tool custom/MCP registrada (busca por `send_to_user`/`mcp_servers`/`create_sdk_mcp_server` em backend = 0 hits). Progresso = texto do agente em lotes de ~800 chars (`pipeline_service.py:41`). |
| 3 | Memória de lições | **Ausente.** `qdrant_service.store_learning/query_learnings` existe mas é código morto (0 imports); nada em `devkit/` (busca `lesson|learned|memor` = 0); Q&A humano fica em `activity_logs` sem reinjeção. |
| 4 | Tratamento de recusa com fallback | **Ausente.** Busca por `refusal`/`retry`/`fallback` de modelo em backend/src = 0 hits relevantes; único destino de erro é `finish_pause` (`pipeline_service.py:303-305`). |
| 5 | Perfis por modelo | **Parcial.** `config/model_ids.py` é o mapa único alias→id consumido por chat e pipeline (`model_ids.py:10-27`), mas há 4 construtores independentes de `ClaudeAgentOptions` e nenhum conceito de perfil. Nenhum parâmetro modelo-específico é passado hoje (busca `temperature|budget_tokens|thinking|prefill|effort` = 0 fora de comentários "best-effort") — nada a limpar, só a estender. |
| 6 | Verificação com contexto limpo | **Já atendido estruturalmente.** Cada estágio roda numa sessão SDK nova (`stage_runner.py:167-173`); o reviewer é independente do implementer por construção e recebe o diff real (`stage_runner.py:102-109`). |

**Auditoria de chain-of-thought (risco `reasoning_extraction` no Fable 5):** nenhum agente do DevKit nem o
system prompt do chat pede transcrição de raciocínio interno — verificados os 7 `.md` e o `DEFAULT_SYSTEM_PROMPT`
(`agent_chat.py:111-162`); reviewer e clarifier fazem o oposto ("Saída (JSON, sem prosa fora dele)",
`sismais-dev-reviewer.md:13`; "Sem prosa fora do JSON", `sismais-dev-clarifier.md:38`). Os campos `porque`/`fonte`
são justificativa de decisão, não CoT. **Sem bloqueio para habilitar o fable-5 por esse critério.**

---

## Análise por dimensão

### 1. Roteamento adaptativo de workflow

**Estado atual.** O workflow é escolhido pelo **projeto** (`Project.workflow_id`, default `"dev"` —
`models/project_registry.py:22`, `routes/projects_registry.py:22`); o card não tem workflow nem trilha. O
dispatcher é hardcoded em dois níveis: quais colunas o pipeline executa (`_AGENT_STAGES = ("plan", "implement",
"review")` + `validate_ci`, `pipeline_service.py:44,50-51`) e coluna→`.md` do DevKit (`STAGE_AGENTS`,
`stage_runner.py:29-34`). Os campos `agentKey`/`provider`/`model`/`isPausedState` das colunas do config são
gravados no seed e **nunca lidos** (grep = só seed e comentários); não há CRUD de workflow (única rota é `GET
/api/workflows/{id}`, `routes/workflows.py:13-22`). **Nenhuma avaliação de complexidade existe no backend**
(busca por `triage|complexity|trilha|router` — nenhum hit de roteamento por complexidade; os hits existentes são
o expert-triage por keywords, que o pipeline não chama, o ci-triage de falha de CI e os `APIRouter` do FastAPI). O conceito de trilhas **já existe pronto no DevKit**: router Leve/Padrão/Exploratória como prosa
(`devkit/.claude/skills/sismais-dev/SKILL.md:25-33`) e os agentes `specifier`/`clarifier`/`tasker` (órfãos —
grep em backend = 0). Mecanismo facilitador já existente: `run_pipeline` aceita começar em etapa arbitrária
(`col = resume_stage or _first_stage(...)`, `pipeline_service.py:251`).

**Gap.** Tarefa trivial e feature complexa percorrem exatamente o mesmo caminho, com o mesmo custo; não há como
pular o `plan` num typo fix nem aprofundar (spec/clarify) numa feature grande.

**Recomendação.** Estágio de **triagem no `POST /execute`** (`routes/runner.py:32-48`), antes do
`create_task`: um dispatch de agente barato (haiku, prompt derivado do texto do router da skill) classifica
Leve/Padrão e devolve a coluna inicial — trivial começa em `implement` via o `resume_stage` já existente;
registrar trilha + justificativa nos logs da execução. Em seguida (horizonte Próximo), generalizar o dispatcher
para ler `agentKey` do config (dado já persistido e nunca consumido) — isso destrava colunas novas (`spec`,
`clarify`) e é a mesma mudança que abre workflows de outras áreas (dimensão 9).

### 2. Robustez do loop

**Estado atual.** O núcleo prometido existe e está provado: fix-loop review→implement com teto
(`DEFAULT_MAX_ITERATIONS = 4`, `pipeline_service.py:40`; estouro pausa, `:331-339`), oito gatilhos de
Pause-or-Decide convergindo em `finish_pause` (`pipeline_service.py:204-227`), retomada via `POST /answer` com
`resume_stage` + `human_answer` (`routes/runner.py:51-82`) reusando a worktree (`pipeline_service.py:230`), Stop
real via `session_registry.interrupt` (`session_registry.py:36-46`), tetos análogos no validate_ci
(`validate_ci_stage.py:61-63,102-104`, poll de CI com `_MAX_POLLS = 40`, `:15-16`).

**Gaps verificados (em ordem de gravidade):**

1. **Exceção fora do estágio deixa o run órfão.** `run_pipeline` não tem try/except de topo (corpo inteiro
   verificado, `pipeline_service.py:173-393`) e o `asyncio.create_task` do endpoint não tem done-callback
   (`routes/runner.py:46`). Exceção em `repo.move`/`commit`/`diff` → task morre em silêncio, `Execution` fica
   `RUNNING` para sempre, e como `/answer` exige `PAUSED` (`routes/runner.py:70-71`), a retomada fica bloqueada.
2. **Nenhum recovery no boot.** O `lifespan` só cria tabelas/migra/semeia (`main.py:52-83`); nenhuma varredura
   de `Execution RUNNING` órfã. Restart do backend durante um run = card travado na coluna corrente.
3. **Review vazio aprova o diff (falha aberta).** `parse_review_findings` devolve baldes vazios quando não há
   JSON ("nao bloqueia por ausencia de parse", `findings.py:66-75`) → `blocking = 0` → avança para validate_ci
   (`pipeline_service.py:328-330,373`). Um reviewer que responda só prosa, um turno vazio (`run_stage` retorna
   `ok=True, text=""`, `stage_runner.py:198-201`) ou uma recusa silenciosa liberam o caminho do merge.
4. **Sem retry e sem detecção de recusa.** Uma única tentativa por estágio; `except Exception` genérico →
   pausa (`stage_runner.py:184-189`); `ResultMessage` só é lido para custo (`stage_runner.py:182-183`) — o
   `subtype`/erro do turno nunca é inspecionado (ver dimensão 10).
5. **Anti-parada-prematura ausente** (padrão 1): nada impede o implement de encerrar o turno com um plano em
   texto — o pipeline commita o que estiver na worktree ("nada a commitar também conta como sucesso",
   `git_workspace.py:215-217`) e segue para review.
6. **Perdas na retomada:** `human_answer` só entra nos prompts de `plan` e `implement`-sem-findings
   (`stage_runner.py:78,96`) — se a pausa foi em `validate_ci`, a resposta humana nunca chega a prompt algum
   (`pipeline_service.py:267-281`); `plan_text` não é persistido (variável local, `pipeline_service.py:249`) —
   retomada em implement perde o plano do run anterior.
7. **Sem timeout do backend sobre o turno do agente** (`stage_runner.py:168-183` — só a espera de CI tem teto).

**Recomendação.** Um pacote único de robustez (tudo P, sem incerteza): (a) try/except de topo em `run_pipeline`
→ `finish_pause("erro interno do orquestrador", ...)`; (b) sweep no boot: `RUNNING` órfã → `PAUSED` +
comentário no card explicando; (c) review falha-fechada: sem JSON parseável → 1 re-pedido → pausa (nunca
aprovar por ausência de parse); (d) snippet anti-parada-prematura no `append` do system prompt em
`run_stage` (padrão 1, texto do prompt de origem); (e) persistir `plan_text` (ex.: em `Execution.result` ou
coluna própria) e injetar `human_answer` também no fluxo de validate_ci; (f) timeout configurável por turno.

### 3. Escalação humana inteligente

**Estado atual.** A pausa é **binária e imediata**: regex `needs_human` (`findings.py:107-110` — casa o termo
em qualquer lugar do texto, com falso positivo possível) ou `pendingQuestions` do plan (`findings.py:83-90`) →
`finish_pause` sem nenhuma camada intermediária (`pipeline_service.py:307-323`). Não existe revisor de
escalação no backend (grep `clarif` em backend/ = 0). O padrão Pause-or-Decide com **score 0–3 já está
documentado e pronto** no DevKit: clarifier decide com score ≥ 2 citando fontes, pausa com score < 2
(`sismais-dev-clarifier.md:14-21`), com gate na skill orquestradora (`sismais-dev/SKILL.md:57-59`) — mas o
clarifier não está em `STAGE_AGENTS` e os scripts de estado `.mjs` que registrariam decisões não existem
(`devkit/README.md:17`; find `*.mjs` = 0 arquivos). **Memória de decisões:** o Q&A humano é persistido como
comentários em `activity_logs` (autor sentinela `agent`/`human`, `activity_repository.py:65-72`), consultável
por card (`routes/activities.py:36-53`), mas **jamais reinjetado** — `build_stage_prompt` nunca lê
`activity_logs`, e não há endpoint cross-card de decisões. A infraestrutura Qdrant de learnings
(`store_learning`/`query_learnings`, `qdrant_service.py:57-169`) é código morto (0 imports) e está cortada por
decisão de arquitetura — não religar.

**Gap.** Toda dúvida do agente vira interrupção humana, mesmo quando decisões anteriores do mesmo projeto já
responderiam; e o que o humano decide se perde para execuções futuras.

**Recomendação.** Duas peças acopladas: (1) **gate de escalação** — antes de `finish_pause` por
`pendingQuestions`/`needs_human`, despachar o clarifier (contexto limpo, mesmo mecanismo `run_stage`) com a
dúvida + fontes do projeto + decisões passadas; só pausa o que ficar com score < 2, registrando as decisões
automáticas com fonte nos logs; (2) **memória de decisões** (padrão 3, versão mínima): persistir cada par
pergunta→resposta/decisão de forma estruturada (tabela `decisions` por projeto, ou Markdown por projeto — uma
lição por arquivo com resumo de 1 linha) e injetar as N mais relevantes no prompt do clarifier e do plan.
`activity_logs` já tem os dados históricos para semear (atenção: `ondelete=CASCADE` no card e
`delete_old_activities(90d)` existente sem callers, `activity_log.py:29-31`, `activity_repository.py:152-171`).

### 4. Contexto de quem pede

**Estado atual.** O card **não registra quem pediu**: o model inteiro não tem criador/prioridade/tipo/labels
(`models/card.py:11-104`; schema `CardCreate` idem, `schemas/card.py:79-105`). O model `User` existe mas é
órfão (único import em `models/__init__.py:3`); nenhuma rota de auth registrada (`main.py:103-115`); postura
single-user local declarada (`routes/filesystem.py:2`). O `Project` não tem descrição/objetivo/empresa
(`models/project_registry.py:15-25`). O prompt dos estágios recebe **apenas** `title + description + worktree`
+ extras mecânicos (diff/plan/findings/human_answer) — `build_stage_prompt` (`stage_runner.py:62-121`,
chamado em `pipeline_service.py:292`). Gaps colaterais verificados: `project.rules_file` nunca chega ao prompt
(o texto hardcoda "Siga o AGENTS.md do projeto se existir", `stage_runner.py:98`); os `.md` dos agentes prometem
receber `rulesFile`/`spec.md`/decisões do clarifier que o backend não envia (`sismais-dev-planner.md:9`);
`card.images` nunca chega ao agente (grep em services = 0).

**Gap.** "Quem pede, para qual projeto, com qual objetivo" — os três insumos que a visão exige para calibrar
decisões e profundidade — não existem no dado nem no prompt.

**Recomendação.** Incremental e barato: (1) campos `requested_by` (texto livre/role: dev, PO, CEO) no Card e
`description`/`objective` no Project (+ schemas + modal); (2) injetar um bloco de contexto no header do
`build_stage_prompt` — o call site já tem `card` e `project` em escopo (`pipeline_service.py:174`); (3) na
mesma mudança, corrigir o `rules_file` hardcoded e alinhar os `.md` dos agentes ao contrato real de inputs
(remover promessas ou passar os artefatos). Isso alimenta também o router (dimensão 1) e o gate de escalação
(dimensão 3), que são os consumidores de "quem pede".

### 5. Auditoria e observabilidade

**Estado atual.** Logs por execução existem e chegam ao vivo no board: `_LogSink` bufferiza (~800 chars),
persiste `ExecutionLog` e transmite por WS no mesmo flush (`pipeline_service.py:41,60-102`;
`execution_ws.py:49-56`); front renderiza no LogsModal com re-hidratação no reload
(`PipelineControls.tsx:31-43,105-120`). Custo real do run é persistido (`execution_cost`,
`pipeline_service.py:222,388`) e exposto na API (`costUsd`, `routes/runner.py:129`). **Mas a auditoria não é
"total":** do stream do SDK só `TextBlock` é capturado — tool calls, tool results e thinking não
(`stage_runner.py:173-183`; grep `ToolUseBlock` no backend = só um import não usado em `agent_chat.py:12`); os prompts enviados a cada estágio não
são persistidos; tokens/`model_used` nunca são gravados (`update_token_usage` sem callers,
`execution_repository.py:279-313`) → o `costStats` por card que a UI exibe é sempre zero
(`cost_calculator.py:23-24`); o `costUsd` real existe na API mas **nenhum componente renderiza** (grep
`costUsd` no front = só o tipo). **Métricas de autonomia não existem** (busca `autonomy|intervention|pause_count`
= 0): iterações do fix-loop são variável local, nº de pausas não é contado. Bug de baseline confirmado:
`get_productivity_metrics` consulta `Card.status`, coluna inexistente (`metrics_repository.py:351-364`).
`send_to_user` não existe (padrão 2) — e os prompts de reviewer/ci-triage pedem "sem prosa fora do JSON", o que
deixa esses estágios mudos no log até o JSON final.

**Gap.** Não dá para reconstruir *o que o agente fez* (só o que narrou), não dá para responder "quanto custou e
quão autônomo foi" por card/projeto, e o progresso visível ao usuário depende do agente narrar por conta própria.

**Recomendação.** (1) Capturar `ToolUseBlock`/`ToolResultBlock` como `ExecutionLog` tipado (auditoria total é
princípio da visão) e persistir o prompt de cada estágio; (2) gravar `usage`/`model_used` do `ResultMessage` +
contadores `pause_count`/`fix_iterations` na `Execution` — com isso "% de cards concluídos sem intervenção"
vira uma query; (3) renderizar o `costUsd` que já vem na API no card; (4) `send_to_user` (padrão 2): tool
in-process via SDK MCP no `run_stage` que grava comentário/log de progresso no card **+ instrução explícita de
uso no system prompt** (definir a tool não basta) — resolve também o silêncio dos estágios só-JSON.

### 6. Chat

**Estado atual.** Project-scoped e persistido de verdade: sessões/mensagens em DB com FK de projeto
(`models/chat.py:14-41`), cwd do agente = `Project.path` (`chat_service.py:259-260`), rotas exigem `projectId`.
**Cobertura real do contexto é estreita e parcialmente legada:** o contexto Kanban injeta no máximo 5 cards por
coluna com descrição truncada a 60 chars (`chat_service.py:180-185`), usa colunas legadas
`test/completed/cancelado` e **não inclui `paused`, `validate_ci` nem `ready_to_merge`**
(`chat_service.py:153-157,167-174`) — justamente os estados que mais importam; as "atividades recentes" **vazam
entre projetos** (`get_recent_activities` não filtra por projeto, `activity_repository.py:74-94`); execuções,
logs e custos não entram no contexto. **Worktrees:** ficam em `project_path/.worktrees` (`git_workspace.py:27`),
fisicamente legíveis pelas tools do chat — mas não há uma linha de orientação sobre elas no prompt (grep
`worktree` em agent_chat/chat_service = 0). O system prompt é prefixado no prompt de usuário, não passado ao SDK
(`agent_chat.py:58-59`; options sem `system_prompt`, `:74-89`); multi-turno é reconstruído por histórico textual
(novo `query()` por turno, `agent_chat.py:62-71,92`). O template de criação de card via curl **não inclui
`projectId`** (`agent_chat.py:130-143`) — cards criados pelo chat ficam sem projeto. Risco a registrar:
`permission_mode="bypassPermissions"` + Bash irrestrito (`agent_chat.py:77-87`). Sem instruções de CoT (ver
seção de padrões).

**Gap.** O chat da visão ("responde sobre qualquer worktree aberta e sobre tarefas já fechadas") tem o acesso
físico, mas não tem o mapa: contexto desatualizado em relação ao workflow real, sem histórico de execuções, sem
noção de worktrees, e com vazamento cross-project nas atividades.

**Recomendação.** Refazer `_get_kanban_context` sobre o workflow config real (colunas do `GET /api/workflows`,
incluindo paused/validate_ci/ready_to_merge, com card id), escopar atividades por projeto, e ensinar no prompt:
onde vivem as worktrees (`.worktrees/card-*`), e que histórico de execução/comentários pode ser consultado via
API (`GET .../execution`, `GET /api/activities/card/{id}`) — o Bash já permite. Incluir `projectId` no template
do curl (bug funcional). Opcional na mesma passada: mover o system prompt para `ClaudeAgentOptions.system_prompt`.

### 7. Criação de projeto do zero (cenário B)

**Estado atual.** O registro de projetos é **catálogo puro**: `POST /api/registry/projects` só checa
duplicidade de path — não valida existência, diretório ou repo git (`routes/projects_registry.py:58-69`;
`is_git_repo()` existe e nunca é chamado, `git_workspace.py:340-343`). O modal pede só nome + caminho e o
browser de pastas só seleciona pastas existentes (`ProjectSelectorRegistry.tsx:104-167`;
`FolderBrowserModal.tsx:40-91`; `/api/fs/browse` rejeita path inexistente, `filesystem.py:30-31`). **Não existe
nenhum bootstrap/scaffold** (busca `git init|scaffold|bootstrap|template|gh repo` em backend e front = 0
relevante). Na prática o pipeline exige repo git com ≥1 commit (worktree é criada a partir da branch base,
`git_workspace.py:157-162`; falha → card pausa no passo 1, `pipeline_service.py:239-240`); sem remote `origin`
o fluxo funciona até o push e pausa (`validate_ci_stage.py:70-73`); repo sem CI passa como verde
(`validate_ci_stage.py:91-93`). O DevKit tem material de discovery parcial (specifier/clarifier — brownfield
por design; brainstorm é instrução inline na skill, sem agente dedicado, `sismais-dev/SKILL.md:31`). O
`goal_decomposer_service` (objetivo → 2-7 cards) existe e está órfão (`goal_decomposer_service.py`; 0
consumidores) — referência útil, não religar às cegas.

**Gap.** O cenário B inteiro: não há como nascer um projeto pela plataforma, nem discovery de regra de negócio,
nem decomposição do produto em cards.

**Recomendação (MVP, caminho de menor esforço verificado).** (1) endpoint de **bootstrap** no registro: se o
path não existe/não tem `.git` → `mkdir` + `git init -b <base>` + commit inicial com `AGENTS.md` — isso dá
"fonte" para o clarifier/planner funcionarem em greenfield (o score deles depende de fontes do projeto);
`gh repo create` opcional (sem remote, o pipeline degrada com pausa no push — aceitável para MVP); (2) opção
"criar do zero" no modal; (3) **discovery via chat** (que já roda com cwd do projeto): roteiro de perguntas de
negócio no system prompt → escreve o `AGENTS.md` inicial → decompõe em cards no backlog. É a dimensão de maior
esforço — tratar como Explorar com um spike barato (1 projeto novo end-to-end) antes de investir na UX completa.

### 8. UX do painel

**Estado atual (fluxo principal).** Criar card: modal com Title obrigatório + 4 carrosséis de modelo — um deles
para a etapa "Testes", **que não existe** no workflow nem no pipeline (`AddCardModal.tsx:71-96`;
`pipeline_service.py:47` sem "test") — defaults todos em opus-4.8 (o mais caro, `AddCardModal.tsx:101-104`).
Disparo: botão Run manual, só no backlog (`PipelineControls.tsx:130`), com bom feedback imediato (LogsModal
abre na hora, `:93`). Acompanhar: o card muda de coluna a cada estágio (WS) + pill Running/Stop nas etapas
ativas; em `validate_ci` (a etapa mais longa) o indicador vivo é limpo de propósito (`PipelineControls.tsx:58-65`).
**Pausa: descoberta 100% passiva** — card âmbar + selo "⏸ Aguardando você" (`Card.tsx:323-331`) numa coluna
`paused` ordenada **depois de Done** (`workflow_seed.py:26-27`), sem toast (hook `useToast` sem importadores),
sino do TopNav decorativo (`TopNav.tsx:51-57`), nenhum handler global do evento de pausa. Responder é bom:
modal abre direto na aba Interação com thread + "Responder e retomar" (`CardEditModal.tsx:36-38`;
`CardInteraction.tsx:65-77`). Ready-to-merge: só o link "🔗 Ver PR" (`PipelineControls.tsx:155-166`); merge no
GitHub; **nada detecta o merge** (0 rotas de merge; sem poll pós-ready) — o usuário volta e arrasta para done
manualmente. Ruídos legados verificados: badges/estados do sistema antigo convivem com os novos no card
(`Card.tsx:118-189,377-388`; endpoints `execute-*` do config sem rota no backend), botão "Create PR"
placeholder em done (`Card.tsx:336-344`), `alert()` nativo ensinando um fluxo com coluna `test` que não existe
(`App.tsx:582`), `/say` existe no backend sem nenhum consumidor no front (`routes/runner.py:94-104`).

**Gap.** O passo mais frequente (criar card) cobra decisões demais; o momento mais crítico (pausa) não notifica;
o fechamento do ciclo é manual e cego; e dois vocabulários de status disputam o mesmo card.

**Recomendação.** Em ordem de impacto: (1) **notificação de pausa** — handler global de
`card_moved→paused`/`execution_complete(paused)` + toast + contador "aguardando você" no TopNav; reposicionar
`paused` no início do board (é mudança de `order` no seed); (2) **fechar o ciclo** — poll leve do estado do PR
(`gh pr view`) para cards em ready_to_merge → badge "merged" + mover para done (é avanço de coluna pós-merge
humano, não merge automático — não fere a regra); (3) **simplificar o modal** — modelos colapsados em "avançado"
com defaults sensatos e remoção do seletor de "Testes"; (4) **remover a UI legada do card** (item explícito e
planejado, como manda a regra de remoção; a dívida já está anotada no `ARQUITETURA_E_ESTADO.md`).

### 9. Fundações para expansão (criativo/administrativo)

**Estado atual.** A fundação certa já existe: workflow como dados (`models/workflow.py:16-22`), board renderiza
colunas do config, transições validadas pelo config (`card_repository.py:148-152`), `ColumnId = str`
(`schemas/card.py:29-31`). O que **impede** um workflow não-dev hoje: dispatcher hardcoded (dimensão 1), nomes
de coluna fixos no pipeline (`paused`, `implement`, `validate_ci` — `pipeline_service.py:213,342,267`),
`PAUSE_COLUMNS` hardcoded em vez do flag `isPausedState` do config (`workflow_rules.py:10`), prompts de estágio
como f-strings dev-específicas (`stage_runner.py:74-121`), e ausência de CRUD de workflow.

**Gap/Recomendação.** Não desenhar as verticais agora (correto por mentalidade MVP). O único preparo barato que
vale: **fazer o motor honrar o config que já persiste** — dispatcher via `agentKey`, pausa via `isPausedState`,
prompt-base vindo do `.md` do agente em vez de f-string. É a mesma mudança da dimensão 1, com dois consumidores.
CRUD de workflow e editor visual continuam adiados (já estavam "Fora" no design v1).

### 10. Abstração multi-modelo

**Estado atual.** O acoplamento a modelo é **baixo por omissão**: nenhum parâmetro modelo-específico é passado
em lugar nenhum (busca `temperature|budget_tokens|max_thinking_tokens|prefill|effort|top_p|max_turns` em
backend/src = 0 fora de comentários "best-effort") — não há nada quebrando com Fable 5 por parâmetro, e os `.md`
do DevKit são model-agnósticos (0 menções a Claude/Opus/effort). `config/model_ids.py` já é a fonte única
alias→id declarada e consumida pelos dois caminhos vivos (`stage_runner.py:162`; `agent_chat.py:51`), com
fallback `claude-sonnet-5[1m]` (`model_ids.py:20`). **Mas:** há 4 construtores independentes de
`ClaudeAgentOptions` (stage_runner, agent_chat, runner_service legado sem model, goal_decomposer órfão com
`model="opus"` hardcoded fora do mapa); o resultado do turno **nunca é inspecionado** além do custo
(`stage_runner.py:182-183` — `subtype`/erro do `ResultMessage` ignorados), então uma recusa que não lance
exceção passa como `ok=True` com o texto que houver (e cai nas falhas abertas da dimensão 2); **não existe
fallback de modelo por recusa/erro de turno** (busca = 0; o `_FALLBACK` de `model_ids.py:20` é só resolução de
alias desconhecido, antes da chamada); `validate_ci_stage` despacha implementer e ci-triage **sem `model=`**
(`validate_ci_stage.py:39,109`) — ignora a escolha do card; `model_test` é resquício coletado e nunca consumido.

**Gap.** Falta exatamente o que os padrões 4 e 5 pedem: um conceito de perfil por modelo plugado num ponto
único, e a reação a recusa/erro do turno.

**Recomendação.** (1) Estender `model_ids.py` de `alias → str` para `alias → perfil` (`{model_id,
prompt_snippets, fallback_model, notas de quirks}`) com um builder/factory de options consumido por
`stage_runner.run_stage` (`options_kwargs`, `stage_runner.py:154-163` — o choke point de 100% dos estágios,
incluindo os dispatches do validate_ci) e por `agent_chat.stream_response`; (2) no `run_stage`, inspecionar o
fim do turno (subtype/erro do `ResultMessage`, exceções tipadas do SDK) e classificar: erro transiente → 1
retry; recusa → **retry automático com o `fallback_model` do perfil** (ex.: fable-5 → opus-4.8), logando a
troca no card (padrão 4) — sem isso, habilitar o fable-5 nos pickers arrisca cards travando sem explicação;
(3) passar `model=` nos dois dispatches do validate_ci. Detalhe de verificação: como a recusa se manifesta
exatamente através do `claude-agent-sdk` (exceção vs `ResultMessage` de erro vs texto vazio) **não é
verificável estaticamente neste repo** — confirmar na doc oficial do SDK/erros na hora de implementar, e tratar
os três caminhos.

---

## Recomendações por horizonte

Formato: **problema → proposta → valor → esforço (P/M/G) → riscos/dependências.**

### Agora (simples — dá para fazer já, sem incerteza)

**A1. Pacote de robustez do run** *(dimensão 2)*
Exceção fora do estágio deixa `Execution RUNNING` órfã e bloqueia `/answer`; restart não recupera nada →
try/except de topo em `run_pipeline` → `finish_pause`; sweep no boot (`RUNNING` órfã → `PAUSED` + comentário) →
o loop nunca mais "some" sem explicação; retomada sempre possível → **P** → risco ~zero; nenhum comportamento
novo, só o caminho de erro.

**A2. Review falha-fechada + anti-parada-prematura** *(dimensões 2, padrão 1)*
Review sem JSON aprova o diff; agente pode encerrar turno com promessa e o pipeline commita → sem parse do
review: 1 re-pedido e depois pausa; snippet anti-parada-prematura + contrato de término no append do system
prompt dos 4 estágios → fecha as duas falhas abertas do caminho do merge → **P** → risco: pausa a mais em
reviewer teimoso (aceitável; hoje o erro é na direção perigosa).

**A3. Notificação de pausa + coluna paused visível** *(dimensão 8)*
Humano não fica sabendo que o pipeline parou por ele → handler global do evento de pausa + toast + contador
"aguardando você" no TopNav; `paused` para o início do board (order no seed) → reduz o gargalo nº 1 de fluidez
(tempo de resposta humana) → **P** → sem dependências; `useToast` já existe órfão.

**A4. Contexto real no prompt do estágio** *(dimensão 4)*
Agentes recebem só título+descrição; prompt hardcoda "AGENTS.md"; `.md` prometem inputs que não chegam → passar
`project.rules_file`, nome/objetivo do projeto e (novo campo) quem pediu via `build_stage_prompt`; alinhar os
`.md` ao contrato real → decisões dos agentes calibradas pelo contexto; menos pausa por falta de base → **P** →
exige 2 colunas novas (Card.requested_by, Project.objective) via light_migrations (padrão já existente).

**A5. Telemetria mínima de autonomia e custo** *(dimensão 5)*
Tokens/modelo nunca gravados, custo invisível na UI, zero métricas de autonomia → gravar `usage`/`model_used`
do ResultMessage + `pause_count`/`fix_iterations` na Execution; renderizar `costUsd` no card → "% de cards sem
intervenção" e custo/card viram queries; base para medir o efeito de tudo o mais desta lista → **P** → nenhum.

**A6. Higiene do chat** *(dimensão 6)*
Contexto com colunas legadas (sem paused/validate_ci), atividades vazando entre projetos, curl sem projectId →
refazer `_get_kanban_context` sobre o workflow config + escopo por projeto + projectId no template → chat
finalmente responde "o que está pausado e por quê" → **P** → nenhum.

### Próximo (médio — integração/design, caminho claro)

**N1. Perfis por modelo + tratamento de recusa com fallback** *(dimensão 10; padrões 4 e 5)*
Recusa/erro suave do turno é invisível; nada distingue modelos → `model_ids.py` vira registry de perfis
(`{model_id, snippets, fallback_model}`) + builder único de options; `run_stage` classifica o fim do turno e
faz retry/fallback conforme o perfil → multi-modelo real; fable-5 habilitável com rede de segurança; menos
pausas inexplicáveis → **M** → dependência: confirmar na doc do SDK como a recusa se manifesta (exceção vs
result de erro); fazer A2 antes (para o texto vazio não passar).

**N2. Router de complexidade no execute** *(dimensão 1)*
Toda tarefa percorre o pipeline inteiro → estágio de triagem (agente barato, prompt derivado do router
Leve/Padrão/Exploratória da skill) decide coluna inicial via `resume_stage` + registra justificativa → tarefas
triviais 2-3× mais baratas/rápidas; base para trilhas profundas depois → **M** → riscos: roteamento raso demais
(mitigar: na dúvida, Padrão — critério já escrito na skill; override manual = escolher a coluna). Depende de N1
para rodar a triagem em modelo barato com fallback.

**N3. Gate de escalação (clarifier) + memória de decisões** *(dimensão 3; padrão 3)*
Toda dúvida pausa; decisões humanas se perdem → clarifier como gate pré-pausa (score 0–3, fontes) + tabela
`decisions` por projeto reinjetada no clarifier/plan → menos interrupções; o "consultar decisões semelhantes
anteriores" da visão nasce aqui → **M** → riscos: decidir errado com score inflado (mitigar: registrar fonte
verificável + começar conservador só no plan); seeds a partir de `activity_logs` existentes.

**N4. Dispatcher dirigido pelo config** *(dimensões 1 e 9)*
`agentKey`/`isPausedState` persistidos e ignorados; colunas novas não executam nada → `_pipeline_handles`/
`STAGE_AGENTS` passam a ler o config; specifier/clarifier/tasker plugáveis como colunas → workflows por área
viram possíveis sem tocar no motor; trilha Padrão completa (spec→clarify→plan→tasks) vira config → **M** →
risco: regressão no fluxo dev (mitigar: seed `dev` inalterado + testes de orquestração existentes, 43 unit).

**N5. `send_to_user` + auditoria de tool calls** *(dimensão 5; padrão 2)*
Progresso depende do agente narrar; não se sabe o que o agente fez → tool in-process (SDK MCP) `send_to_user`
gravando progresso no card + instrução explícita de uso no system prompt; capturar ToolUse/ToolResult como
ExecutionLog tipado + persistir o prompt do estágio → card mostra "o que estou fazendo agora"; auditoria vira
"total" de verdade → **M** → volume de log cresce (aceitável; SQLite aguenta, e é princípio da visão).

**N6. Fechar o ciclo no board + limpeza da UI legada** *(dimensão 8)*
Merge não é detectado; dois sistemas de status no card → poll leve do PR em ready_to_merge → badge/auto-move
para done; remover `useAgentExecution`/badges/botões legados (item explícito de remoção, como manda a regra) →
o fluxo principal fica coerente de ponta a ponta → **M** → remoção precisa de smoke no board (dívida já
mapeada no ARQUITETURA_E_ESTADO).

### Explorar (alto potencial, incerto — com o spike que tira a dúvida)

**E1. Cenário B — projeto do zero** *(dimensão 7)*
Não há nascimento de projeto pela plataforma → bootstrap (`git init` + `AGENTS.md` do discovery) + roteiro de
discovery de negócio no chat + decomposição em cards → abre o segundo cenário inteiro da visão → **G** →
**spike barato:** criar 1 projeto novo real end-to-end usando só o bootstrap mínimo + chat atual guiado à mão;
medir onde o clarifier/planner travam em greenfield antes de desenhar a UX definitiva.

**E2. Memória de lições pós-run** *(dimensões 3 e 5; padrão 3 pleno)*
Além das decisões (N3): lições de execução (o que falhou, o que o fix corrigiu) reinjetadas em runs futuros →
etapa pós-run que destila 1 lição em Markdown (uma por arquivo, resumo de 1 linha) por projeto, injetada no
plan/implement → potencial de reduzir fix-loops recorrentes → **M/G** → **spike:** gerar lições de 5 runs do
spike-loop-test e medir se o plan as usa (A/B manual barato) antes de automatizar.

**E3. Auto-merge com salvaguardas** *(visão de longo prazo)*
Registrado apenas como Explorar, conforme a regra vigente e inegociável: **humano decide o merge, sempre**.
Pré-requisitos antes de sequer o spike: telemetria de autonomia madura (A5) + histórico de reviews confiáveis
(A2/N1) + política de risco por projeto. Nenhuma mudança imediata.

**E4. `/say` robusto (falar sem parar)** *(dimensão 2)*
Já tentado e revertido (2026-07-05, pendura a etapa); o endpoint existe sem UI → retomar só com
`receive_response` com timeout no 1º chunk, como a nota de reversão já aponta → **M** → spike técnico curto no
SDK antes de reexpor na UI; até lá, Stop→corrige→retoma cobre o caso.

---

## Sequência sugerida

1. **A1 + A2 (blindar o loop)** — primeiro porque tudo o mais assume que "rodar até estar pronto" é confiável;
   hoje as duas falhas abertas (run órfão, review que aprova sem parse) corrompem qualquer métrica ou autonomia
   construída em cima. É também o pré-requisito honesto para aumentar o volume de cards reais.
2. **A3 + A5 + A6 (visibilidade)** — com o loop confiável, atacar o gargalo humano (descoberta da pausa) e ligar
   a telemetria que vai **medir** o efeito de todo o resto (custo/card, % sem intervenção). Barato e independente.
3. **A4 (contexto no prompt)** — enriquece as decisões dos agentes antes de dar mais autonomia a eles; alimenta
   N2 e N3.
4. **N1 (perfis + recusa)** — a fundação multi-modelo vem antes do router porque a triagem/estágios baratos só
   são seguros com fallback de recusa funcionando; também é o que destrava o fable-5 nos pickers.
5. **N2 → N4 (router, depois dispatcher config-driven)** — o router entrega valor imediato com mudança mínima
   (coluna inicial); a generalização do dispatcher vem em seguida e abre a trilha Padrão completa
   (specifier/clarifier/tasker) e os workflows de outras áreas (dimensão 9) — conectando com o roadmap original
   do design v1 ("outros setores entram como novas configs de workflow").
6. **N3 (escalação + decisões)** — com contexto (A4), telemetria (A5) e trilhas (N2) no lugar, o gate de
   escalação tem insumo para decidir bem — e a métrica de pausas mostra o ganho.
7. **N5 + N6 (auditoria profunda + ciclo fechado no board)** — consolidação de experiência; N6 inclui a remoção
   planejada da UI legada, já anotada como dívida.
8. **E1/E2 via spikes** — cenário B e memória de lições entram por experimentos baratos definidos acima, sem
   comprometer o fluxo dev que já está provado.

Racional geral: **confiabilidade → visibilidade → contexto → multi-modelo → adaptatividade → memória**. Cada
passo aumenta autonomia ou fluidez de forma mensurável (A5 garante isso) sem reabrir decisões de arquitetura já
tomadas e sem remover nada fora de item explícito e planejado.
