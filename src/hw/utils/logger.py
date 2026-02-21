from os.path import expanduser
from pathlib import Path

from loguru import logger


def _get_log_file_path() -> Path:
    home = expanduser("~")
    log_dir = Path(home) / ".hw" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "hw.log"
    return log_file


def setup_logger():
    log_file_path = _get_log_file_path()
    logger.remove()
    logger.add(log_file_path, rotation="10 MB", retention="7 days", compression="zip")
