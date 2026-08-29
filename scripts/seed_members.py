"""One-off script to load a {name, children} JSON tree into the members table.

Usage: uv run python scripts/seed_members.py path/to/tree.json
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from app.db.session import get_session_maker  # noqa: E402
from app.models.member import Member  # noqa: E402


async def _seed(tree: dict) -> None:
    session_maker = get_session_maker()
    async with session_maker() as session:

        async def insert(node: dict, parent_id: int | None) -> None:
            member = Member(full_name=node["name"], parent_id=parent_id)
            session.add(member)
            await session.flush()
            for child in node.get("children", []):
                await insert(child, member.id)

        await insert(tree, None)
        await session.commit()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/seed_members.py path/to/tree.json")
        raise SystemExit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        tree = json.load(f)

    asyncio.run(_seed(tree))
    print("Seed complete.")


if __name__ == "__main__":
    main()
