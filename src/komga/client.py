import logging
from typing import Optional

import aiohttp

from ..config import Settings

logger = logging.getLogger(__name__)


class KomgaClient:
    """REST client for the Komga API."""

    def __init__(self, settings: Settings):
        self._base_url = settings.komga_base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

        self._headers: dict[str, str] = {}
        self._auth: Optional[aiohttp.BasicAuth] = None
        if settings.komga_api_key:
            self._headers["X-API-Key"] = settings.komga_api_key
        elif settings.komga_username:
            self._auth = aiohttp.BasicAuth(
                settings.komga_username, settings.komga_password
            )

    async def start(self):
        self._session = aiohttp.ClientSession(
            headers=self._headers,
            auth=self._auth,
        )

    async def close(self):
        if self._session:
            await self._session.close()

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self._base_url}{path}"
        async with self._session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_book(self, book_id: str) -> dict:
        """Get a single book by ID, including readProgress."""
        return await self._get(f"/api/v1/books/{book_id}")

    async def get_series(self, series_id: str) -> dict:
        """Get a single series by ID."""
        return await self._get(f"/api/v1/series/{series_id}")

    async def get_books_for_series(self, series_id: str) -> list[dict]:
        """Get all books in a series (handles pagination)."""
        books = []
        page = 0
        while True:
            data = await self._get(
                f"/api/v1/series/{series_id}/books",
                params={"page": page, "size": 500, "sort": "metadata.numberSort,asc"},
            )
            books.extend(data.get("content", []))
            if data.get("last", True):
                break
            page += 1
        return books

    async def get_all_series(self) -> list[dict]:
        """Get all series (handles pagination)."""
        all_series = []
        page = 0
        while True:
            data = await self._get(
                "/api/v1/series",
                params={"page": page, "size": 500, "sort": "metadata.titleSort,asc"},
            )
            all_series.extend(data.get("content", []))
            if data.get("last", True):
                break
            page += 1
        logger.info("Fetched %d series from Komga", len(all_series))
        return all_series
