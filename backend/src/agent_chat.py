"""
Integration with Claude Agent SDK for chat functionality.
This module handles the communication with Claude AI using the Agent SDK.
"""
from typing import AsyncGenerator
from pathlib import Path
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ResultMessage,
)
from .config.model_ids import resolve_model_id


class ClaudeAgentChat:
    """Handler for Claude Agent SDK integration"""

    def __init__(self):
        """Initialize the Claude Agent Chat handler"""
        # No need for API key - Agent SDK uses Claude Code authentication
        pass

    async def stream_response(
        self,
        messages: list[dict],
        model: str = "sonnet-5",
        system_prompt: str | None = None,
        cwd: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream response from Claude using Agent SDK directly
        without predefined commands like /question

        Args:
            messages: List of conversation messages in format [{"role": "user/assistant", "content": "..."}]
            model: AI model to use (e.g., "opus-4.8", "sonnet-5", "haiku-4.5")
            system_prompt: Optional system prompt to set context
            cwd: Working directory for the agent (defaults to the process cwd)

        Yields:
            str: Chunks of the response text as they arrive
        """
        print(f"[ClaudeAgentChat] stream_response called with model: {model}")

        try:
            resolved_cwd = Path(cwd) if cwd else Path.cwd()

            agent_model = resolve_model_id(model)

            # Build conversation context
            # Instead of using /question command, send direct prompt with full context
            full_prompt = ""

            # Add system prompt if provided
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n"

            # Add conversation history
            if len(messages) > 1:
                full_prompt += "Previous conversation:\n"
                for msg in messages[:-1]:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    full_prompt += f"{role}: {msg['content']}\n"
                full_prompt += "\n"

            # Add current user message
            user_message = messages[-1]["content"]
            full_prompt += f"User: {user_message}\n\nAssistant:"

            # Configure Claude Agent SDK Options - same as /plan but with appropriate tools
            options = ClaudeAgentOptions(
                cwd=resolved_cwd,  # Use project root
                setting_sources=["user", "project"],
                allowed_tools=[
                    "Read",      # Read files
                    "Bash",      # Execute commands
                    "Glob",      # Search files
                    "Grep",      # Search content
                    "WebSearch", # Web search capability
                    "WebFetch",  # Fetch web content
                    "Task",      # Launch agents for complex tasks
                    "Skill",     # Use skills
                ],
                permission_mode="bypassPermissions",  # Auto-approve for chat
                model=agent_model,
            )

            # Execute query directly without command prefix
            async for message in query(prompt=full_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            # Stream text content
                            yield block.text
                elif isinstance(message, ResultMessage):
                    # Log para debug, mas NÃO faz yield do resultado
                    # pois o conteúdo já foi enviado através dos TextBlocks
                    if hasattr(message, "result") and message.result:
                        print(f"[ClaudeAgentChat] ResultMessage received (not yielding): {len(message.result)} chars")

        except Exception as e:
            error_msg = f"Error in Claude Agent SDK: {str(e)}"
            print(f"[ClaudeAgentChat] {error_msg}")
            raise RuntimeError(error_msg)


# Default system prompt for the chat assistant
DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant integrated into a Kanban board application.

## Capabilities

You can help users with:
- Understanding and managing their tasks
- Planning and organizing their workflow
- Answering questions about software development
- Providing coding assistance and best practices
- General questions and conversations

## Creating Cards - IMPORTANT

You CAN create cards in the Kanban board! When the user asks to:
- "criar um card/tarefa/ticket/issue"
- "adicionar ao backlog"
- "preciso fazer X" (implies a task)
- "create a card/task"

Use the Bash tool to call the API directly (replace PROJECT_ID with the projectId from the "Projeto atual" section below):

```bash
curl -s -X POST http://localhost:3001/api/cards \
  -H "Content-Type: application/json" \
  -d '{
    "title": "TITULO_AQUI",
    "description": "DESCRICAO_AQUI",
    "projectId": "PROJECT_ID",
    "modelPlan": "opus-4.8",
    "modelImplement": "sonnet-5",
    "modelReview": "haiku-4.5"
  }'
```

### Model defaults (use unless user specifies otherwise):
- Plan: opus-4.8 (best for planning)
- Implement: sonnet-5 (good balance)
- Review: haiku-4.5 (fast for review)

### Available models:
- Claude: opus-4.8, sonnet-5, haiku-4.5

If user specifies a model (e.g., "use sonnet for everything"), adjust accordingly.

After creating, confirm to the user that the card was created and is in the backlog.

## Guidelines

- Be concise, friendly, and helpful
- When discussing code, provide clear examples
- Keep responses focused and actionable"""


# Singleton instance
_claude_agent_instance = None


def get_claude_agent() -> ClaudeAgentChat:
    """Get or create the Claude Agent instance"""
    global _claude_agent_instance
    if _claude_agent_instance is None:
        _claude_agent_instance = ClaudeAgentChat()
    return _claude_agent_instance
