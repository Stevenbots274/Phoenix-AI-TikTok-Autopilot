"""Media boundary for FFmpeg, TTS, subtitles, and vertical output validation."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path


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
            "status": "healthy" if self.available else "not_configured",
            "engine": "ffmpeg",
            "path": self.ffmpeg,
            "message": "Ready for rendering" if self.available else "Install FFmpeg to render videos",
        }

    @staticmethod
    def validate_spec(spec: RenderSpec) -> None:
        if (spec.width, spec.height) != (1080, 1920):
            raise ValueError("TikTok output must be 1080x1920 (9:16).")
        if spec.container != "mp4" or spec.video_codec != "libx264" or spec.audio_codec != "aac":
            raise ValueError("Output must be MP4/H.264 with AAC audio.")

    @staticmethod
    def _wrapped(value: str, width: int) -> str:
        lines = []
        for paragraph in str(value or "").splitlines() or [""]:
            lines.extend(textwrap.wrap(paragraph, width=width) or [""])
        return "\n".join(lines)

    @staticmethod
    def _filter_path(path: Path) -> str:
        return str(path).replace("\\", "\\\\").replace(":", "\\:")

    def render(
        self,
        *,
        topic: str,
        hook: str,
        script: str,
        duration_seconds: int,
        output_path: Path,
    ) -> dict:
        if not self.available:
            raise RuntimeError("FFmpeg is not installed. Install it before rendering videos.")
        spec = RenderSpec()
        self.validate_spec(spec)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="phoenix-render-") as directory:
            temp = Path(directory)
            title_file = temp / "title.txt"
            hook_file = temp / "hook.txt"
            script_file = temp / "script.txt"
            title_file.write_text(self._wrapped(topic, 28), encoding="utf-8")
            hook_file.write_text(self._wrapped(hook, 34), encoding="utf-8")
            script_file.write_text(self._wrapped(script, 38)[:900], encoding="utf-8")
            title_path = self._filter_path(title_file)
            hook_path = self._filter_path(hook_file)
            script_path = self._filter_path(script_file)
            draw = (
                f"drawtext=textfile={title_path}:fontcolor=white:fontsize=62:"
                "x=(w-text_w)/2:y=190:line_spacing=14:box=1:boxcolor=0x252a36cc:boxborderw=26,"
                f"drawtext=textfile={hook_path}:fontcolor=0xffb59fff:fontsize=38:"
                "x=90:y=590:line_spacing=12:box=1:boxcolor=0x10131acc:boxborderw=22,"
                f"drawtext=textfile={script_path}:fontcolor=0xf4f5f7:fontsize=32:"
                "x=90:y=1030:line_spacing=10:box=1:boxcolor=0x10131acc:boxborderw=22"
            )
            command = [
                self.ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x191d27:s={spec.width}x{spec.height}:r=30:d={int(duration_seconds)}",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-vf",
                draw,
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                spec.video_codec,
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                spec.audio_codec,
                "-b:a",
                "128k",
                "-t",
                str(int(duration_seconds)),
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if completed.returncode:
                raise RuntimeError(f"FFmpeg could not render this video: {completed.stderr[-600:]}")
        return {
            "path": str(output_path),
            "duration": int(duration_seconds),
            "resolution": f"{spec.width}x{spec.height}",
            "file_size": output_path.stat().st_size,
        }
