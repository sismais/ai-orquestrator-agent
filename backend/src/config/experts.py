"""Expert agents configuration.

Defines available expert agents and their detection criteria.
Each expert has:
- name: Display name
- knowledge_path: Path to KNOWLEDGE.md file (relative to project root)
- keywords: Words that suggest this expert is relevant
- file_patterns: File path patterns this expert specializes in

IMPORTANTE:
- Quando NÃO há projeto carregado (project_path=None): usa ORCHESTRATOR_EXPERTS
- Quando há projeto carregado: carrega dinamicamente do projeto
"""

import json
from pathlib import Path
from typing import Dict, List, TypedDict, Optional


class ExpertConfig(TypedDict):
    """Configuration for a single expert agent."""
    name: str
    knowledge_path: str
    keywords: List[str]
    file_patterns: List[str]


# =============================================================================
# ORCHESTRATOR EXPERTS (usados quando NÃO há projeto externo carregado)
# Estes são os experts específicos do projeto orquestrador-agent
# =============================================================================
ORCHESTRATOR_EXPERTS: Dict[str, ExpertConfig] = {
    "database": {
        "name": "Database Expert",
        "knowledge_path": ".claude/commands/experts/database/KNOWLEDGE.md",
        "keywords": [
            "model", "database", "migration", "campo", "tabela", "SQL",
            "repository", "banco", "sqlite", "sqlalchemy", "query",
            "schema", "foreign key", "index", "coluna", "ORM",
            "persistencia", "dados", "armazenamento"
        ],
        "file_patterns": [
            "backend/src/models/",
            "backend/migrations/",
            "backend/src/repositories/",
            "backend/src/database",
            "backend/src/schemas/"
        ]
    },
    "kanban-flow": {
        "name": "Kanban Flow Expert",
        "knowledge_path": ".claude/commands/experts/kanban-flow/KNOWLEDGE.md",
        "keywords": [
            "card", "coluna", "transicao", "workflow", "kanban", "board",
            "drag", "drop", "arrastar", "mover", "backlog", "plan",
            "implement", "test", "review", "done", "SDLC", "automacao",
            "lifecycle", "ciclo de vida"
        ],
        "file_patterns": [
            "frontend/src/components/Board/",
            "frontend/src/components/Card/",
            "frontend/src/components/Column/",
            "frontend/src/hooks/useWorkflow",
            "frontend/src/hooks/useAgent",
            "backend/src/routes/cards"
        ]
    },
    "frontend": {
        "name": "Frontend Expert",
        "knowledge_path": ".claude/commands/experts/frontend/KNOWLEDGE.md",
        "keywords": [
            "react", "componente", "component", "hook", "useState", "useEffect",
            "tsx", "jsx", "css", "estilo", "style", "layout", "UI", "interface",
            "dnd-kit", "drag", "drop", "vite", "typescript", "frontend",
            "pagina", "page", "modal", "form", "input", "button", "theme",
            "dark mode", "light mode", "responsive", "mobile"
        ],
        "file_patterns": [
            "frontend/src/components/",
            "frontend/src/hooks/",
            "frontend/src/pages/",
            "frontend/src/api/",
            "frontend/src/types/",
            "frontend/src/utils/",
            "frontend/src/contexts/",
            "frontend/src/styles/"
        ]
    },
    "backend": {
        "name": "Backend Expert",
        "knowledge_path": ".claude/commands/experts/backend/KNOWLEDGE.md",
        "keywords": [
            "fastapi", "api", "endpoint", "route", "rota", "service", "servico",
            "python", "pydantic", "schema", "dto", "websocket", "ws",
            "streaming", "async", "await", "agent", "claude", "gemini",
            "chat", "execution", "workflow", "backend", "servidor", "server"
        ],
        "file_patterns": [
            "backend/src/routes/",
            "backend/src/services/",
            "backend/src/schemas/",
            "backend/src/config/",
            "backend/src/main.py",
            "backend/src/agent",
            "backend/src/execution.py"
        ]
    },
    "chat": {
        "name": "Chat Expert",
        "knowledge_path": ".claude/commands/experts/chat/KNOWLEDGE.md",
        "keywords": [
            "chat", "mensagem", "message", "conversa", "streaming",
            "websocket", "ws", "ia", "ai", "claude", "gemini",
            "contexto", "context", "kanban context"
        ],
        "file_patterns": [
            "frontend/src/components/Chat/",
            "backend/src/agent_chat.py",
            "backend/src/routes/chat.py"
        ]
    }
}

# Alias para compatibilidade com código existente
AVAILABLE_EXPERTS = ORCHESTRATOR_EXPERTS

# Cache de experts por projeto
_experts_cache: Dict[str, Dict[str, ExpertConfig]] = {}


def get_experts(project_path: Optional[str] = None) -> Dict[str, ExpertConfig]:
    """
    Retorna experts apropriados baseado no contexto.

    Args:
        project_path: Caminho do projeto carregado ou None se não houver

    Returns:
        - Se project_path é None → retorna ORCHESTRATOR_EXPERTS (comportamento atual)
        - Se project_path existe → carrega dinamicamente do projeto
    """
    # SEM projeto carregado = usar experts do orquestrador
    if project_path is None:
        return ORCHESTRATOR_EXPERTS

    # COM projeto carregado = carregar dinamicamente
    return _load_project_experts(project_path)


def _load_project_experts(project_path: str) -> Dict[str, ExpertConfig]:
    """
    Carrega experts de um projeto externo.

    Busca em: {project_path}/.claude/commands/experts/
    Cada expert deve ter um config.json com: name, keywords, file_patterns
    """
    if project_path in _experts_cache:
        return _experts_cache[project_path]

    experts_dir = Path(project_path) / ".claude" / "commands" / "experts"

    if not experts_dir.exists():
        _experts_cache[project_path] = {}
        return {}

    experts: Dict[str, ExpertConfig] = {}

    for expert_dir in experts_dir.iterdir():
        if not expert_dir.is_dir():
            continue

        config_file = expert_dir / "config.json"
        knowledge_file = expert_dir / "KNOWLEDGE.md"

        # Precisa ter config.json para ser válido
        if not config_file.exists():
            continue

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            expert_id = expert_dir.name
            experts[expert_id] = {
                "name": config.get("name", f"{expert_id.title()} Expert"),
                "knowledge_path": f".claude/commands/experts/{expert_id}/KNOWLEDGE.md",
                "keywords": config.get("keywords", []),
                "file_patterns": config.get("file_patterns", [])
            }
        except (json.JSONDecodeError, IOError) as e:
            print(f"[experts] Failed to load expert {expert_dir.name}: {e}")
            continue

    _experts_cache[project_path] = experts
    return experts


def clear_experts_cache(project_path: Optional[str] = None):
    """
    Limpa cache de experts.

    Args:
        project_path: Se fornecido, limpa apenas o cache deste projeto.
                     Se None, limpa todo o cache.
    """
    global _experts_cache
    if project_path:
        _experts_cache.pop(project_path, None)
    else:
        _experts_cache = {}


def get_expert_config(expert_id: str, project_path: Optional[str] = None) -> Optional[ExpertConfig]:
    """
    Get configuration for a specific expert.

    Args:
        expert_id: ID do expert
        project_path: Caminho do projeto (None = orquestrador)
    """
    experts = get_experts(project_path)
    return experts.get(expert_id)


def get_all_expert_ids(project_path: Optional[str] = None) -> List[str]:
    """
    Get list of all available expert IDs.

    Args:
        project_path: Caminho do projeto (None = orquestrador)
    """
    experts = get_experts(project_path)
    return list(experts.keys())
