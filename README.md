# 🚀 Sismais AI Orquestrador

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.13-blue)
![Node](https://img.shields.io/badge/node-20+-green)

Painel Kanban que **dirige e acompanha agentes de IA** (o Sismais AI DevKit) operando sobre projetos reais: cada coluna é uma etapa executada por um agente, orquestrada pelo backend numa git worktree isolada por card, com logs ao vivo — parando no *ready-to-merge* para o humano aprovar e fazer o merge.

> **Fork** de [eduwxyz/orquestrator-agent](https://github.com/eduwxyz/orquestrator-agent) ("Zenflow"), sob licença MIT — atribuição preservada em [LICENSE](LICENSE). Repositório privado da Sismais Tecnologia.

## Comece rápido

Aplicação **local, single-user** (backend + frontend na sua máquina). Pré-requisitos: Python 3.13,
Node 20+, `gh` autenticado (`gh auth login`) e **Claude Code CLI instalado e logado** — o backend
executa os agentes via `claude-agent-sdk` usando a assinatura do CLI (**sem** `ANTHROPIC_API_KEY`).

### IA-first (recomendado)

Cole o prompt abaixo num **Claude Code** (ou outra IA com acesso ao terminal):

```text
Deixe o Sismais AI Orquestrador (painel Kanban da Sismais) rodando na minha máquina.

Fonte da verdade: o repo sismais/ai-orquestrator-agent — README ("Comece rápido") e
docs/DESENVOLVIMENTO.md (passos detalhados e gotchas, principalmente no Windows). Se eu
ainda não tiver o checkout local, pergunte em qual diretório clonar.

Regras: confira os pré-requisitos ANTES de executar (Python 3.13, Node 20+, `gh`
autenticado, Claude Code CLI logado — NÃO use ANTHROPIC_API_KEY); execute os passos
VALIDANDO cada um pelo critério do doc (backend :3001 com "Dev workflow seeded" no log;
frontend :5173 respondendo); quando algo falhar, consulte os gotchas do
DESENVOLVIMENTO.md antes de improvisar; me peça apenas o que exige ação humana (logins).
Ao final: me diga como registrar meu primeiro projeto no painel, como garantir o
AGENTS.md dele e como subir os serviços de novo depois que eu fechar tudo.
```

> Prefere fazer à mão? Os passos abaixo continuam valendo — e são também o **playbook que a
> IA segue** (e o caminho de debug quando algo falhar).

```bash
# 1. Backend (porta 3001)
cd backend
python -m venv venv && . venv/Scripts/activate     # Windows/Git Bash (Linux/Mac: venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env                                # sem API key — usa o login do Claude Code
./venv/Scripts/python.exe -m src.main               # confira no log: "Dev workflow seeded"

# 2. Frontend (porta 5173) — noutro terminal
cd frontend
npm install
printf 'VITE_API_URL=http://localhost:3001\nVITE_WS_URL=ws://localhost:3001\n' > .env
npm run dev
```

Depois, em http://localhost:5173:

3. **Registre o projeto** (seletor no topo): nome, caminho local, branch base, comando de
   validação. O projeto precisa ser um repo git com ≥ 1 commit; remote no GitHub é necessário
   para o estágio de PR/CI.
4. **Garanta o `AGENTS.md` do projeto** — é dele que os agentes tiram as regras (fluxo git,
   zonas de risco, o que podem sem perguntar). O jeito guiado é rodar `/sismais-dev-init` no
   projeto via Claude Code ([plugins do DevKit](https://github.com/sismais/sismais-ai-plugins-private)).
5. **Crie um card no backlog e clique em Run.** O card percorre as colunas com logs ao vivo;
   se o pipeline pausar, a pergunta vira comentário no card — responda e ele retoma sozinho.
   Em `ready_to_merge`, faça o merge no GitHub; o card vai para `done` automaticamente.

Detalhes, testes e gotchas (Windows, processos na 3001, repo-alvo de teste):
[docs/DESENVOLVIMENTO.md](docs/DESENVOLVIMENTO.md).

## Como funciona

- **Workflow como config**: o board renderiza as colunas do workflow `dev`
  (`paused → backlog → plan → implement → review → validate_ci → ready_to_merge → done`);
  transições e agentes por coluna vêm do config em banco.
- **Backend é o orquestrador**: despacha um agente por estágio (prompts do DevKit), faz todo o
  git (commit/push/PR), roda o fix-loop review→implement com teto, espera o CI com triagem de
  falha (related/unrelated) e **nunca faz merge** — regra inegociável.
- **Pause-or-Decide**: o clarifier decide sozinho o que tem base documental (score 0–3 com
  fonte, memória de decisões por projeto); só o genuinamente ambíguo pausa para o humano.
- **Prompts dos agentes** são cópias sincronizadas do
  [`devkit-core`](https://github.com/sismais/sismais-ai-plugins-private) — não edite
  `devkit/.claude/agents/` aqui (ver [devkit/README.md](devkit/README.md)).

## Documentação

| Doc | Conteúdo |
|---|---|
| [docs/DESENVOLVIMENTO.md](docs/DESENVOLVIMENTO.md) | Como rodar, testar, smoke do runner, gotchas |
| [docs/ARQUITETURA_E_ESTADO.md](docs/ARQUITETURA_E_ESTADO.md) | Arquitetura e estado atual (fases/ondas) |
| [devkit/README.md](devkit/README.md) | Camada de agentes + regra de fonte única (devkit-core) |
| [docs/sismais-devkit/specs/](docs/sismais-devkit/specs/) | Histórico de decisões de design |

**Modo terminal (sem painel):** os mesmos agentes rodam como plugins do Claude Code
(CLI/VS Code) — interativo, zero infra, um repo por vez. Ver
[sismais-ai-plugins-private](https://github.com/sismais/sismais-ai-plugins-private).

## 📄 Licença

MIT License - veja [LICENSE](LICENSE)
