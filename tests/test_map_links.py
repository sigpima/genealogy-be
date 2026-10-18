"""Google Maps links: what is accepted, and what coordinates can be read from them."""

import pytest

from app.core.map_links import clean_map_url, coordinates_from

GOOD = [
    "https://www.google.com/maps/place/H%C3%A0+N%E1%BB%99i/@21.0285,105.8542,15z",
    "https://google.com/maps?q=21.03,105.85",
    "https://maps.google.com/?q=21.03,105.85",
    "https://maps.app.goo.gl/AbCd123",
    "https://goo.gl/maps/xyz",
    "HTTPS://WWW.GOOGLE.COM/maps/place/x",
]

BAD = [
    "http://www.google.com/maps/place/x",
    "javascript:alert(1)",
    "https://evil.com/maps",
    "https://google.com.evil.com/maps",
    "https://google.com@evil.com/",
    "https://www.google.com:8443@evil.com/maps",
    "https://goo.gl/other",
    "ftp://maps.google.com/x",
    "www.google.com/maps",
    "https://www.google.com/maps/place/x\nSet-Cookie: a=b",
    "https://www.google.com/maps/" + "a" * 500,
]


@pytest.mark.parametrize("url", GOOD)
def test_google_maps_links_are_accepted(url):
    assert clean_map_url(url) == url.strip()


@pytest.mark.parametrize("url", BAD)
def test_other_links_are_refused(url):
    with pytest.raises(ValueError):
        clean_map_url(url)


def test_blank_is_none():
    assert clean_map_url(None) is None
    assert clean_map_url("   ") is None


def test_surrounding_spaces_are_trimmed():
    assert clean_map_url("  https://maps.app.goo.gl/AbCd123  ") == "https://maps.app.goo.gl/AbCd123"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.google.com/maps/place/Ha+Noi/@21.0285,105.8542,15z", (21.0285, 105.8542)),
        ("https://www.google.com/maps/place/x/data=!3d10.5!4d106.25", (10.5, 106.25)),
        ("https://www.google.com/maps?q=21.03,105.85", (21.03, 105.85)),
        ("https://maps.google.com/?ll=-33.86,151.21&z=10", (-33.86, 151.21)),
        ("https://www.google.com/maps/place/21.5,105.5", (21.5, 105.5)),
        ("https://www.google.com/maps/@-12.5,-77.0,10z", (-12.5, -77.0)),
    ],
)
def test_coordinates_are_read_when_the_link_carries_them(url, expected):
    assert coordinates_from(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://maps.app.goo.gl/AbCd123",
        "https://www.google.com/maps/place/Ha+Noi",
        "https://www.google.com/maps/@95.0,10.0,15z",
        "https://www.google.com/maps/@10.0,190.0,15z",
        "",
    ],
)
def test_no_coordinates_otherwise(url):
    assert coordinates_from(url) is None
