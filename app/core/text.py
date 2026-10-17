import re
import unicodedata

_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    """Search key: no tone marks or diacritics (`đ` -> `d`), lower case, single spaces.

    NFD splits every letter into base + combining marks, so `hòa` and `hoà` (tone mark placed differently), a
    precomposed `ễ` and a decomposed one, and plain `hoa` all fold to the same string.
    """
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("đ", "d").replace("Đ", "d")
    return _SPACES.sub(" ", stripped.lower()).strip()
