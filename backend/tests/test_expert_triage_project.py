import inspect
import src.routes.experts as experts_mod


def test_triage_source_uses_card_project_not_manager():
    src = inspect.getsource(experts_mod.expert_triage_endpoint)
    assert "current_project" not in src  # nao usa mais o ProjectManager
    assert "project_id" in src  # resolve pelo card/registry
