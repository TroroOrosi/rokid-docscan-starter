from app.subjects import SUBJECTS, detect_subject


def _subj(text: str) -> str:
    return detect_subject(text)[0]


def test_math():
    assert _subj("2x + 3 = 7 を満たす x を求め、関数 f(x) の微分を計算せよ。") == "数学"


def test_math_bare_arithmetic():
    # Arithmetic-only prompts (+/-) must be detected as math, not default 現代文.
    assert _subj("12+13 を計算せよ") == "数学"
    assert _subj("5−2 を求めよ") == "数学"


def test_physics():
    assert _subj("質量 m の物体の加速度と運動量を求め、速度 v を m/s で答えよ。") == "物理"


def test_chemistry():
    assert _subj("0.1 mol の化合物の酸化還元反応と溶液の pH を求めよ。") == "化学"


def test_biology():
    assert _subj("細胞の遺伝子と DNA、酵素による光合成の代謝を説明せよ。") == "生物"


def test_earth_science():
    assert _subj("地層と火成岩、プレートの境界で起きる地震の震源を答えよ。") == "地学"


def test_modern_japanese():
    assert _subj("次の文章を読んで、傍線部における筆者の主張を本文に即して述べよ。") == "現代文"


def test_classical_japanese():
    assert _subj("次の古文を読み、傍線部の助動詞「けり」の意味を答え、和歌を鑑賞せよ。") == "古文"


def test_kanbun():
    assert _subj("次の漢文を白文で示す。返り点とレ点に従い書き下し文を作れ。") == "漢文"


def test_english():
    assert _subj("Read the following passage and answer the questions below.") == "英語"


def test_world_history():
    assert _subj("ローマ帝国の成立とフランス革命について、世界史の観点で述べよ。") == "世界史"


def test_japanese_history():
    assert _subj("江戸時代の幕府と藩の関係、将軍と天皇について日本史で述べよ。") == "日本史"


def test_geography():
    assert _subj("ケッペンの気候区分と地形、人口と産業について地理的に説明せよ。") == "地理"


def test_civics_political_economy():
    assert _subj("日本国憲法と三権分立、需要と供給、GDP と財政政策について述べよ。") == "政治経済"


def test_ethics():
    assert _subj("ソクラテスとカントの思想、青年期の倫理について述べよ。") == "倫理"


def test_informatics():
    assert _subj("擬似言語で配列を用いたアルゴリズムを書き、2進数の論理演算を説明せよ。") == "情報"


def test_empty_is_unknown():
    assert detect_subject("")[0] == "unknown"
    assert detect_subject(None)[0] == "unknown"


def test_confidence_in_range_and_subject_valid():
    subj, conf = detect_subject("関数の微分と積分を計算せよ。")
    assert subj in SUBJECTS
    assert 0.0 <= conf <= 1.0
