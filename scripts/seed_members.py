"""One-off script to load a {name, children} JSON tree into a family tree.

Each node may also carry an optional "title" (chức vị).

Usage: uv run python scripts/seed_members.py path/to/tree.json [--tree-slug SLUG]

Without --tree-slug the only tree is used (a default one is created on an empty database);
with several trees you must say which one.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.tenants import get_or_create_default_tree, get_tree_by_slug  # noqa: E402
from app.db.session import get_session_maker  # noqa: E402
from app.models.member import Member  # noqa: E402
from app.models.tree import Tree  # noqa: E402


async def seed_tree(session: AsyncSession, tree_data: dict, tree: Tree) -> int:
    """Insert `tree_data` (parents before children, siblings in order) into `tree`; returns the count."""
    count = 0

    async def insert(node: dict, parent_id: int | None) -> None:
        nonlocal count
        member = Member(
            tree_id=tree.id, full_name=node["name"], parent_id=parent_id, title=node.get("title")
        )
        session.add(member)
        await session.flush()
        count += 1
        for child in node.get("children", []):
            await insert(child, member.id)

    await insert(tree_data, None)
    await session.commit()
    return count


async def _main(path: str, tree_slug: str | None) -> None:
    with open(path, encoding="utf-8") as f:
        tree_data = json.load(f)
    async with get_session_maker()() as session:
        if tree_slug:
            tree = await get_tree_by_slug(session, tree_slug)
            if tree is None:
                raise SystemExit(f"no tree with slug {tree_slug!r}")
        else:
            trees = (await session.execute(select(Tree).order_by(Tree.id))).scalars().all()
            if len(trees) > 1:
                raise SystemExit("several trees exist: pass --tree-slug (see: manage.py list)")
            tree = trees[0] if trees else await get_or_create_default_tree(session)
        count = await seed_tree(session, tree_data, tree)
    print(f"Seeded {count} members into tree {tree.slug!r}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path")
    parser.add_argument("--tree-slug")
    args = parser.parse_args()
    asyncio.run(_main(args.path, args.tree_slug))


if __name__ == "__main__":
    main()
