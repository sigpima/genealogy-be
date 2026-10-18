"""Google Maps links for burials and places: only https links to Google Maps are kept, and a position is read from them when they carry one."""

import re
from urllib.parse import urlsplit

MAX_LENGTH = 500
MAPS_HOSTS = {"google.com", "www.google.com", "maps.google.com", "maps.app.goo.gl"}
SHORT_PATH_HOST = "goo.gl"  # only goo.gl/maps/... is Google Maps

_NUMBER = r"(-?\d{1,3}(?:\.\d+)?)"
_PATTERNS = (
    re.compile(rf"@{_NUMBER},{_NUMBER}"),
    re.compile(rf"!3d{_NUMBER}!4d{_NUMBER}"),
    re.compile(rf"[?&](?:q|ll|query)={_NUMBER}(?:,|%2C){_NUMBER}(?:&|$)"),
    re.compile(rf"/maps/place/{_NUMBER},{_NUMBER}(?:/|$|\?)"),
)


def clean_map_url(value: str | None) -> str | None:
    """The trimmed link, None for blank; ValueError when it is not an https link to Google Maps."""
    if value is None:
        return None
    url = value.strip()
    if not url:
        return None
    if len(url) > MAX_LENGTH:
        raise ValueError(f"the link must be at most {MAX_LENGTH} characters")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise ValueError("the link must not contain spaces or line breaks")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise ValueError("not a valid link") from None
    if parts.scheme.lower() != "https":
        raise ValueError("the link must start with https://")
    if parts.username is not None or parts.password is not None or port not in (None, 443):
        raise ValueError("not a Google Maps link")
    if host in MAPS_HOSTS or (host == SHORT_PATH_HOST and parts.path.startswith("/maps")):
        return url
    raise ValueError("not a Google Maps link (google.com/maps, maps.app.goo.gl)")


def coordinates_from(url: str) -> tuple[float, float] | None:
    """(latitude, longitude) when the link carries them in one of the usual forms, else None (a short link does not)."""
    for pattern in _PATTERNS:
        found = pattern.search(url)
        if found:
            lat, lng = float(found.group(1)), float(found.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None
