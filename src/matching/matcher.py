import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """
    Aggressively normalize a title for comparison.

    Steps:
      1. Unicode NFKC normalization (half-width/full-width, ligatures)
      2. Lowercase
      3. Remove bracketed annotations: [Digital], (2023), etc.
      4. Replace separators (underscores, hyphens, dots) with spaces
      5. Remove non-alphanumeric except spaces
      6. Collapse multiple spaces and strip
    """
    s = unicodedata.normalize("NFKC", title)
    s = s.lower()
    s = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", s)
    s = re.sub(r"[_\-\.]+", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _title_similarity(a: str, b: str) -> float:
    """Similarity ratio between two already-normalized titles."""
    return SequenceMatcher(None, a, b).ratio()


class MangaMatcher:
    """
    Matches Komga series to Suwayomi manga by title.

    Uses a 3-pass approach:
      1. Exact normalized match
      2. Containment check (one title contains the other)
      3. Fuzzy ratio above threshold
    """

    def __init__(self, threshold: float = 0.85):
        self._threshold = threshold

    def match_series_to_manga(
        self,
        komga_title: str,
        suwayomi_manga_list: list[dict],
    ) -> Optional[dict]:
        """
        Find the best Suwayomi manga match for a Komga series title.
        Returns the matched manga dict or None.
        """
        k_norm = normalize_title(komga_title)
        if not k_norm:
            return None

        candidates = []
        for manga in suwayomi_manga_list:
            s_norm = normalize_title(manga["title"])
            candidates.append((manga, s_norm))

        # Pass 1: Exact normalized match
        for manga, s_norm in candidates:
            if k_norm == s_norm:
                logger.debug(
                    "Exact match: '%s' == '%s'", komga_title, manga["title"]
                )
                return manga

        # Pass 2: Containment (one is a substring of the other)
        for manga, s_norm in candidates:
            if not s_norm:
                continue
            if k_norm in s_norm or s_norm in k_norm:
                shorter = min(len(k_norm), len(s_norm))
                longer = max(len(k_norm), len(s_norm))
                ratio = shorter / longer
                if ratio > 0.6:
                    logger.debug(
                        "Containment match: '%s' <-> '%s' (ratio=%.2f)",
                        komga_title,
                        manga["title"],
                        ratio,
                    )
                    return manga

        # Pass 3: Fuzzy matching
        best_match = None
        best_score = 0.0
        for manga, s_norm in candidates:
            if not s_norm:
                continue
            score = _title_similarity(k_norm, s_norm)
            if score > best_score:
                best_score = score
                best_match = manga

        if best_match and best_score >= self._threshold:
            logger.debug(
                "Fuzzy match: '%s' <-> '%s' (score=%.3f)",
                komga_title,
                best_match["title"],
                best_score,
            )
            return best_match

        # No match found - log at ERROR level for visibility
        if best_match:
            logger.error(
                "UNMATCHED TITLE: Komga series '%s' could not be matched to any "
                "Suwayomi manga. Best candidate: '%s' (score=%.3f, threshold=%.2f)",
                komga_title,
                best_match["title"],
                best_score,
                self._threshold,
            )
        else:
            logger.error(
                "UNMATCHED TITLE: Komga series '%s' could not be matched - "
                "no candidates in Suwayomi library",
                komga_title,
            )
        return None


def match_chapter(
    komga_book_number: Optional[str | float | int],
    suwayomi_chapters: list[dict],
) -> Optional[dict]:
    """
    Match a Komga book (by its number) to a Suwayomi chapter.

    Strategy:
      1. Parse komga_book_number to float
      2. Find Suwayomi chapter with matching chapterNumber (float comparison
         with epsilon for floating point tolerance)
      3. If no numeric match, fall back to name-based matching
    """
    if komga_book_number is None:
        return None

    # Try numeric match first
    k_num: Optional[float] = None
    try:
        k_num = float(komga_book_number)
    except (ValueError, TypeError):
        pass

    if k_num is not None:
        for ch in suwayomi_chapters:
            s_num = ch.get("chapterNumber")
            if s_num is not None:
                try:
                    if abs(float(s_num) - k_num) < 0.001:
                        return ch
                except (ValueError, TypeError):
                    continue

    # Fallback: normalize and compare names
    k_name = normalize_title(str(komga_book_number))
    if k_name:
        for ch in suwayomi_chapters:
            s_name = normalize_title(ch.get("name", ""))
            if s_name and k_name == s_name:
                return ch

    return None
