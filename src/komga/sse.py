import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class KomgaSSEListener:
    """
    Connects to Komga's SSE endpoint and dispatches ReadProgressChanged events.
    Implements exponential backoff reconnection.
    """

    def __init__(
        self,
        settings: Settings,
        on_read_progress: Callable[[str, str], Awaitable[None]],
    ):
        base_url = settings.komga_base_url.rstrip("/")
        self._url = f"{base_url}/sse/v1/events"

        self._headers: dict[str, str] = {}
        self._auth: Optional[tuple[str, str]] = None
        if settings.komga_api_key:
            self._headers["X-API-Key"] = settings.komga_api_key
        elif settings.komga_username:
            self._auth = (settings.komga_username, settings.komga_password)

        self._on_read_progress = on_read_progress
        self._reconnect_base = settings.sse_reconnect_delay_seconds
        self._reconnect_max = settings.sse_reconnect_max_delay_seconds
        self._running = False
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def run(self):
        """Main loop: connect, listen, reconnect on failure."""
        self._running = True
        delay = self._reconnect_base

        while self._running:
            try:
                logger.info("Connecting to Komga SSE at %s", self._url)
                await self._listen()
                delay = self._reconnect_base
            except (httpx.HTTPError, httpx.StreamError, ConnectionError) as e:
                self._connected = False
                logger.warning(
                    "SSE connection lost: %s. Reconnecting in %ds", e, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max)
            except asyncio.CancelledError:
                logger.info("SSE listener cancelled")
                self._connected = False
                break
            except Exception:
                self._connected = False
                logger.exception("Unexpected SSE error. Reconnecting in %ds", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max)

    async def _listen(self):
        """Open streaming connection and parse SSE frames."""
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET",
                self._url,
                headers=self._headers,
                auth=self._auth,
            ) as response:
                response.raise_for_status()
                self._connected = True
                logger.info("SSE connected successfully")

                event_type = ""
                data_lines: list[str] = []

                async for line in response.aiter_lines():
                    if not self._running:
                        break

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line == "":
                        # End of event frame
                        if event_type and data_lines:
                            data = "\n".join(data_lines)
                            await self._dispatch(event_type, data)
                        event_type = ""
                        data_lines = []

    async def _dispatch(self, event_type: str, data: str):
        """Route events to handlers."""
        if event_type == "ReadProgressChanged":
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in SSE event: %s", data)
                return

            book_id = payload.get("bookId")
            user_id = payload.get("userId", "")
            if book_id:
                logger.debug(
                    "ReadProgressChanged: book=%s user=%s", book_id, user_id
                )
                try:
                    await self._on_read_progress(book_id, user_id)
                except Exception:
                    logger.exception(
                        "Error handling ReadProgressChanged for book %s", book_id
                    )

    def stop(self):
        self._running = False
        self._connected = False
