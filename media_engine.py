"""Media boundary for FFmpeg, TTS, subtitles, and vertical output validation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class RenderSpec:
    width: int = 1080
    height: int = 1920
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    container: str = "mp4"


class MediaEngine:
    def __init__(self):
        self.ffmpeg = shutil.which("ffmpeg")

    @property
    def available(self) -> bool:
        return self.ffmpeg is not None

    def health(self) -> dict:
        return {
            "status": "not_configured",
            "engine": "ffmpeg",
            "path": self.ffmpeg,
            "message": "Video rendering worker is not implemented yet" if self.available else "Install FFmpeg to render videos",
        }

    @staticmethod
    def validate_spec(spec: RenderSpec) -> None:
        if (spec.width, spec.height) != (1080, 1920):
            raise ValueError("TikTok output must be 1080x1920 (9:16).")
        if spec.container != "mp4" or spec.video_codec != "libx264" or spec.audio_codec != "aac":
            raise ValueError("Output must be MP4/H.264 with AAC audio.")

    def render(self, *args, **kwargs):
        """Reserved for the worker; fail clearly instead of creating a fake video."""
        if not self.available:
            raise RuntimeError("FFmpeg is not installed. Install it before rendering videos.")
        raise NotImplementedError("The render worker is the next media milestone.")
