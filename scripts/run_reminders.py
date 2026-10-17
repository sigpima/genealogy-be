"""Send due reminders. `--interval N` keeps running (the compose `worker` service uses 3600); without it, run once.

Safe to run as often as you like: reminders are de-duplicated per user (see app/jobs/reminders.py).
"""

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.getcwd())

from app.db.session import get_session_maker  # noqa: E402
from app.jobs.reminders import send_due_reminders  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reminders")


async def run_once() -> None:
    async with get_session_maker()() as session:
        result = await send_due_reminders(session)
    log.info("reminders: %s", result)


async def main(interval: int) -> None:
    while True:
        try:
            await run_once()
        except Exception:  # noqa: BLE001 - a failed round (database restarting...) must not kill the worker
            log.exception("reminder round failed; will retry")
        if interval <= 0:
            return
        await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=0, help="seconds between rounds (0 = run once and exit)")
    asyncio.run(main(parser.parse_args().interval))
