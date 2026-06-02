"""MediaStore — 图片下载与持久化存储。

与 media_bridge.py（临时缓存 + OCR）不同，本模块负责：
  1. 从 media_urls 下载图片到本地永久存储
  2. 计算 media_hash 用于去重
  3. 批量下载 + 并发控制
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
from loguru import logger

from config.settings import settings


class MediaStore:
    """图片下载与持久化存储。

    使用方式:
        store = MediaStore()
        local_paths = store.download_images(media_urls, platform="xiaohongshu", raw_id=123)
        md5_hash = store.compute_media_hash(media_urls)
    """

    def __init__(self, max_workers: int = 4, timeout: int = 15,
                 store_dir: Path | None = None):
        self.max_workers = max_workers
        self.timeout = timeout
        self._store_dir = store_dir or (settings.DATA_DIR / "images")
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        })

    # ═══════════════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════════════

    def download_images(
        self, urls: list[str], *,
        platform: str = "", raw_id: int = 0,
    ) -> list[str]:
        """Download images to local storage. Returns list of local file paths.

        Directory structure: data/images/{platform}/{raw_id}/{md5}.jpg
        """
        if not urls:
            return []

        dest_dir = self._store_dir / platform / str(raw_id)
        dest_dir.mkdir(parents=True, exist_ok=True)

        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._download_one, url, dest_dir): url
                for url in urls
            }
            for f in as_completed(futures):
                url = futures[f]
                try:
                    path = f.result(timeout=self.timeout + 10)
                    if path:
                        results.append(str(path))
                except Exception as exc:
                    logger.debug(f"  Image download failed [{url[:80]}]: {exc}")

        if results:
            logger.debug(
                f"  Downloaded {len(results)}/{len(urls)} images → {dest_dir}"
            )
        return results

    def _download_one(self, url: str, dest_dir: Path) -> str | None:
        """Download a single image, skip if already cached."""
        if not url or not isinstance(url, str):
            return None

        # Compute cache key from URL
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]

        # Check existing files with any extension
        for ext in (".jpg", ".png", ".webp", ".jpeg", ".gif"):
            existing = dest_dir / f"{url_hash}{ext}"
            if existing.exists():
                return str(existing)

        # Download
        try:
            resp = self._session.get(url, timeout=self.timeout, stream=True)
            resp.raise_for_status()

            # Determine extension
            content_type = resp.headers.get("Content-Type", "")
            ext = self._ext_from_content_type(content_type)

            out_path = dest_dir / f"{url_hash}{ext}"
            with open(out_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return str(out_path)
        except Exception as exc:
            logger.debug(f"  Download error [{url[:100]}]: {exc}")
            return None

    @staticmethod
    def _ext_from_content_type(content_type: str) -> str:
        if "png" in content_type:
            return ".png"
        elif "webp" in content_type:
            return ".webp"
        elif "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
        elif "gif" in content_type:
            return ".gif"
        return ".jpg"  # default

    @staticmethod
    def compute_media_hash(urls: list[str]) -> str:
        """Compute content hash from a list of media URLs.

        Used for dedup — identical URL sets produce identical hashes.
        """
        if not urls:
            return ""
        return hashlib.md5(
            "|".join(sorted(str(u) for u in urls if u)).encode()
        ).hexdigest()[:16]

    def get_local_paths(
        self, urls: list[str], *, platform: str = "", raw_id: int = 0,
    ) -> list[str]:
        """Get local file paths for previously downloaded images (no re-download)."""
        if not urls:
            return []
        dest_dir = self._store_dir / platform / str(raw_id)
        if not dest_dir.exists():
            return []
        paths = []
        for url in urls:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
            for ext in (".jpg", ".png", ".webp", ".jpeg", ".gif"):
                p = dest_dir / f"{url_hash}{ext}"
                if p.exists():
                    paths.append(str(p))
                    break
        return paths

    def cleanup_platform(self, platform: str, max_age_days: int = 30) -> int:
        """Remove images older than max_age_days for a platform. Returns count removed."""
        import time as _time
        platform_dir = self._store_dir / platform
        if not platform_dir.exists():
            return 0
        cutoff = _time.time() - max_age_days * 86400
        removed = 0
        for root, _, files in os.walk(platform_dir):
            for f in files:
                fpath = Path(root) / f
                if fpath.stat().st_mtime < cutoff:
                    fpath.unlink()
                    removed += 1
        logger.info(f"Cleaned up {removed} old images for [{platform}]")
        return removed


# Singleton
media_store = MediaStore()
