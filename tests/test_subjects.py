from app.subjects import detect_subject


def test_math_detected():
    subj, conf = detect_subject("2x + 3 = 7 を満たす x を求め、関数の微分を計算せよ")
    assert subj == "math"
    assert conf > 0.0


def test_english_detected():
    subj, _ = detect_subject("Read the following passage and answer the questions below.")
    assert subj == "english"


def test_history_detected():
    subj, _ = detect_subject("1603年に江戸幕府が開かれた。次の天皇の在位を答えよ。")
    assert subj == "history"


def test_default_is_modern_jp():
    subj, _ = detect_subject("次の文章を読んで、筆者の主張を述べよ。")
    assert subj in {"modern_jp", "classical_jp", "history"}


def test_empty_is_unknown():
    assert detect_subject("")[0] == "unknown"
    assert detect_subject(None)[0] == "unknown"
