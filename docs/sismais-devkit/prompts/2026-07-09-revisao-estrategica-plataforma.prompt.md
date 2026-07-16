---
proposito: Prompt de revisão estratégica da plataforma (análise de gap entre visão de produto e estado atual)
execucao: Claude Code + Fable 5, effort xhigh, sessão somente-análise (sem implementação)
resultado: docs/sismais-devkit/specs/2026-07-09-revisao-estrategica-plataforma.md
---
# Revisão estratégica da plataforma de orquestração de agentes

## Papel

Atue como engenheiro sênior especialista em arquitetura de agentes de IA, engenharia de loops agênticos e orquestração multi-agente aplicada a desenvolvimento de software (foco principal), com visão de expansão futura para trabalho criativo (marketing/vendas) e administrativo (análise de dados, criação de materiais).

## Contexto

Este repo é o Sismais AI Orquestrador: painel Kanban que dirige agentes de IA (Claude Code via `claude-agent-sdk`) sobre projetos reais. O backend orquestra cada coluna numa git worktree isolada por card, com logs, e para no ready-to-merge — não faz merge sozinho.

A plataforma é **multi-modelo por design**: opera vários LLMs (configuráveis por etapa do Kanban), começando pelos modelos da Anthropic e expandindo futuramente para outros provedores. Nenhuma recomendação deve assumir um único modelo fixo.

Antes de qualquer análise, leia nesta ordem:

1. `docs/ARQUITETURA_E_ESTADO.md` — arquitetura ativa, fases concluídas, o que foi removido
2. `docs/sismais-devkit/notes/2026-06-17-fork-code-map.md` — mapa do código
3. `docs/DESENVOLVIMENTO.md` — como rodar e gotchas
4. Specs/planos em `docs/sismais-devkit/{specs,plans}/` conforme precisar de detalhe por fase (OBS: podem estar obsoletos)

É um fork do Zenflow em reforma: não confie em comportamento legado. O que os docs dizem que foi removido, foi removido.

**Checkpoint obrigatório:** após a leitura, apresente no chat um resumo de até 5 linhas do seu entendimento do estado atual (o que existe, o que é parcial, o que não existe) **antes** de iniciar a análise. Prossiga em seguida sem aguardar confirmação, mas registre esse resumo também no início do documento final.

## Visão de produto (north star)

O usuário (dev, PO, CEO ou gerente) descreve **o que** quer; os agentes trabalham em loop — planejam, executam, revisam e corrigem — até estar pronto para merge, com o mínimo de intervenção humana.

**Cenário A — feature em projeto existente:** o pedido chega como card (painel ou API). A plataforma avalia a complexidade e traça o workflow proporcional: tarefa trivial vai direto para correção; complexa exige spec → plano → implementação → múltiplas revisões. Para decidir, considera quem pede, qual o projeto, e qual o objetivo final.

**Cenário B — projeto novo do zero:** a IA faz apenas perguntas de regra de negócio (arquitetura ela decide sozinha e só pede confirmação), planeja, executa e entrega a v1 utilizável.

## Princípios que a análise deve respeitar

- **Autonomia máxima:** a IA decide tudo que puder; antes de acionar um humano, um agente revisor julga se a dúvida realmente exige humano (inclusive consultando decisões semelhantes anteriores). Humano só como último recurso, aguardando resposta no card.
- **Auditoria total:** todo stream da IA registrado.
- **Humano decide o merge**, sempre — regra vigente e inegociável no estado atual. Auto-merge com salvaguardas é visão de longo prazo: se surgir na análise, entra apenas como item **Explorar**, nunca como mudança imediata.
- **Usuário pensa em regra de negócio / user story**, nunca em arquitetura.
- **Chat agnóstico a tarefas**, escopado pelo projeto selecionado, capaz de responder sobre qualquer worktree aberta e sobre tarefas já fechadas.
- **Multi-modelo:** requests, system prompts e tratamento de erros não podem ficar acoplados a um modelo específico.
- **UX/UI:** "Não Me Faça Pensar" + heurísticas de Nielsen; padrões consistentes; arquitetura modular.
- **Mentalidade MVP** com expansão futura; equipe pequena; preservar o que funciona.

### Decisões de arquitetura já tomadas (não reabrir)

O `CLAUDE.md` do repo foi renomeado de propósito nesta sessão para não influenciar a análise; estas regras essenciais dele continuam valendo:

- **Banco único** `backend/orchestrator.db` via `DATABASE_URL`, tenant-shaped por `project_id` — o legado multi-arquivo/`ActiveProject` foi removido e não deve voltar.
- **O backend orquestra**; coluna = etapa; workflow é config (tabela `Workflow`, seed `dev`), não hardcoded.
- **O DevKit** (`devkit/.claude/`) não é copiado para a worktree — o papel de cada estágio vem do `system_prompt` e a worktree fica pristina.
- **Auth do SDK = assinatura Max do CLI** (sem `ANTHROPIC_API_KEY`); execução real gasta Max — teste real só no repo `maiconsaraiva/spike-loop-test`.
- **Remoção de algo existente** é sempre item explícito e planejado, nunca embutido em outra mudança.

## Padrões oficiais da Anthropic a avaliar (insumo da análise)

A documentação da Anthropic (posterior ao seu treinamento, já conferida contra a referência oficial — trate os itens abaixo como corretos) recomenda os padrões a seguir para agentes autônomos. Para detalhes de API além do descrito, consulte a documentação oficial via WebFetch em vez de responder de memória. Para cada padrão, verifique se a plataforma já implementa algo equivalente, e onde não implementa, avalie o encaixe nas dimensões da análise:

1. **Snippet anti-parada-prematura em pipelines autônomos:** instrução de system prompt para o agente executor: "Você está operando de forma autônoma; o usuário não acompanha em tempo real. Antes de encerrar o turno, verifique seu último parágrafo: se for um plano, uma análise, uma pergunta retórica ou uma promessa de trabalho não feito, execute esse trabalho agora com tool calls em vez de encerrar."
2. **Ferramenta `send_to_user`:** tool client-side que entrega mensagens de progresso ao usuário (no card) sem encerrar o turno do agente. Atenção: definir a ferramenta não basta — o system prompt precisa instruir explicitamente quando usá-la.
3. **Memória de lições:** persistir lições aprendidas por execução (pode ser Markdown simples, uma lição por arquivo com resumo de uma linha no topo) e injetá-las em execuções futuras — base concreta para a feature de "decisões anteriores" do agente revisor.
4. **Tratamento de recusa com fallback:** o Claude Fable 5 pode retornar `stop_reason: "refusal"` em trabalho benigno (ex.: temas adjacentes a cibersegurança); a recomendação oficial é fallback automático para outro modelo (ex.: Opus 4.8). O orquestrador precisa tratar isso para o card não travar sem explicação.
5. **Perfis por modelo:** modelos divergem em parâmetros aceitos (Fable 5 rejeita `temperature`, `budget_tokens` e prefill com erro 400), escala de effort, snippets de system prompt e comportamento de recusa. Avalie se existe um ponto único de montagem de request onde "perfis de modelo" (config simples por modelo) possam ser plugados.
6. **Verificação com contexto limpo:** subagentes verificadores com contexto fresco superam a autocrítica do próprio agente — padrão relevante para as etapas de review do Kanban.

Contexto para os padrões 4 e 5: a plataforma fala com os modelos via `claude-agent-sdk` (Claude Code por baixo), não via API Messages direta — o backend não monta `temperature`/`budget_tokens` em request nenhum, e uma recusa se manifesta como resultado/erro do turno do SDK. Avalie nesses termos: como o orquestrador detecta e reage a recusas/erros de turno, e onde perfis por modelo se plugariam na chamada ao SDK (hoje o ponto único parcial é `config/model_ids.py`).

Verifique também se os system prompts dos agentes do DevKit (`devkit/.claude/agents/*.md`) e o system prompt do chat contêm instruções que peçam a **transcrição do raciocínio interno** (chain of thought) na resposta — no Fable 5 isso pode disparar recusas (`reasoning_extraction`) e deve ser sinalizado. Pedidos normais de justificativa ("explique a causa raiz da decisão") não disparam isso.

## Tarefa

Faça uma análise de gap entre a visão acima e o estado atual, dimensão por dimensão:

1. **Roteamento adaptativo de workflow** — hoje o workflow `dev` é fixo por config. Como a plataforma deveria escolher/ajustar o workflow pela complexidade e tipo da tarefa?
2. **Robustez do loop** — fix-loop, Pause-or-Decide, tetos de iteração, retomada, anti-parada-prematura (padrão 1 acima). O que falta para "trabalhar até estar pronto" de forma confiável?
3. **Escalação humana inteligente** — o agente revisor intermediário e a memória de decisões anteriores (padrão 3) existem? O que falta?
4. **Contexto de quem pede** — pessoa/empresa/projeto/objetivo influenciando as decisões dos agentes.
5. **Auditoria e observabilidade** — logs, custos por run, métricas de autonomia (ex.: % de cards concluídos sem intervenção), progresso em tempo real no card (padrão 2).
6. **Chat** — cobertura real sobre worktrees abertas e histórico de tarefas fechadas.
7. **Criação de projeto do zero** (cenário B) — o que existe e o que falta.
8. **UX do painel** — fluidez do fluxo principal (criar card → acompanhar → responder pausa → aprovar merge).
9. **Fundações para expansão** (criativo/administrativo) — apenas o que for barato preparar agora; não desenhar essas verticais ainda.
10. **Abstração multi-modelo** — a montagem de requests, system prompts e tratamento de erros/recusas está acoplada a um modelo específico ou existe ponto único para plugar perfis por modelo (padrões 4 e 5)?

Regras da análise:

- Toda afirmação sobre o estado atual deve ser **verificada no código (cite `arquivo:linha`) ou nos docs** — não assuma pelo nome do arquivo nem pelo comportamento do fork original.
- **Regra de grounding:** só reporte como existente o que você verificou por um resultado de ferramenta nesta sessão (arquivo lido, busca executada). O que não foi verificado, declare explicitamente como "não verificado". Nunca apresente inferência como fato.
- Pode usar subagentes de exploração (Explore) em paralelo para varrer o código.
- **Antes de finalizar o documento**, dispare um subagente verificador com contexto limpo para conferir por amostragem as evidências `arquivo:linha` citadas; corrija o que não se sustentar.
- Poucas recomendações de alto impacto valem mais que uma lista exaustiva — corte o que não muda autonomia ou fluidez.
- **Não implemente nada.** Não proponha remover nada que funciona. Respeite as decisões de arquitetura já tomadas (seção acima). Priorize evolução incremental.

## Saída

Crie `docs/sismais-devkit/specs/2026-07-09-revisao-estrategica-plataforma.md` com:

- **Resumo do estado atual** (o checkpoint de 5 linhas).
- **Sumário executivo** (≤ 10 linhas): as 3–5 melhorias que mais aumentam autonomia e fluidez.
- **Análise por dimensão** (as 10 acima): estado atual (com evidência) → gap → recomendação.
- **Recomendações agrupadas por horizonte:**
  - **Agora (simples):** dá para fazer já, sem incerteza.
  - **Próximo (médio):** exige integração/design, mas o caminho é claro.
  - **Explorar (alto potencial):** promissor porém incerto — indique qual spike/experimento barato tira a dúvida antes de investir.
- Cada recomendação no formato: problema → proposta → valor esperado → esforço (P/M/G) → riscos/dependências.
- **Sequência sugerida:** em que ordem atacar e por quê, conectando com o roadmap existente.

No chat, apresente apenas o checkpoint, o sumário executivo e o caminho do arquivo.
