"""Multimodal media processor — extract text from images, video frames, and audio.

Converts non-text media into normalized text before feeding into CleaningPipeline.
Supports:
  - Image OCR via PaddleOCR (Chinese + English)
  - Video frame extraction + OCR
  - Audio/video speech-to-text via faster-whisper

Usage:
    from cleaner.media_processor import MediaProcessor

    proc = MediaProcessor()
    text = proc.process_image("/path/to/screenshot.jpg")
    text = proc.process_video("/path/to/clip.mp4", mode="ocr")
    text = proc.process_audio("/path/to/voice.ogg")
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MediaProcessor:
    """Process image/video/audio media into normalized text."""

    def __init__(self, ocr_lang: str = "ch", device: str = "cpu"):
        self._ocr_lang = ocr_lang
        self._device = device
        self._ocr = None        # Lazy-loaded PaddleOCR instance
        self._whisper = None    # Lazy-loaded WhisperModel instance

    # ── Public API ────────────────────────────────────────────────────────

    def process_image(self, path: str | Path) -> str:
        """Extract text from an image file via OCR."""
        ocr = self._get_ocr()
        if ocr is None:
            logger.warning("PaddleOCR not available — returning empty text")
            return ""
        try:
            result = ocr.ocr(str(path), cls=True)
            if not result or not result[0]:
                return ""
            lines = [line[1][0] for line in result[0] if line[1][1] > 0.5]
            return "\n".join(lines)
        except Exception as exc:
            logger.error(f"OCR failed for {path}: {exc}")
            return ""

    def process_video(self, path: str | Path, mode: str = "ocr",
                      frame_interval: float = 2.0) -> str:
        """Extract text from video — OCR on sampled frames or ASR on audio track.

        Args:
            path: Video file path.
            mode: 'ocr' (sample frames + OCR) or 'asr' (extract audio + transcribe).
            frame_interval: Seconds between sampled frames (OCR mode only).
        """
        if mode == "asr":
            audio_path = self._extract_audio(path)
            if audio_path:
                return self.process_audio(audio_path)
            return ""

        # OCR mode: extract frames and run OCR
        try:
            import cv2
        except ImportError:
            logger.warning("opencv-python not available for video processing")
            return ""

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            logger.error(f"Cannot open video: {path}")
            return ""

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_step = max(1, int(fps * frame_interval))
        all_text: list[str] = []
        frame_idx = 0

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % frame_step == 0:
                    # Write frame to temp file for OCR
                    with tempfile.NamedTemporaryFile(
                        suffix=".jpg", delete=False
                    ) as tmp:
                        cv2.imwrite(tmp.name, frame)
                        text = self.process_image(tmp.name)
                        if text.strip():
                            all_text.append(text)
                        os.unlink(tmp.name)
                frame_idx += 1
        finally:
            cap.release()

        return "\n".join(all_text)

    def process_audio(self, path: str | Path) -> str:
        """Transcribe audio to text via faster-whisper."""
        model = self._get_whisper()
        if model is None:
            logger.warning("faster-whisper not available — returning empty text")
            return ""
        try:
            segments, _info = model.transcribe(str(path), language="zh")
            return " ".join(seg.text.strip() for seg in segments)
        except Exception as exc:
            logger.error(f"ASR failed for {path}: {exc}")
            return ""

    # ── Lazy loaders ──────────────────────────────────────────────────────

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
                self._ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang=self._ocr_lang,
                    use_gpu=self._device != "cpu",
                )
            except ImportError:
                logger.warning("PaddleOCR not installed. pip install paddleocr")
            except Exception as exc:
                logger.warning(f"PaddleOCR init failed: {exc}")
        return self._ocr

    def _get_whisper(self):
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
                self._whisper = WhisperModel(
                    "base", device=self._device, compute_type="int8"
                )
            except ImportError:
                logger.warning(
                    "faster-whisper not installed. "
                    "pip install faster-whisper"
                )
            except Exception as exc:
                logger.warning(f"WhisperModel init failed: {exc}")
        return self._whisper

    @staticmethod
    def _extract_audio(video_path: str | Path) -> Optional[str]:
        """Extract audio track from video to a temp WAV file."""
        try:
            import subprocess
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000",
                    "-ac", "1", tmp.name,
                ],
                capture_output=True,
                check=True,
                timeout=120,
            )
            return tmp.name
        except FileNotFoundError:
            logger.warning("ffmpeg not found — cannot extract audio from video")
        except Exception as exc:
            logger.error(f"Audio extraction failed: {exc}")
        return None


# Singleton
media_processor = MediaProcessor()
