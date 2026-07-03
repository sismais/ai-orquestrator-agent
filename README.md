# 🚀 Sismais AI Orquestrador

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![Node](https://img.shields.io/badge/node-18+-green)

Painel Kanban que **dirige e acompanha agentes de IA** (o Sismais AI DevKit) operando sobre projetos reais: cada coluna é uma etapa executada por uma skill-agente, orquestrada pelo backend numa git worktree isolada por card, com logs ao vivo — parando no *ready-to-merge* para o humano aprovar e fazer o merge.

> **Fork** de [eduwxyz/orquestrator-agent](https://github.com/eduwxyz/orquestrator-agent) ("Zenflow"), sob licença MIT — atribuição preservada em [LICENSE](LICENSE). Repositório privado da Sismais Tecnologia.

## ✨ Features

- 📋 **Workflow Board Visual** - Interface moderna para gerenciamento de tarefas
- 🤖 **Claude Agent Integration** - Execute tarefas automaticamente com IA
- 🌲 **Git Worktree Automation** - Isolamento automático de branches
- 📊 **Métricas e Dashboard** - Acompanhe custos e progresso
- 💬 **Chat Integrado** - Converse com Claude sobre o projeto
- 🔄 **Workflow Automation** - Pipeline plan → implement → test → review → done

## 🎯 Use Cases

- Desenvolvimento de features com IA
- Code review automatizado
- Geração de testes
- Refatoração assistida
- Documentação automática

## 📋 Requisitos

### Sistema
- Python 3.9+
- Node.js 18+
- Git 2.30+
- Claude Code CLI

### API Keys
- Anthropic API Key (Claude)
- Google Generative AI Key (opcional para Gemini)

## 🚀 Instalação Rápida

```bash
# 1. Clone o repositório
git clone https://github.com/seu-usuario/zenflow.git
cd zenflow

# 2. Instale Claude Code CLI
curl -fsSL https://claude.ai/install.sh | bash

# 3. Configure as variáveis de ambiente
cp backend/.env.example backend/.env
# Edite backend/.env com suas API keys

# 4. Instale dependências
npm run setup

# 5. Inicie o sistema
npm run dev
```

Acesse http://localhost:5173

## 🏗️ Arquitetura

### Stack Tecnológica
- **Frontend**: React + TypeScript + Vite
- **Backend**: FastAPI + Python
- **Database**: SQLite (multi-database)
- **IA**: Claude Agent SDK + Gemini
- **UI**: CSS Modules + Lucide Icons

### Estrutura do Projeto
```
zenflow/
├── frontend/          # Interface React
├── backend/           # API FastAPI
├── .claude/          # Comandos e skills do Agent SDK
├── specs/            # Especificações de tarefas
└── docs/             # Documentação
```

## 📖 Como Usar

### 1. Criar um Novo Card
- Clique em "New Task" no board
- Descreva a tarefa desejada
- Selecione o modelo de IA (Claude/Gemini)

### 2. Executar Workflow Automatizado
- Arraste o card para "Plan" → Gera especificação
- Mova para "Implement" → Executa implementação
- Continue para "Test" → Executa testes
- Finalize em "Review" → Revisão de código

### 3. Comandos Disponíveis
- `/plan` - Criar plano de implementação
- `/implement` - Executar implementação
- `/test-implementation` - Validar e testar
- `/review` - Revisar código
- `/dev-workflow` - Pipeline completo

## ⚙️ Configuração

### Backend (.env)
```env
ANTHROPIC_API_KEY=your-key
GOOGLE_API_KEY=your-key-optional
DATABASE_URL=sqlite+aiosqlite:///./backend/auth.db
SECRET_KEY=your-secret-key
```

### Claude Agent SDK
Configure comandos customizados em `.claude/commands/`
Configure skills em `.claude/skills/`

## 🔧 Desenvolvimento

### Estrutura de Database
- **auth.db**: Database principal (users, cards, executions)
- **.claude/database.db**: Database por projeto
- **project_history.db**: Histórico de projetos

### API Endpoints
- `POST /api/cards` - Criar card
- `GET /api/cards` - Listar cards
- `PUT /api/cards/{id}` - Atualizar card
- `POST /api/execute/{id}` - Executar card
- `WS /ws/execution/{id}` - Stream de execução

## 🤝 Contribuindo

Veja [CONTRIBUTING.md](docs/CONTRIBUTING.md) para diretrizes.

## 📝 Troubleshooting

### Claude Code não encontrado
```bash
# Reinstale o CLI
curl -fsSL https://claude.ai/install.sh | bash
```

### Database não inicializa
```bash
# Reset database
rm backend/auth.db
python backend/src/main.py  # Recria automaticamente
```

## 📄 Licença

MIT License - veja [LICENSE](LICENSE)

## 🙏 Créditos

- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk)
- [FastAPI](https://fastapi.tiangolo.com/)
- [React](https://react.dev/)
