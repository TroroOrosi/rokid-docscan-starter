from app.layout import parse_layout, primary_question


def test_detects_question_number_and_choices():
    text = "問2 次の計算をせよ\n① 12\n② 13\n③ 14\n④ 15"
    parsed = parse_layout(text)
    q = primary_question(parsed)
    assert q.question_no == "問2"
    assert len(q.choices) == 4


def test_full_width_digits_normalized():
    parsed = parse_layout("問３ あ")
    assert primary_question(parsed).question_no == "問3"


def test_page_number_and_figures_extracted():
    parsed = parse_layout("P.12 第1問 図2 を見よ")
    assert parsed["page_number"] == 12
    q = primary_question(parsed)
    assert any("図" in f for f in q.figure_refs)


def test_answer_box_from_keyword_is_normalized():
    parsed = parse_layout("問1 解答欄に記入せよ")
    box = parse_layout("問1 解答欄に記入せよ")["answer_box"]
    assert box is not None
    for k in ("x", "y", "w", "h"):
        assert 0.0 <= box[k] <= 1.0


def test_answer_box_from_bbox_hint_is_used():
    hints = [{"text": "解答欄", "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}}]
    parsed = parse_layout("問1 本文", bbox_hints=hints)
    assert parsed["answer_box"]["estimated"] is False
    assert parsed["answer_box"]["x"] == 0.1


def test_empty_text_is_safe():
    parsed = parse_layout(None)
    assert parsed["questions"] == []
    assert primary_question(parsed) is None
