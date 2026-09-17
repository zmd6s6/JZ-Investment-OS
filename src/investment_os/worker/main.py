"""Worker bootstrap loop with database-backed readiness."""

import asyncio
import logging
from pathlib import Path

from investment_os.application.health import AsyncClosable, ReadinessProbe
from investment_os.infrastructure.database import DatabaseReadinessProbe
from investment_os.infrastructure.settings import Settings, get_settings

LOGGER = logging.getLogger(__name__)


def _set_ready_marker(ready_file: Path, *, ready: bool) -> None:
    if ready:
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.touch()
    else:
        ready_file.unlink(missing_ok=True)


async def refresh_ready_marker(probe: ReadinessProbe, ready_file: Path) -> bool:
    """Reflect one sanitized readiness check in a local container marker file."""

    check = await probe.check()
    await asyncio.to_thread(_set_ready_marker, ready_file, ready=check.ready)
    return check.ready


async def run_worker(settings: Settings) -> None:
    """Maintain readiness only; scheduled business work begins in later stages."""

    probe = DatabaseReadinessProbe(settings.database_url)
    LOGGER.info("worker_bootstrap_started")
    try:
        while True:
            ready = await refresh_ready_marker(probe, settings.worker_ready_file)
            if not ready:
                LOGGER.warning("worker_database_not_ready")
            await asyncio.sleep(settings.worker_poll_seconds)
    finally:
        await asyncio.to_thread(settings.worker_ready_file.unlink, missing_ok=True)
        if isinstance(probe, AsyncClosable):
            await probe.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_worker(get_settings()))
