import inspect
from src.agent_chat import get_claude_agent


def test_stream_response_accepts_cwd_param():
    sig = inspect.signature(get_claude_agent().stream_response)
    assert "cwd" in sig.parameters


def test_agent_chat_source_has_no_active_project():
    import src.agent_chat as m
    src = inspect.getsource(m)
    assert "ActiveProject" not in src  # cwd vem por parametro, nao do ActiveProject
