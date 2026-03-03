import asyncio
import logging
import signal
from pathlib import Path

from .config import Settings
from .health.server import HealthServer
from .komga.client import KomgaClient
from .komga.sse import KomgaSSEListener
from .logging_setup import setup_logging
from .matching.matcher import MangaMatcher
from .suwayomi.client import SuwayomiClient
from .sync.cache import MappingCache
from .sync.engine import SyncEngine
from .sync.unmatched import UnmatchedTitlesLog


async def main():
    settings = Settings()

    setup_logging(settings)
    logger = logging.getLogger("komga-suwayomi-sync")
    logger.info("Starting komga-suwayomi-sync")

    # Persistent unmatched titles log
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    unmatched_log = UnmatchedTitlesLog(log_dir)
    logger.info("Unmatched titles will be recorded to %s", log_dir / "unmatched.txt")

    # Initialize clients
    komga = KomgaClient(settings)
    suwayomi = SuwayomiClient(settings)
    await komga.start()
    await suwayomi.start()

    matcher = MangaMatcher(
        threshold=settings.match_threshold,
        unmatched_log=unmatched_log,
    )
    cache = MappingCache(ttl_seconds=settings.cache_ttl_seconds)
    engine = SyncEngine(komga, suwayomi, matcher, cache, settings)

    # SSE listener
    sse_listener = KomgaSSEListener(
        settings,
        on_read_progress=engine.handle_read_progress_event,
    )

    # Health server
    health = HealthServer(
        port=settings.health_port,
        sse_connected_fn=lambda: sse_listener.connected,
    )
    await health.start()

    # Initial sync
    if settings.initial_sync_on_start:
        try:
            await engine.initial_sync()
        except Exception:
            logger.exception("Initial sync failed, continuing with SSE listener...")

    # Handle graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()
        sse_listener.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Run SSE + polling concurrently
    try:
        await asyncio.gather(
            sse_listener.run(),
            engine.polling_loop(),
        )
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down...")
        await health.stop()
        await komga.close()
        await suwayomi.close()
        logger.info("Shutdown complete")


def entry_point():
    asyncio.run(main())


if __name__ == "__main__":
    entry_point()
