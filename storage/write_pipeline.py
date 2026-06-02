"""Concurrent write pipeline for multi-collector data ingestion.

Producer-consumer model: collector threads enqueue items, a single writer
thread batch-inserts them into MySQL with automatic retry and backpressure.
"""

import queue
import threading
import time
import json as _json
from loguru import logger
from storage.mysql_store import mysql

INSERT_SQL = """INSERT INTO ods_raw_intel
    (source_platform, source_channel, source_url, source_keyword,
     author_id, author_name, publish_time, collect_time,
     content_type, content_raw, media_urls, media_hash,
     crawl_batch_id, raw_status, metadata)
    VALUES (%(source_platform)s, %(source_channel)s, %(source_url)s, %(source_keyword)s,
            %(author_id)s, %(author_name)s, %(publish_time)s, %(collect_time)s,
            %(content_type)s, %(content_raw)s, %(media_urls)s, %(media_hash)s,
            %(crawl_batch_id)s, %(raw_status)s, %(metadata)s)"""


class ConcurrentWritePipeline:
    """Producer-consumer write pipeline for multi-threaded collectors.

    Collector threads call ``enqueue()`` (thread-safe). A single background
    writer thread drains the queue and batch-inserts into MySQL.  When the
    queue is full, ``enqueue()`` blocks — this provides natural backpressure.

    Usage::

        pipeline = ConcurrentWritePipeline(batch_size=200)
        pipeline.start()
        # ... collector threads call pipeline.enqueue(item_dict) ...
        stats = pipeline.finish()
    """

    def __init__(self, batch_size: int = 100, max_retries: int = 3,
                 queue_maxsize: int = 5000):
        """
        Args:
            batch_size: Number of items per ``executemany`` batch.
            max_retries: Retries per batch on failure (exponential backoff).
            queue_maxsize: Maximum queue size (backpressure threshold).
        """
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._writer_thread: threading.Thread | None = None
        self._running = False
        self._stats_lock = threading.Lock()
        self.stats = {"inserted": 0, "errors": 0, "batches": 0, "retries": 0}

    # ── public API ──────────────────────────────────────────────────────────

    def enqueue(self, item: dict) -> None:
        """Enqueue one item for writing.  Blocks when the queue is full (backpressure)."""
        self._queue.put(item)

    def start(self) -> None:
        """Start the background writer thread."""
        self._running = True
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="write-pipeline", daemon=True,
        )
        self._writer_thread.start()
        logger.debug("Write pipeline started (batch_size={})", self._batch_size)

    def finish(self) -> dict:
        """Signal shutdown, drain remaining items, wait for writer thread.

        Returns a copy of the final stats dict.
        """
        self._queue.put(None)  # poison pill
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=60)
        self._running = False
        logger.info(
            "Write pipeline finished: {} inserted, {} errors, "
            "{} batches, {} retries",
            self.stats["inserted"], self.stats["errors"],
            self.stats["batches"], self.stats["retries"],
        )
        return dict(self.stats)

    # ── internals ───────────────────────────────────────────────────────────

    def _writer_loop(self) -> None:
        """Main loop: collect items from queue, flush when batch is full."""
        batch: list[dict] = []
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                # No new items for 0.5 s — flush partial batch to avoid data loss
                if batch:
                    self._flush_batch(batch)
                    batch = []
                continue

            if item is None:  # poison pill
                if batch:
                    self._flush_batch(batch)
                    batch = []
                break

            batch.append(item)
            if len(batch) >= self._batch_size:
                self._flush_batch(batch)
                batch = []

        # Final safety flush (should have been handled above, but belt-and-suspenders)
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: list[dict]) -> None:
        """Attempt to INSERT the batch, retrying on failure."""
        for attempt in range(self._max_retries):
            try:
                with mysql.cursor() as c:
                    c.executemany(INSERT_SQL, batch)
                with self._stats_lock:
                    self.stats["inserted"] += len(batch)
                    self.stats["batches"] += 1
                return
            except Exception as exc:
                if attempt < self._max_retries - 1:
                    delay = 2 ** attempt
                    time.sleep(delay)
                    with self._stats_lock:
                        self.stats["retries"] += 1
                    logger.warning(
                        "Batch insert retry {}/{} after {:.0f}s: {}",
                        attempt + 1, self._max_retries - 1, delay, exc,
                    )
                else:
                    logger.error(
                        "Batch insert FAILED after {} retries: {} items lost — {}",
                        self._max_retries, len(batch), exc,
                    )
                    with self._stats_lock:
                        self.stats["errors"] += len(batch)


# Singleton for convenience
write_pipeline = ConcurrentWritePipeline()
