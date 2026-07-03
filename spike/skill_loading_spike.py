"""Spike descartavel (Fase 1, Task 3): prova que o claude-agent-sdk reconhece
nossa skill/comando do DevKit quando cwd e uma git WORKTREE (.git = arquivo).

Uso:
    SPIKE_WORKTREE=/caminho/da/worktree python spike/skill_loading_spike.py

Auth: sem ANTHROPIC_API_KEY -> usa o login do Claude Code CLI (assinatura Max).
"""
import asyncio
import os

from claude_agent_sdk import query, ClaudeAgentOptions


async def main():
    worktree = os.environ["SPIKE_WORKTREE"]
    options = ClaudeAgentOptions(
        cwd=worktree,
        setting_sources=["project"],  # le .claude/ da worktree (Plan B: copia por-run)
        allowed_tools=["Skill", "Read", "Glob", "Grep"],
        permission_mode="acceptEdits",
    )
    prompt = (
        "/sismais-dev-fix spike: em UMA linha, confirme que o comando/skill "
        "sismais-dev foi carregado e reconhecido. Nao edite arquivos."
    )

    print(f"[spike] cwd={worktree}")
    print(f"[spike] prompt={prompt!r}\n")

    async for message in query(prompt=prompt, options=options):
        name = type(message).__name__
        # SystemMessage de init costuma listar slash_commands/skills disponiveis
        data = getattr(message, "data", None)
        if data and isinstance(data, dict):
            cmds = data.get("slash_commands") or data.get("commands")
            if cmds:
                sismais = [c for c in cmds if "sismais" in str(c).lower()]
                print(f"[spike] slash_commands sismais visiveis: {sismais or '(nenhum)'}")
        result = getattr(message, "result", None)
        if result:
            print(f"[spike] RESULT: {result}")
        else:
            print(f"[spike] MSG {name}")


if __name__ == "__main__":
    asyncio.run(main())
