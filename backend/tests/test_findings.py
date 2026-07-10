from src.services.findings import (
    parse_review_findings,
    parse_pending_questions,
    detect_needs_human,
)


def test_pure_json():
    text = '{"blocks":[{"titulo":"x"}],"fixNow":[],"suggestions":[{"titulo":"s"}]}'
    f = parse_review_findings(text)
    assert len(f["blocks"]) == 1 and len(f["fixNow"]) == 0 and len(f["suggestions"]) == 1


def test_json_in_fence_with_prose():
    text = (
        "Segue minha analise do diff.\n"
        "```json\n"
        '{"blocks": [], "fixNow": [{"titulo":"bug","arquivo":"a.py:1","porque":"z"}], "suggestions": []}\n'
        "```\n"
        "Fim."
    )
    f = parse_review_findings(text)
    assert len(f["fixNow"]) == 1 and len(f["blocks"]) == 0


def test_no_json_returns_empty():
    f = parse_review_findings("nao houve nada relevante")
    assert f == {"blocks": [], "fixNow": [], "suggestions": []}


def test_last_json_wins():
    text = '{"blocks":[{"a":1}]} depois {"blocks":[],"fixNow":[]}'
    f = parse_review_findings(text)
    assert len(f["blocks"]) == 0


def test_parse_review_findings_strict_devolve_none_sem_json():
    from src.services.findings import parse_review_findings_strict
    assert parse_review_findings_strict("") is None
    assert parse_review_findings_strict("parece tudo certo, aprovado!") is None
    assert parse_review_findings_strict('{"outra": "coisa"}') is None


def test_parse_review_findings_strict_parseia_json_valido():
    from src.services.findings import parse_review_findings_strict
    f = parse_review_findings_strict('bla ```json\n{"blocks":[],"fixNow":[{"titulo":"x"}]}\n```')
    assert f == {"blocks": [], "fixNow": [{"titulo": "x"}], "suggestions": []}


def test_pending_questions_present():
    text = 'plano...\n{"pendingQuestions":[{"question":"q1"},{"question":"q2"}]}'
    assert len(parse_pending_questions(text)) == 2


def test_pending_questions_absent():
    assert parse_pending_questions("plano sem pendencias") == []


def test_needs_human_detected():
    assert detect_needs_human("resultado: status: needs_human (migration arriscada)") is not None


def test_needs_human_absent():
    assert detect_needs_human("status: done, tudo certo") is None
