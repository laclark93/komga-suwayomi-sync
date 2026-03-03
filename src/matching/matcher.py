import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import unquote

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


def _extract_folder_name(series_url: str) -> str:
    """
    Extract the last path component from a Komga series URL/path.

    Handles:
      - Unix paths:    /mnt/data/manga/Madan No Ichi
      - Windows paths: C:\\data\\manga\\Madan No Ichi
      - URL-encoded:   /data/manga/Sword%20Art%20Online
    """
    if not series_url:
        return ""
    path = unquote(series_url)
    path = path.replace("\\", "/").rstrip("/")
    return path.split("/")[-1] if "/" in path else path


def _title_similarity(a: str, b: str) -> float:
    """Similarity ratio between two already-normalized titles."""
    return SequenceMatcher(None, a, b).ratio()


class MangaMatcher:
    """
    Matches Komga series to Suwayomi manga by title.

    Matching order:
      Pass 0 - Folder name (from Komga series URL) vs Suwayomi title
               This resolves language mismatches where Komga has fetched an
               English title (e.g. "Ichi the Witch") but the download folder
               still uses the source/romanized name ("Madan No Ichi") that
               Suwayomi also uses.
      Pass 1 - Exact normalized match on metadata title
      Pass 2 - Containment check on metadata title
      Pass 3 - Fuzzy ratio on metadata title above threshold
    """

    def __init__(self, threshold: float = 0.85):
        self._threshold = threshold

    def match_series_to_manga(
        self,
        komga_title: str,
        suwayomi_manga_list: list[dict],
        komga_url: str = "",
    ) -> Optional[dict]:
        """
        Find the best Suwayomi manga match for a Komga series.

        komga_title: the metadata title shown in Komga (may be English)
        komga_url:   the series folder path from Komga (closer to the
                     download-time name Suwayomi uses)
        """
        candidates = [
            (manga, normalize_title(manga["title"]))
            for manga in suwayomi_manga_list
        ]

        # Pass 0: match by folder name extracted from the series path.
        # Because both Komga and Suwayomi reference the same directory,
        # the folder name is the most reliable cross-language identifier.
        folder_name = _extract_folder_name(komga_url)
        folder_norm = normalize_title(folder_name)
        k_norm = normalize_title(komga_title)

        if folder_norm and folder_norm != k_norm:
            result = self._run_passes(folder_norm, candidates)
            if result:
                logger.debug(
                    "Folder-name match: Komga '%s' (folder '%s') -> Suwayomi '%s'",
                    komga_title,
                    folder_name,
                    result["title"],
                )
                return result

        # Passes 1-3: match using the metadata title
        if not k_norm:
            logger.error(
                "UNMATCHED TITLE: Komga series '%s' has no normalizable title",
                komga_title,
            )
            return None

        result = self._run_passes(k_norm, candidates)
        if result:
            return result

        # Nothing worked — log at ERROR so it's visible during debugging
        best_match, best_score = self._best_candidate(k_norm, candidates)
        if best_match:
            logger.error(
                "UNMATCHED TITLE: Komga series '%s' (folder '%s') could not be "
                "matched to any Suwayomi manga. "
                "Best candidate: '%s' (score=%.3f, threshold=%.2f). "
                "If this is a language mismatch, check that the Komga series "
                "folder name matches the Suwayomi manga title.",
                komga_title,
                folder_name or "unknown",
                best_match["title"],
                best_score,
                self._threshold,
            )
        else:
            logger.error(
                "UNMATCHED TITLE: Komga series '%s' could not be matched — "
                "Suwayomi library is empty or all titles failed to normalize.",
                komga_title,
            )
        return None

    def _run_passes(
        self,
        search_norm: str,
        candidates: list[tuple[dict, str]],
    ) -> Optional[dict]:
        """
        Run the three title-matching passes against a normalized search string.
        Returns the first match found, or None.
        """
        # Pass 1: Exact
        for manga, s_norm in candidates:
            if search_norm == s_norm:
                return manga

        # Pass 2: Containment
        for manga, s_norm in candidates:
            if not s_norm:
                continue
            if search_norm in s_norm or s_norm in search_norm:
                shorter = min(len(search_norm), len(s_norm))
                longer = max(len(search_norm), len(s_norm))
                if shorter / longer > 0.6:
                    return manga

        # Pass 3: Fuzzy
        best_match, best_score = self._best_candidate(search_norm, candidates)
        if best_match and best_score >= self._threshold:
            return best_match

        return None

    def _best_candidate(
        self,
        search_norm: str,
        candidates: list[tuple[dict, str]],
    ) -> tuple[Optional[dict], float]:
        """Return the highest-scoring candidate and its score."""
        best_match = None
        best_score = 0.0
        for manga, s_norm in candidates:
            if not s_norm:
                continue
            score = _title_similarity(search_norm, s_norm)
            if score > best_score:
                best_score = score
                best_match = manga
        return best_match, best_score


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
