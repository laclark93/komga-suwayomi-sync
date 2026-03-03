import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_HEADER = (
    "# Unmatched titles — Komga series that could not be matched to a Suwayomi manga.\n"
    "# Each title appears only once (deduplicated across restarts).\n"
    "# Fields: Komga title | Folder name | Best Suwayomi candidate | Score\n"
    "#\n"
)


class UnmatchedTitlesLog:
    """
    Persistent, deduplicated log of Komga series titles that could not be
    matched to any Suwayomi manga.

    Written to {log_dir}/unmatched.txt. Existing entries are read on startup
    so that repeated sync runs do not produce duplicate lines.
    """

    def __init__(self, log_dir: Path) -> None:
        self._path = log_dir / "unmatched.txt"
        self._seen: set[str] = self._load_existing()

        if not self._path.exists():
            self._path.write_text(_HEADER, encoding="utf-8")

    def _load_existing(self) -> set[str]:
        """Read the file and collect all Komga titles already recorded."""
        seen: set[str] = set()
        if not self._path.exists():
            return seen
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Format: [timestamp] Komga: "title" | ...
                if 'Komga: "' in line:
                    start = line.index('Komga: "') + len('Komga: "')
                    end = line.index('"', start)
                    seen.add(line[start:end])
        except Exception:
            logger.warning("Could not read existing unmatched.txt — starting fresh")
        return seen

    def record(
        self,
        komga_title: str,
        folder_name: str,
        best_candidate: Optional[str],
        best_score: float,
    ) -> None:
        """
        Record an unmatched title. No-op if this Komga title has been seen before.
        """
        if komga_title in self._seen:
            return

        self._seen.add(komga_title)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if best_candidate:
            line = (
                f'[{ts}] Komga: "{komga_title}" | '
                f'Folder: "{folder_name or "unknown"}" | '
                f'Best match: "{best_candidate}" (score: {best_score:.3f})\n'
            )
        else:
            line = (
                f'[{ts}] Komga: "{komga_title}" | '
                f'Folder: "{folder_name or "unknown"}" | '
                f"Best match: none\n"
            )

        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
            logger.debug("Recorded unmatched title to %s", self._path)
        except OSError:
            logger.exception("Failed to write to unmatched.txt")
