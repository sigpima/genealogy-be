"""Create (or reset) the fake 'demo' family behind /guest.

Usage: uv run python scripts/seed_demo.py     (in Docker: docker compose exec api python scripts/seed_demo.py)

Takes no arguments on purpose: the only tree it can ever touch is the one with slug 'demo' (and the name "Họ Demo
(dữ liệu giả)", and no accounts). Running it again resets the demo to the same data. See DOCKER.md, "Bản demo cho khách".
"""

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.demo import DEMO_SLUG, DemoGuardError, reset_demo  # noqa: E402
from app.db.session import get_session_maker  # noqa: E402


async def _main() -> int:
    url = make_url(get_settings().database_url)
    print(f"Đích: {url.host}:{url.port}/{url.database}")  # before anything is written; the password is never printed
    async with get_session_maker()() as session:
        try:
            summary = await reset_demo(session)
        except DemoGuardError as exc:
            print(f"Dừng, không đổi gì: {exc}", file=sys.stderr)
            return 1
    print(f"Đã đặt lại họ {DEMO_SLUG!r}: {summary.members} người, {summary.spouses} vợ/chồng, {summary.articles} bài.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
