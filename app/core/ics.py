"""A minimal iCalendar (RFC 5545) writer for the family calendar feed: all-day events with stable UIDs."""

from datetime import datetime, timedelta, timezone

from app.core.calendar_items import Item


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Lines are at most 75 octets; continuation lines start with one space. Never split inside a UTF-8 character."""
    parts, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        limit = 75 if not parts else 74  # a continuation line spends one octet on its leading space
        if size + width > limit:
            parts.append(current)
            current, size = "", 0
        current += char
        size += width
    parts.append(current)
    return [parts[0]] + [" " + p for p in parts[1:]]


def build_calendar(name: str, items: list[Item], now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//gia-pha//lich-gio//VI",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "X-WR-TIMEZONE:Asia/Ho_Chi_Minh",
    ]
    for item in items:
        source = item.member_id if item.kind == "death_anniversary" else item.event_id
        description = [item.subtitle] if item.subtitle else []
        if item.time_text:
            description.append(f"Lúc {item.time_text}")
        if item.description:
            description.append(item.description)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{item.kind}-{source}-{item.date:%Y%m%d}@gia-pha",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{item.date:%Y%m%d}",
            f"DTEND;VALUE=DATE:{item.date + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(item.title)}",
        ]
        if description:
            lines.append(f"DESCRIPTION:{_escape(chr(10).join(description))}")
        if item.location:
            lines.append(f"LOCATION:{_escape(item.location)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(folded for line in lines for folded in _fold(line)) + "\r\n"
