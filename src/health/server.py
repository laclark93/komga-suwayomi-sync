import logging

from aiohttp import web

logger = logging.getLogger(__name__)


class HealthServer:
    """Minimal HTTP server for Docker health checks."""

    def __init__(self, port: int, sse_connected_fn):
        self._port = port
        self._sse_connected_fn = sse_connected_fn
        self._runner = None

    async def start(self):
        app = web.Application()
        app.router.add_get("/health", self._health_handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await site.start()
        logger.info("Health server listening on port %d", self._port)

    async def _health_handler(self, request):
        return web.json_response(
            {
                "status": "ok",
                "sse_connected": self._sse_connected_fn(),
            }
        )

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
