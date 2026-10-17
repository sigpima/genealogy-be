"""Administration commands (trees, users, roles). See app/cli.py or run with --help.

Usage: uv run python scripts/manage.py create-tree --name "Nguyễn Tộc" --slug nguyen-toc
"""

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from app.cli import run  # noqa: E402
from app.db.session import get_session_maker  # noqa: E402


async def _main(argv: list[str]) -> int:
    async with get_session_maker()() as session:
        output = await run(argv, session)
    print(output)
    return 1 if output.startswith("error:") else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
