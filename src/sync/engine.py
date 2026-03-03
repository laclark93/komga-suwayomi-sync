import asyncio
import logging
from typing import Optional

from ..config import Settings
from ..komga.client import KomgaClient
from ..matching.matcher import MangaMatcher, match_chapter
from ..suwayomi.client import SuwayomiClient
from .cache import MappingCache

logger = logging.getLogger(__name__)


class SyncEngine:
    """
    Orchestrates read progress sync from Komga to Suwayomi.

    Two modes:
      - initial_sync(): full comparison of all read books at startup
      - handle_read_progress_event(): real-time sync from SSE events
      - polling_loop(): periodic full sync as safety net
    """

    def __init__(
        self,
        komga: KomgaClient,
        suwayomi: SuwayomiClient,
        matcher: MangaMatcher,
        cache: MappingCache,
        settings: Settings,
    ):
        self._komga = komga
        self._suwayomi = suwayomi
        self._matcher = matcher
        self._cache = cache
        self._settings = settings

    async def _get_suwayomi_library(self) -> list[dict]:
        """Get Suwayomi library from cache or fetch fresh."""
        library = self._cache.get_suwayomi_library()
        if library is not None:
            return library
        library = await self._suwayomi.get_all_manga_with_chapters()
        self._cache.set_suwayomi_library(library)
        return library

    def _extract_book_number(self, book: dict) -> Optional[str]:
        """Extract the chapter/book number from a Komga book."""
        number = book.get("metadata", {}).get("number")
        if number:
            return str(number)
        number = book.get("number")
        if number is not None:
            return str(number)
        return None

    def _extract_series_title(self, series: dict) -> str:
        """Extract the display title from a Komga series."""
        return series.get("metadata", {}).get("title") or series.get("name", "")

    async def initial_sync(self):
        """
        Full sync: compare all read books in Komga against Suwayomi
        and mark unread chapters as read.
        """
        logger.info("Starting initial sync...")
        suwayomi_library = await self._suwayomi.get_all_manga_with_chapters()
        self._cache.set_suwayomi_library(suwayomi_library)

        komga_series_list = await self._komga.get_all_series()
        synced_count = 0
        unmatched_series = 0

        for k_series in komga_series_list:
            series_id = k_series["id"]
            series_title = self._extract_series_title(k_series)

            s_manga = self._matcher.match_series_to_manga(
                series_title, suwayomi_library
            )
            if not s_manga:
                unmatched_series += 1
                continue

            self._cache.set_manga_id(series_id, s_manga["id"])

            k_books = await self._komga.get_books_for_series(series_id)

            to_mark: list[int] = []
            for book in k_books:
                read_progress = book.get("readProgress")
                if not read_progress or not read_progress.get("completed"):
                    continue

                book_number = self._extract_book_number(book)
                matched_ch = match_chapter(
                    book_number, s_manga["chapters"]["nodes"]
                )
                if matched_ch and not matched_ch["isRead"]:
                    to_mark.append(matched_ch["id"])
                    if book_number:
                        self._cache.set_chapter_id(
                            series_id, book_number, matched_ch["id"]
                        )

            if to_mark:
                await self._suwayomi.mark_chapters_read(to_mark)
                synced_count += len(to_mark)
                logger.info(
                    "Synced %d chapters for '%s'", len(to_mark), series_title
                )

        logger.info(
            "Initial sync complete: %d chapters synced, %d series unmatched",
            synced_count,
            unmatched_series,
        )

    async def handle_read_progress_event(self, book_id: str, user_id: str):
        """
        Handle a single ReadProgressChanged SSE event.

        Fetches the book, checks if completed, matches to Suwayomi, and syncs.
        """
        book = await self._komga.get_book(book_id)
        read_progress = book.get("readProgress")
        if not read_progress or not read_progress.get("completed"):
            logger.debug("Book %s not yet completed, skipping", book_id)
            return

        series_id = book["seriesId"]
        book_number = self._extract_book_number(book)

        if not book_number:
            logger.warning("Book %s has no number metadata, cannot match", book_id)
            return

        # Check cache first
        cached_chapter_id = self._cache.get_chapter_id(series_id, book_number)
        if cached_chapter_id:
            await self._suwayomi.mark_chapter_read(cached_chapter_id)
            logger.info(
                "Synced book %s (cached) -> Suwayomi chapter %d",
                book_id,
                cached_chapter_id,
            )
            return

        # Cache miss - resolve the mapping
        suwayomi_library = await self._get_suwayomi_library()
        s_manga_id = self._cache.get_manga_id(series_id)

        if s_manga_id is None:
            k_series = await self._komga.get_series(series_id)
            series_title = self._extract_series_title(k_series)

            s_manga = self._matcher.match_series_to_manga(
                series_title, suwayomi_library
            )
            if not s_manga:
                return
            self._cache.set_manga_id(series_id, s_manga["id"])
            s_manga_id = s_manga["id"]

        # Find the manga in library
        s_manga = next(
            (m for m in suwayomi_library if m["id"] == s_manga_id), None
        )
        if not s_manga:
            logger.warning(
                "Suwayomi manga ID %d no longer in library, invalidating cache",
                s_manga_id,
            )
            self._cache.invalidate()
            return

        matched_ch = match_chapter(book_number, s_manga["chapters"]["nodes"])
        if matched_ch:
            self._cache.set_chapter_id(series_id, book_number, matched_ch["id"])
            if not matched_ch["isRead"]:
                await self._suwayomi.mark_chapter_read(matched_ch["id"])
                logger.info(
                    "Synced book %s -> Suwayomi chapter %d ('%s' ch.%s)",
                    book_id,
                    matched_ch["id"],
                    s_manga["title"],
                    book_number,
                )
            else:
                logger.debug(
                    "Chapter already read in Suwayomi: %s ch.%s",
                    s_manga["title"],
                    book_number,
                )
        else:
            logger.warning(
                "No matching Suwayomi chapter for book number '%s' in manga '%s'",
                book_number,
                s_manga["title"],
            )

    async def polling_loop(self):
        """
        Fallback polling that periodically re-runs a full sync.
        Catches events missed during SSE disconnections.
        """
        while True:
            await asyncio.sleep(self._settings.polling_interval_seconds)
            try:
                logger.info("Running polling sync...")
                await self.initial_sync()
            except Exception:
                logger.exception("Polling sync failed")
