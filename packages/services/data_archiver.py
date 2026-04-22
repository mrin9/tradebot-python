import os
import queue
import threading
import time
from datetime import datetime
from typing import Any

import polars as pl

from packages.utils.log_utils import setup_logger

logger = setup_logger(__name__)


class DataArchiverService:
    """
    Background service that accepts normalized tick data and writes it
    to partitioned Parquet chunks asynchronously.
    """

    def __init__(self, flush_interval_seconds: int = 180):
        self.tick_queue = queue.Queue()
        self.flush_interval_seconds = flush_interval_seconds
        self.is_running = True

        # Start daemon thread immediately
        self._thread = threading.Thread(target=self._archiver_loop, daemon=True)
        self._thread.start()
        logger.info(f"💾 Data Archiver started. Flush interval: {flush_interval_seconds}s")

    def enqueue(self, tick_data: dict[str, Any]) -> None:
        """
        Pushes a tick dictionary to the background queue.
        This is an O(1) non-blocking operation.
        """
        self.tick_queue.put(tick_data)

    def _archiver_loop(self) -> None:
        buffer = []
        last_flush_time = time.time()

        while self.is_running:
            try:
                # Timeout allows thread to wake up and check flush interval even if idle
                item = self.tick_queue.get(timeout=1.0)
                buffer.append(item)
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"Error in data archiver queue loop: {e}", exc_info=True)

            current_time = time.time()
            if current_time - last_flush_time >= self.flush_interval_seconds:
                if buffer:
                    # Flush a copy of the buffer and clear it instantly
                    data_to_flush = buffer.copy()
                    buffer.clear()
                    self._flush_to_parquet(data_to_flush)
                last_flush_time = current_time

    def _flush_to_parquet(self, data: list[dict[str, Any]]) -> None:
        """Converts buffer to Polars DF and writes out chunk."""
        try:
            df = pl.DataFrame(data)

            # E.g., ../data/ticks/date=2026-04-22/
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            # Resolve the path to the parent of tradebot-python
            # __file__ is packages/services/data_archiver.py
            current_dir = os.path.dirname(os.path.abspath(__file__))
            tradebot_python_dir = os.path.dirname(os.path.dirname(current_dir))
            parent_dir = os.path.dirname(tradebot_python_dir)
            
            base_dir = os.path.join(parent_dir, "data", "ticks", f"date={today_str}")
            os.makedirs(base_dir, exist_ok=True)

            # E.g., ticks_1442.parquet (HHMM)
            time_str = datetime.now().strftime("%H%M")
            file_path = os.path.join(base_dir, f"ticks_{time_str}.parquet")

            df.write_parquet(file_path)
            logger.debug(f"💾 Flushed {len(data)} ticks to {file_path}")
        except Exception as e:
            logger.error(f"💥 Failed to write parquet chunk: {e}", exc_info=True)

    def stop(self) -> None:
        """Gracefully stops the archiver."""
        self.is_running = False
