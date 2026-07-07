import src.models  # noqa: F401
from src.services.pipeline_service import stage_model_for_column


def test_stage_model_for_column_maps_stage_to_card_field():
    class FakeCard:
        model_plan = "opus-4.8"
        model_implement = "sonnet-5"
        model_review = "haiku-4.5"
    card = FakeCard()
    assert stage_model_for_column("plan", card) == "opus-4.8"
    assert stage_model_for_column("implement", card) == "sonnet-5"
    assert stage_model_for_column("review", card) == "haiku-4.5"
    assert stage_model_for_column("validate_ci", card) is None
