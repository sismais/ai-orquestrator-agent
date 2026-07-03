import pytest
from src.database import get_session, async_session_maker


def test_get_session_returns_the_single_maker():
    # get_session deve devolver SEMPRE o async_session_maker unico,
    # sem depender do db_manager multi-arquivo (removido no caminho de sessao).
    assert get_session() is async_session_maker
