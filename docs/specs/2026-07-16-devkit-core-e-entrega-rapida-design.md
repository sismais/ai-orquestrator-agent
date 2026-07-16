# Devkit-core (fonte única de prompts) + premissa de entrega rápida — design

**Data:** 2026-07-16 · **Status:** aprovado pelo mantenedor · **Repos afetados:** este e `ai-orquestrator-agent`.

## Contexto

Os agentes do DevKit vivem duplicados em dois consumidores: os plugins deste repo e o
`devkit/.claude/` da plataforma (`ai-orquestrator-agent`). O drift já é fato: `planner`,
`implementer` e `reviewer` divergiram (só no contrato de entrada) e o `router` existe só na
plataforma. A duplicação dos **motores** (skill+`.mjs` vs backend Python) é intencional e fica;
a duplicação dos **prompts** não é, e é isso que este design elimina.

## Decisões

1. **`devkit-core/` (neste repo) é a fonte única dos prompts de agente** — os 8 `.md`
   (specifier, clarifier, planner, tasker, implementer, reviewer, ci-triage, router) e os
   schemas JSON dos contratos de saída. Ninguém edita as cópias nos consumidores; edita-se o
   core e sincroniza.
2. **Contrato de entrada neutro**: cada agente declara "você recebe no prompt de despacho …"
   sem citar mecanismo do host. Quem preenche é o consumidor (SKILL.md via Task tool;
   `build_stage_prompt` via SDK). Foi exatamente a única divergência observada.
3. **Schemas compartilhados + validação falha-fechada nos dois lados**: os contratos
   reviewer/clarifier/ci-triage/router viram `devkit-core/schemas/*.schema.json` com fixtures
   comuns. A plataforma já valida falha-fechada (`findings.py`); os plugins ganham o
   equivalente (`findings.mjs` + protocolo na SKILL: sem JSON parseável → 1 re-pedido → pausa;
   nunca aprovar por ausência de parse).
4. **Sincronização mecânica**: `devkit-core/sync.mjs` copia core → plugins e (com
   `--platform <path>`) → plataforma, gravando manifest de hashes. CI dos plugins roda
   `sync.mjs --check`; a plataforma ganha um teste pytest que valida os arquivos contra o
   manifest e roda o parser contra as fixtures comuns. Sem submodule, sem dependência runtime.
5. **Divisão de papéis assumida**: plugins = **modo terminal** (interativo, zero infra, um dev
   num repo). Plataforma = **modo autônomo supervisionado** (Kanban, fila, telemetria,
   memória). **Não portamos** para os plugins: Stop, background/logs, recovery, perfis de
   modelo com fallback, multi-projeto — teto de paridade declarado.

## Premissa de entrega rápida (origem: análise do fluxo Lovable)

Mover qualidade de "processo que o humano lê" para "defaults que ninguém pergunta"; artefatos
proporcionais à tarefa. A espinha review independente → validação → CI **fica** (é a vantagem
sobre o Lovable). Aplicado agora, no core:

- **Router por reversibilidade**: critério primário vira reversibilidade × clareza de escopo
  (reversível e localizado → leve; caro de desfazer — migration/RLS/contrato — ou escopo
  incerto → padrão). "Na dúvida, padrão" permanece como desempate.
- **Plano enxuto por padrão**: bullets, legível em ~1 minuto (alvo ≤ 40 linhas); plano longo
  só sob pedido explícito.
- **Disciplina de escopo no implementer**: menor mudança correta; edição pontual em vez de
  rewrite; nada não pedido; relato final curto.

Próximos (fora deste ciclo): pacote de convenções (`AGENTS.md` semeado no bootstrap de projeto
— mata perguntas recorrentes tipo "push na main?"); sinal precoce de progresso nos plugins (a
plataforma já tem via `send_to_user`).

## Fora de escopo

- Reabrir o pivô de 2026-06-17 (plataforma vira plugin) — descartado em análise.
- Unificar os motores ou os scripts de estado (`run-state`/`loop-state` ficam como estão).
- CRUD/sync automático cross-repo via rede — o sync é local, disciplinado por CI.

## Riscos e mitigação

- **Contrato neutro genérico demais** → começar pelos 4 arquivos já idênticos; os 3 divergentes
  unificados mudaram só a linha de entrada (verificado contra os dois despachantes).
- **Sync vira cópia manual com nome bonito** → `--check` na CI dos plugins + manifest test na
  plataforma tornam o drift um build vermelho, não uma descoberta tardia.
- **Router mais permissivo errar para leve** → o custo está declarado no prompt; desempate
  continua conservador; a plataforma registra trilha+justificativa por run para auditar.
