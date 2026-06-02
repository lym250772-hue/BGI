"""
MediaBridge — 异步图片 OCR 管道，连接 MediaProcessor 到数据管道。

设计决策: 后处理异步模式（不在采集时同步做 OCR）
  - 采集时下载图片会加 3~9s/条，触发反爬
  - 改为: 采集完一批后，单独运行 python main.py ocr 批量处理

处理流程:
  1. 查 ods_raw_intel 中有 image_list/video_cover_url 但无 OCR 的数据
  2. 下载图片 (requests + 重试 + 24h 缓存)
  3. PaddleOCR 提取文字
  4. 写入 dwd_clean_intel.ocr_text 和 merged_text

用法:
    from cleaner.media_bridge import media_bridge

    # 批量处理
    count = media_bridge.process_pending(limit=100, platforms=["douyin", "xiaohongshu"])

    # 单条处理
    media_bridge.process_single(raw_id=123)
"""

from __future__ import annotations

import os
import json
import time
import hashlib
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

import requests

from config.settings import settings


# ═══════════════════════════════════════════════════════════════════════════════
# MediaBridge
# ═══════════════════════════════════════════════════════════════════════════════

class MediaBridge:
    """异步图片下载 + OCR 管道。

    参数:
        cache_dir: 图片缓存目录 (默认 data/raw/images/)
        cache_ttl_hours: 缓存有效期 (默认 24h)
        max_images_per_item: 每条最多下载几张图 (默认 5)
        request_timeout: 图片下载超时秒数 (默认 15)
    """

    def __init__(
        self,
        cache_dir: str | None = None,
        cache_ttl_hours: int = 24,
        max_images_per_item: int = 5,
        request_timeout: int = 15,
    ):
        self.cache_dir = Path(cache_dir or (settings.raw_data_dir / "images"))
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.max_images = max_images_per_item
        self.timeout = request_timeout
        self._ocr = None  # 惰性加载 PaddleOCR
        self._session: requests.Session | None = None

        # 确保缓存目录存在
        os.makedirs(self.cache_dir, exist_ok=True)

    # ── 公共 API ──────────────────────────────────────────────────────────

    def process_pending(self, limit: int = 100,
                        platforms: list[str] | None = None) -> int:
        """批量处理待 OCR 的数据。

        Args:
            limit: 最大处理条数
            platforms: 限定的平台 (默认 ['douyin', 'xiaohongshu'])

        Returns:
            成功处理的数量
        """
        platforms = platforms or ["douyin", "xiaohongshu"]
        items = self._fetch_pending_items(limit, platforms)
        if not items:
            logger.info("没有待 OCR 处理的数据")
            return 0

        processed = 0
        for item in items:
            try:
                if self.process_single(item):
                    processed += 1
            except Exception as exc:
                logger.error(f"OCR 处理失败 raw_id={item.get('id')}: {exc}")

        logger.info(f"OCR 批量处理完成: {processed}/{len(items)}")
        return processed

    def process_single(self, item: dict) -> bool:
        """处理单条数据的 OCR。

        Args:
            item: ods_raw_intel 的行 dict (含 id, content_raw, metadata 等)

        Returns:
            是否成功提取到 OCR 文本
        """
        raw_id = item.get("id")
        metadata = self._parse_metadata(item.get("metadata", {}))

        # 收集图片 URL
        image_urls = self._collect_image_urls(metadata, item.get("source_platform", ""))
        if not image_urls:
            return False

        # 下载 + OCR
        ocr_lines = []
        for url in image_urls[:self.max_images]:
            img_path = self._download_image(url)
            if img_path:
                text = self._ocr_image(img_path)
                if text:
                    ocr_lines.append(text)

        if not ocr_lines:
            return False

        ocr_text = "\n".join(ocr_lines)
        self._save_ocr_result(raw_id, ocr_text, item.get("content_raw", ""))
        logger.info(f"  raw_id={raw_id}: OCR 提取 {len(ocr_lines)} 段文本 ({len(ocr_text)} chars)")
        return True

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _fetch_pending_items(self, limit: int, platforms: list[str]) -> list[dict]:
        """查询待 OCR 的数据。"""
        try:
            from storage.mysql_store import mysql
            with mysql.cursor() as c:
                placeholders = ",".join(["%s"] * len(platforms))
                sql = f"""
                    SELECT o.id, o.content_raw, o.metadata, o.source_platform
                    FROM ods_raw_intel o
                    LEFT JOIN dwd_clean_intel d ON d.raw_id = o.id
                    WHERE o.source_platform IN ({placeholders})
                      AND (d.ocr_text IS NULL OR d.ocr_text = '')
                      AND o.raw_status = 'CLEANED'
                    LIMIT %s
                """
                c.execute(sql, [*platforms, limit])
                return c.fetchall()
        except Exception as exc:
            logger.error(f"查询待 OCR 数据失败: {exc}")
            return []

    @staticmethod
    def _parse_metadata(metadata) -> dict:
        """解析 metadata 字段。"""
        if isinstance(metadata, str):
            try:
                return json.loads(metadata)
            except Exception:
                return {}
        return metadata or {}

    def _collect_image_urls(self, metadata: dict, platform: str) -> list[str]:
        """从 metadata 中收集图片 URL。"""
        urls = []

        # 小红书: image_list
        image_list = metadata.get("image_list", [])
        if isinstance(image_list, list):
            urls.extend(image_list)

        # 抖音: video_cover_url
        cover = metadata.get("video_cover_url", "")
        if cover and isinstance(cover, str) and cover.startswith("http"):
            urls.append(cover)

        # 微博/Tieba 也可能有图片（预留）
        if not urls and platform in ("weibo", "tieba", "zhihu"):
            # 尝试从其他字段提取
            pass

        # 去重
        seen = set()
        unique = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique

    def _download_image(self, url: str) -> Optional[str]:
        """下载图片到缓存，返回本地路径。"""
        # 用 URL 的 MD5 做缓存 key
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.cache_dir / f"{url_hash}.jpg"

        # 缓存命中且未过期
        if cache_path.exists():
            mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
            if datetime.now() - mtime < self.cache_ttl:
                return str(cache_path)

        # 下载
        try:
            if self._session is None:
                self._session = requests.Session()
                self._session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/131.0.0.0 Safari/537.36",
                    "Referer": "https://www.xiaohongshu.com/",
                })

            resp = self._session.get(url, timeout=self.timeout)
            resp.raise_for_status()

            with open(cache_path, "wb") as f:
                f.write(resp.content)

            return str(cache_path)

        except Exception as exc:
            logger.debug(f"  图片下载失败 {url[:80]}: {exc}")
            return None

    def _ocr_image(self, img_path: str) -> str:
        """对单张图片执行 OCR。"""
        ocr = self._get_ocr()
        if ocr is None:
            return ""
        try:
            result = ocr.ocr(img_path, cls=True)
            if not result or not result[0]:
                return ""
            # 过滤低置信度(<0.5)的行
            lines = [line[1][0] for line in result[0] if line[1][1] > 0.5]
            # 过滤过短的行 (<2 chars)
            lines = [l for l in lines if len(l.strip()) >= 2]
            return "\n".join(lines)
        except Exception as exc:
            logger.debug(f"  OCR 失败 {img_path}: {exc}")
            return ""

    def _get_ocr(self):
        """惰性加载 PaddleOCR。"""
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
                self._ocr = PaddleOCR(use_angle_cls=True, lang="ch")
                logger.info("PaddleOCR 已加载")
            except ImportError:
                logger.warning("PaddleOCR 未安装，OCR 功能不可用。安装: pip install paddleocr paddlepaddle")
                self._ocr = False
            except Exception as exc:
                logger.warning(f"PaddleOCR 加载失败: {exc}")
                self._ocr = False
        return self._ocr if self._ocr is not False else None

    def _save_ocr_result(self, raw_id: int, ocr_text: str, content_raw: str):
        """保存 OCR 结果到 dwd_clean_intel。"""
        try:
            from storage.mysql_store import mysql

            # 构建 merged_text: content_raw + OCR
            merged = content_raw
            if ocr_text:
                merged += f"\n[OCR文本]\n{ocr_text}"

            with mysql.cursor() as c:
                c.execute(
                    """UPDATE dwd_clean_intel
                       SET ocr_text = %s, merged_text = %s
                       WHERE raw_id = %s""",
                    (ocr_text, merged, raw_id),
                )
        except Exception as exc:
            logger.error(f"保存 OCR 结果失败 raw_id={raw_id}: {exc}")

    def cleanup_cache(self, older_than_hours: int = 48):
        """清理过期缓存文件。"""
        cutoff = datetime.now() - timedelta(hours=older_than_hours)
        count = 0
        for f in self.cache_dir.iterdir():
            if f.is_file():
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    count += 1
        if count:
            logger.info(f"清理了 {count} 个过期图片缓存")


# ── 单例 ────────────────────────────────────────────────────────────────────

media_bridge = MediaBridge()
