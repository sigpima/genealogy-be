"""The book's inline Markdown: bold survives, links/images become text, and backslash escapes (written by the chronicle editor) are literal."""

from app.core.book import _inline


def test_bold_survives_and_links_and_images_become_text():
    assert _inline("**đậm** và [liên kết](https://x.example) ![ảnh](media:3)") == "<b>đậm</b> và liên kết ảnh"


def test_an_escaped_marker_is_shown_literally():
    assert _inline(r"2\*3\*4") == "2*3*4"
    assert _inline(r"snake\_case \[x\]") == "snake_case [x]"
    assert _inline(r"một \\ hai") == "một \\ hai"


def test_an_escaped_star_does_not_close_bold():
    assert _inline(r"**a \* b**") == "<b>a * b</b>"


def test_a_backslash_before_an_ordinary_letter_is_left_alone():
    assert _inline(r"C:\Users và \n") == r"C:\Users và \n"


def test_markup_characters_are_still_escaped_for_the_pdf():
    assert _inline("a < b & c") == "a &lt; b &amp; c"
    assert _inline(r"\*<b>") == "*&lt;b&gt;"
