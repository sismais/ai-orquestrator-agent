"""Runner minimo (Fase 3b): executa um agente do DevKit numa git worktree do projeto-alvo.

Para um card: cria worktree isolada (pristina) do repo do projeto, invoca o SDK com cwd=worktree,
coleta os logs/custo, e devolve o resultado. O papel de cada estagio vem do system_prompt
(`stage_runner` le o `.md` do agente de `devkit/.claude/agents`), entao NAO copiamos o DevKit
pra worktree — ela fica so com o codigo real do projeto (o `.claude` do projeto permanece intacto).
NAO faz merge, NAO abre PR (isso e 3c). Auth do SDK = login do Claude Code CLI (assinatura Max).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock, ResultMessage

from ..git_workspace import GitWorkspaceManager, WorktreeResult

# repo raiz = .../ai-orquestrator-agent ; runner_service.py em backend/src/services/
DEVKIT_CLAUDE = Path(__file__).resolve().parents[3] / "devkit" / ".claude"


@dataclass
class RunnerResult:
    success: bool
    worktree_path: Optional[str] = None
    branch_name: Optional[str] = None
    logs: list = field(default_factory=list)
    result_text: Optional[str] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


def build_prompt(title: str, description: str, worktree: str) -> str:
    task = f"{title}. {description}".strip().rstrip(".")
    return (
        f"Voce esta trabalhando no repositorio em `{worktree}` (worktree isolada). "
        f"Implemente a tarefa a seguir editando o codigo e criando/atualizando testes quando fizer sentido. "
        f"Se existir um AGENTS.md na raiz, siga as regras dele. Faca commits nao e necessario. "
        f"Ao terminar, resuma em uma linha o que mudou.\n\nTarefa: {task}"
    )


async def prepare_worktree(project_path: str, base_branch: Optional[str], card_id: str) -> WorktreeResult:
    """Cria a worktree pristina (checkout do projeto). Retorna o WorktreeResult do git_workspace.

    NAO injeta o DevKit na worktree: o backend e o orquestrador e o papel de cada estagio vem do
    system_prompt (`stage_runner` le o `.md` do agente direto de `devkit/.claude/agents`). Assim a
    worktree fica so com os arquivos reais do projeto — o `.claude` do projeto (skills/agentes dele)
    permanece intacto e e commitado normalmente; o DevKit nunca polui a branch da feature.
    Para injetar skills-padrao Sismais nos agentes no futuro, usar `plugins=[{type:local,path}]`
    (provado no spike 2026-07-03), com `skills` filtrado so pro DevKit (evita puxar skills globais do host).
    """
    gm = GitWorkspaceManager(project_path)
    await gm.recover_state()
    return await gm.create_worktree(card_id, base_branch or None)


async def run_card(title: str, description: str, project_path: str, base_branch: Optional[str],
                    card_id: str, on_log=None) -> RunnerResult:
    """Executa a implementacao do card na worktree. on_log(str) e chamado a cada chunk de texto (opcional)."""
    wt = await prepare_worktree(project_path, base_branch, card_id)
    if not wt.success:
        return RunnerResult(success=False, error=wt.error or "falha ao criar worktree")

    worktree = wt.worktree_path
    prompt = build_prompt(title, description, worktree)
    options = ClaudeAgentOptions(
        cwd=worktree,
        setting_sources=["project"],
        allowed_tools=["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep", "TodoWrite"],
        permission_mode="acceptEdits",
    )

    logs: list[str] = []
    result_text = None
    cost = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        logs.append(block.text)
                        if on_log:
                            on_log(block.text)
            elif isinstance(message, ResultMessage):
                result_text = getattr(message, "result", None)
                cost = getattr(message, "total_cost_usd", None)
    except Exception as e:  # noqa: BLE001
        return RunnerResult(success=False, worktree_path=worktree, branch_name=wt.branch_name,
                             logs=logs, error=str(e))

    return RunnerResult(success=True, worktree_path=worktree, branch_name=wt.branch_name,
                         logs=logs, result_text=result_text, cost_usd=cost)
