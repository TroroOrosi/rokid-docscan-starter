from app.layout import parse_layout, primary_question, segment_problems


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


def test_compound_words_do_not_create_question_boundaries():
    # 学問/質問/疑問… inside prose must not fabricate numbered problems.
    text = "学問1について論じよ\n筆者の疑問2は次の通り\nこの質問3に答えよ"
    parsed = parse_layout(text)
    assert parsed["headings"] == []
    # Everything stays in one unnumbered body unit.
    assert len(parsed["questions"]) == 1
    assert parsed["questions"][0].question_no is None


def test_paren_numbers_only_count_at_line_start():
    # Mid-line parentheses (years, inline notes) are not boundaries...
    parsed = parse_layout("第一次世界大戦（1914）が勃発した")
    assert parsed["headings"] == []
    # ...but a line-leading （2） is a genuine sub-question marker.
    parsed = parse_layout("（2） 下線部の理由を答えよ")
    assert parsed["headings"] == ["(2)"]


def test_decimal_leading_line_is_not_a_choice():
    parsed = parse_layout("問1 長さを求めよ\n1.5メートルの棒がある")
    q = primary_question(parsed)
    assert q.choices == []
    assert "1.5メートルの棒" in q.body_text


# ---------------------------------------------------------------------------
# segment_problems (whole-document segmentation for the 3-phase exam flow)
# ---------------------------------------------------------------------------


def test_segment_problems_splits_on_boundaries_across_pages():
    pages = [
        (0, "問1 りんごは何個か\n① 1\n② 2"),
        (1, "問2 みかんは何個か"),
    ]
    problems = segment_problems(pages)
    assert [p.question_no for p in problems] == ["問1", "問2"]
    assert problems[0].start_page_index == 0
    assert problems[0].choices == ["1", "2"]
    assert problems[1].start_page_index == 1
    assert problems[1].page_indexes == [1]


def test_segment_problems_merges_cross_page_continuation():
    # 問1 starts on page 0 and its text continues at the top of page 1.
    pages = [
        (0, "問1 次の文章を読み"),
        (1, "続きの本文がここにある\n問2 別の問題"),
    ]
    problems = segment_problems(pages)
    assert [p.question_no for p in problems] == ["問1", "問2"]
    assert "続きの本文" in problems[0].body_text
    assert problems[0].page_indexes == [0, 1]
    assert problems[0].start_page_index == 0


def test_segment_problems_shares_page_leading_prompt_with_next_problem():
    # A page that opens with a prompt/passage before the next numbered problem:
    # text alone cannot tell continuation from prompt, so the block goes to
    # BOTH the previous problem (continuation) and the next one (prompt).
    pages = [
        (0, "問1 前半の本文"),
        (1, "次の文章を読んで答えよ\n問2 下線部について述べよ"),
    ]
    problems = segment_problems(pages)
    assert [p.question_no for p in problems] == ["問1", "問2"]
    assert "次の文章を読んで答えよ" in problems[0].body_text  # continuation
    assert problems[0].page_indexes == [0, 1]
    assert problems[1].body_text.startswith("次の文章を読んで答えよ")  # prompt
    assert problems[1].start_page_index == 1


def test_segment_problems_figure_labels_do_not_split_question():
    # A single OCR question with a labelled table in vision_text: the (1)/(2)
    # figure labels must NOT create extra deck problems, and the row values
    # must stay in the problem body for solving.
    pages = [
        (0, "問1 次の表から最大の月を答えよ", "表:\n(1) 4月 100\n(2) 5月 200\n(3) 6月 150"),
    ]
    problems = segment_problems(pages)
    assert [p.question_no for p in problems] == ["問1"]
    assert "(2) 5月 200" in problems[0].body_text
    assert "【図・画像の読み取り】" in problems[0].body_text


def test_segment_problems_figure_only_fallback_keeps_values():
    # No numbered boundary, values only in the figure reading: the single
    # fallback problem must still carry them.
    pages = [(0, "参考資料", "グラフ: 最高気温は35度")]
    problems = segment_problems(pages)
    assert len(problems) == 1
    assert "35度" in problems[0].body_text


def test_segment_problems_falls_back_to_single_problem():
    pages = [(0, "境界のない本文だけ"), (1, "二ページ目の本文"), (2, "")]
    problems = segment_problems(pages)
    assert len(problems) == 1
    p = problems[0]
    assert p.question_no is None
    assert "境界のない本文だけ" in p.body_text
    assert "二ページ目の本文" in p.body_text
    assert p.page_indexes == [0, 1]  # empty page 2 carries no content


def test_segment_problems_folds_preamble_into_first_problem():
    pages = [(0, "受験上の注意 静かに解くこと"), (1, "問1 本文")]
    problems = segment_problems(pages)
    assert len(problems) == 1
    assert problems[0].body_text.startswith("受験上の注意")
    assert problems[0].page_indexes == [0, 1]


def test_segment_problems_dedups_question_numbers():
    # 問1 appears under two 大問 — deck/ingest need unique problem numbers.
    pages = [(0, "大問1 前半\n問1 一つ目"), (1, "大問2 後半\n問1 二つ目")]
    problems = segment_problems(pages)
    nos = [p.question_no for p in problems]
    assert nos == ["大問1", "問1", "大問2", "問1(2)"]


def test_segment_problems_is_deterministic_and_safe_on_empty():
    pages = [(0, "問1 あ"), (1, "問2 い")]
    assert segment_problems(pages) == segment_problems(pages)
    assert segment_problems([]) == []
    assert segment_problems([(0, ""), (1, "  ")]) == []
