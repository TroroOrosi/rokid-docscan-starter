import json
from pathlib import Path

from app.layout import parse_layout, primary_question, segment_problems

FORM_PACK_PATH = (
    Path(__file__).resolve().parent / "fixtures/answer_forms/cases.json"
)


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


def test_segment_problems_page_figure_reaches_every_same_page_problem():
    # One page with two numbered problems and a single page-level figure
    # reading: we cannot tell which problem references the figure, so the
    # figure block must reach BOTH — the figure-dependent problem is never
    # solved without its values, rather than the figure landing only on the
    # last problem on the page.
    pages = [
        (0, "問1 次の図のピークを答えよ\n問2 別の設問に答えよ", "図: グラフのピークは3である"),
    ]
    problems = segment_problems(pages)
    assert [p.question_no for p in problems] == ["問1", "問2"]
    assert "グラフのピークは3である" in problems[0].body_text
    assert "グラフのピークは3である" in problems[1].body_text


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


def test_kanji_and_letter_sub_questions_split():
    text = "\n".join([
        "第1問 次の問いに答えよ。",
        "(三) 傍線部の理由を述べよ。",
        "(A) 自由英作文を書け。",
        "（Ａ） 全角の英字も設問である。",
    ])
    numbers = [p.question_no for p in segment_problems([(0, text)])]
    assert numbers == ["第1問", "(三)", "(A)", "(Ａ)"]


def test_mid_text_parentheses_are_not_sub_questions():
    text = "\n".join([
        "第1問 次の問いに答えよ。",
        "第一次大戦（1914）について述べよ。",
        "A) りんご",
    ])
    units = segment_problems([(0, text)])
    assert [p.question_no for p in units] == ["第1問"]
    assert units[0].choices == ["りんご"]


def test_answer_form_pack_segments_to_section_headings_only():
    # Pins measured reality, not the design goal: tests/fixtures/answer_forms/
    # cases.json stores each page's OCR as a single line (no "\n"), and
    # parse_layout only ever splits on line breaks, so a sub-question marker
    # that would be line-leading in real, multi-line OCR is mid-line here and
    # is never seen as a boundary. All eight forms therefore collapse to their
    # 第N問/大問N heading(s) with zero sub-question deck rows -- the
    # whole-section fallback, not the per-sub-question split this feature is
    # for. Whether real device OCR emits actual line breaks (which would make
    # this a non-issue in production) is untested here; see
    # docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md.
    expected = {
        "K01": ["第1問"],
        "K02": ["第2問"],
        "T01": ["第3問"],
        "T02": ["第1問", "第2問", "第4問"],
        "K03": ["第2問"],
        "K04": ["第3問"],
        "T03": ["第5問"],
        "T04": ["第1問", "第2問", "第4問"],
    }
    cases = {
        c["id"]: c
        for c in json.loads(FORM_PACK_PATH.read_text(encoding="utf-8"))["cases"]
    }
    assert set(cases) == set(expected)
    for case_id, want in expected.items():
        pages = cases[case_id]["input"]["pages"]
        materials = [(i, p["text"]) for i, p in enumerate(pages)]
        units = [p.question_no for p in segment_problems(materials)]
        assert units == want, case_id


def test_a_daimon_numbered_in_kanji_is_one_problem_with_an_arabic_label():
    """東大 and most 記述式 papers write 第一問, not 第1問.

    The deck addresses a problem by this string, so the two spellings must not
    become two problems.
    """
    from app.layout import segment_problems

    problems = segment_problems([
        (0, "第一問 次の文章を読んで答えよ。"),
        (1, "第二問 以下の設問に答えよ。"),
    ])

    assert [p.question_no for p in problems] == ["第1問", "第2問"]


def test_a_repeated_daimon_heading_continues_that_problem_instead_of_splitting_it():
    """An exam booklet prints a 第N問 side tab on EVERY page of that 大問.

    Measured on the 2026 共通テスト 数学Ⅰ・Ａ PDF: without this, 4 大問 across
    26 pages became 26 problems -- 26 solver calls instead of 4, each seeing
    only its own page.
    """
    from app.layout import segment_problems

    problems = segment_problems([
        (0, "第1問 四角形 ABCD の面積 S について考えよう。"),
        (1, "第1問 ク , ケ の解答群"),
        (2, "第1問 点 O を中心とする円を考える。"),
        (3, "第2問 花子さんの記録を考える。"),
    ])

    assert [p.question_no for p in problems] == ["第1問", "第2問"]
    assert problems[0].page_indexes == [0, 1, 2]
    assert "解答群" in problems[0].body_text and "点 O" in problems[0].body_text


def test_a_repeated_shoumon_number_under_two_daimon_stays_two_problems():
    # 問1 under 第1問 and 問1 under 第2問 are different questions; only the
    # 大問-level number repeats as a page tab.
    from app.layout import segment_problems

    problems = segment_problems([
        (0, "第1問 リード文\n問1 これを答えよ"),
        (1, "第2問 別のリード文\n問1 これも答えよ"),
    ])

    assert [p.question_no for p in problems] == ["第1問", "問1", "第2問", "問1(2)"]


def test_letter_choices_under_a_small_question_stay_choices():
    """RP-12a: (A)(B) lines under 問N are its choices, not extra deck problems."""
    units = segment_problems([(0, "問1 Choose one\n(A) apple\n（Ｂ） orange\n問2 Next")])
    assert [p.question_no for p in units] == ["問1", "問2"]
    assert units[0].choices == ["(A) apple", "（Ｂ） orange"]


def test_letter_markers_directly_under_a_major_question_still_split():
    # 東大英語 1(A)/1(B) are separate problems of one 大問.
    units = segment_problems([(0, "第1問\n(A) 要約せよ。\n(B) 和訳せよ。")])
    assert [p.question_no for p in units] == ["第1問", "(A)", "(B)"]
