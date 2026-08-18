"""Cista logika vidljivosti uslovnih pitanja."""

from app.services.survey_visibility import (
    AnswerValue,
    QuestionSpec,
    compute_visibility,
)


def test_unconditional_question_visible():
    qs = [QuestionSpec(id=1, tip_pitanja="TEXT")]
    vis = compute_visibility(qs, {})
    assert vis[1] is True


def test_boolean_equals_condition():
    qs = [
        QuestionSpec(id=1, tip_pitanja="BOOLEAN"),
        QuestionSpec(id=2, tip_pitanja="TEXT", uslov_pitanje_id=1, uslov_operator="EQUALS", uslov_vrednosti=["false"]),
    ]
    # kontrolno = false -> zavisno vidljivo
    vis = compute_visibility(qs, {1: AnswerValue(logicka=False)})
    assert vis[2] is True
    # kontrolno = true -> zavisno skriveno
    vis = compute_visibility(qs, {1: AnswerValue(logicka=True)})
    assert vis[2] is False


def test_hidden_when_control_unanswered():
    qs = [
        QuestionSpec(id=1, tip_pitanja="BOOLEAN"),
        QuestionSpec(id=2, tip_pitanja="TEXT", uslov_pitanje_id=1, uslov_operator="NOT_EQUALS", uslov_vrednosti=["true"]),
    ]
    vis = compute_visibility(qs, {})  # kontrolno nema odgovor
    assert vis[2] is False


def test_choice_in_operator():
    qs = [
        QuestionSpec(id=1, tip_pitanja="SINGLE_CHOICE"),
        QuestionSpec(id=2, tip_pitanja="TEXT", uslov_pitanje_id=1, uslov_operator="IN", uslov_vrednosti=["10", "11"]),
    ]
    vis = compute_visibility(qs, {1: AnswerValue(opcija_ids=[11])})
    assert vis[2] is True
    vis = compute_visibility(qs, {1: AnswerValue(opcija_ids=[99])})
    assert vis[2] is False


def test_nested_condition_hidden_control_hides_dependent():
    qs = [
        QuestionSpec(id=1, tip_pitanja="BOOLEAN"),
        QuestionSpec(id=2, tip_pitanja="BOOLEAN", uslov_pitanje_id=1, uslov_operator="EQUALS", uslov_vrednosti=["true"]),
        QuestionSpec(id=3, tip_pitanja="TEXT", uslov_pitanje_id=2, uslov_operator="EQUALS", uslov_vrednosti=["true"]),
    ]
    # 1=false -> 2 skriveno -> 3 skriveno iako bi 2 "odgovor" bio tacan
    vis = compute_visibility(qs, {1: AnswerValue(logicka=False), 2: AnswerValue(logicka=True)})
    assert vis[2] is False
    assert vis[3] is False