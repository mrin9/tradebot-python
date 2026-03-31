import logging
import sys
from datetime import datetime
from pathlib import Path

import pytz

# Create logs directory if it doesn't exist
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


class UppercaseFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # Force IST for logs
        ist = pytz.timezone("Asia/Kolkata")
        dt = datetime.fromtimestamp(record.created, tz=ist)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime("%Y-%m-%d %H:%M:%S,%03d")
        return s.upper()


def setup_logger(name: str, log_file: str = "app.log", level=logging.INFO):
    """
    Sets up a logger with the specified name and log file.
    """
    formatter = UppercaseFormatter(
        "%(asctime)s %(levelname)-8s %(filename)-15s:%(lineno)-4d  %(message)s", datefmt="%b-%d %H:%M"
    )

    handler = logging.FileHandler(LOG_DIR / log_file)
    handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding handlers multiple times
    if not logger.handlers:
        logger.addHandler(handler)

        # Only add console output if NOT in testing environment
        import os

        if not os.environ.get("TESTING_ENV"):
            logger.addHandler(console_handler)

    return logger
