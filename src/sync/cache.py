import time
from typing import Optional


class MappingCache:
    """
    In-memory cache mapping:
      - komga_series_id -> suwayomi_manga_id
      - (komga_series_id, book_number) -> suwayomi_chapter_id
      - Full Suwayomi library snapshot

    Entries expire after TTL seconds.
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._ttl = ttl_seconds
        # series_id -> (suwayomi_manga_id, timestamp)
        self._series_map: dict[str, tuple[int, float]] = {}
        # (series_id, book_number_str) -> (suwayomi_chapter_id, timestamp)
        self._chapter_map: dict[tuple[str, str], tuple[int, float]] = {}
        # Cached Suwayomi library
        self._suwayomi_library: Optional[list[dict]] = None
        self._library_timestamp: float = 0

    def _is_valid(self, timestamp: float) -> bool:
        return (time.monotonic() - timestamp) < self._ttl

    def get_manga_id(self, komga_series_id: str) -> Optional[int]:
        entry = self._series_map.get(komga_series_id)
        if entry and self._is_valid(entry[1]):
            return entry[0]
        return None

    def set_manga_id(self, komga_series_id: str, suwayomi_manga_id: int):
        self._series_map[komga_series_id] = (suwayomi_manga_id, time.monotonic())

    def get_chapter_id(
        self, komga_series_id: str, book_number: str
    ) -> Optional[int]:
        key = (komga_series_id, book_number)
        entry = self._chapter_map.get(key)
        if entry and self._is_valid(entry[1]):
            return entry[0]
        return None

    def set_chapter_id(
        self, komga_series_id: str, book_number: str, suwayomi_chapter_id: int
    ):
        key = (komga_series_id, book_number)
        self._chapter_map[key] = (suwayomi_chapter_id, time.monotonic())

    def get_suwayomi_library(self) -> Optional[list[dict]]:
        if self._suwayomi_library is not None and self._is_valid(
            self._library_timestamp
        ):
            return self._suwayomi_library
        return None

    def set_suwayomi_library(self, library: list[dict]):
        self._suwayomi_library = library
        self._library_timestamp = time.monotonic()

    def invalidate(self):
        self._series_map.clear()
        self._chapter_map.clear()
        self._suwayomi_library = None
