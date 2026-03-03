import logging
import logging.handlers
import os
from pathlib import Path

from .config import Settings


def setup_logging(settings: Settings) -> None:
    """
    Configure application logging.

    Outputs to:
      - stdout (all levels at or above log_level)
      - {log_dir}/sync.log (all INFO+ messages, rotating at 10 MB, 5 backups)
    """
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    # --- stdout handler ---
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    # --- rotating sync.log handler ---
    sync_log_path = log_dir / "sync.log"
    file_handler = logging.handlers.RotatingFileHandler(
        sync_log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("komga-suwayomi-sync").info(
        "Logging to %s (max 10 MB × 5 backups)", sync_log_path
    )
