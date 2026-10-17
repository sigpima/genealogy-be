from app.core.text import fold


def test_fold_drops_tone_marks_whatever_their_placement():
    assert fold("Nguyễn Văn Hòa") == fold("nguyen van hoa") == fold("NGUYỄN VĂN HOÀ")
    assert fold("hoà") == fold("hòa") == "hoa"


def test_fold_handles_d_stroke_and_spacing():
    assert fold("  Đặng   Đình  ") == "dang dinh"


def test_fold_normalises_decomposed_input():
    decomposed = "Nguyễn"  # e + circumflex + tilde as separate code points
    assert fold(decomposed) == "nguyen"


def test_fold_of_nothing():
    assert fold("") == "" and fold("   ") == ""
