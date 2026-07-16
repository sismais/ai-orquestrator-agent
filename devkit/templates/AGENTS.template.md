# AGENTS.md — regras do projeto <nome do projeto>

> Fonte de verdade para agentes de IA (e humanos) neste repositório. Curto e prescritivo:
> **o que está escrito aqui não se pergunta de novo.**

## O projeto

- **O que é:** <uma frase — produto, público, propósito>
- **Objetivo atual:** <o que este ciclo/fase está tentando alcançar>

## Stack e comandos

- **Stack:** <linguagens/frameworks principais>
- **Rodar local:** `<comando>`
- **Validar antes de entregar:** `<comando único de lint/build/testes que o agente SEMPRE roda>`

## Fluxo git e deploy

- **Branch:** <direto na main | branch de feature + PR>
- **Push na main:** <permitido sem perguntar? sim/não>
- **Deploy:** <como publica; se push na main = deploy de produção, diga aqui>
- **Nunca:** <ex.: force-push, reescrever histórico, tocar tags de release>

## Convenções

- **Idioma:** <ex.: código e nomes de arquivo em inglês; UI, comentários e docs em pt-BR>
- <padrões que o agente segue: estilo, estrutura de pastas, mobile-first, testes onde…>

## Regras de negócio críticas

- <regras que nunca podem ser violadas; cite o arquivo/módulo onde cada uma vive>

## Zonas de risco — pausar e perguntar antes

- <ex.: migrations/schema, RLS/Supabase, dados de produção, cobrança, integração fiscal>

## O agente pode, sem perguntar

- <ex.: refatorar localmente, criar/ajustar testes, corrigir bug óbvio, commitar após validar>
