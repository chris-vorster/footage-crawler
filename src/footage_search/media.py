from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts"}

register_heif_opener()


def discover(folder: Path, include_photos: bool = True, include_videos: bool = True):
    media = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if include_photos and suffix in PHOTO_EXTENSIONS:
            media.append((path.resolve(), "photo"))
        elif include_videos and suffix in VIDEO_EXTENSIONS:
            media.append((path.resolve(), "video"))
    return sorted(media, key=lambda item: str(item[0]).lower())


def require_ffmpeg() -> None:
    for command in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run([command, "-version"], check=True, capture_output=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"{command} is required and was not found on PATH") from error


def video_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def photo_thumbnail(source: Path, target: Path, size=(640, 400)) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail(size)
        canvas = Image.new("RGB", size, "#17231e")
        offset = ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
        canvas.paste(image, offset)
        canvas.save(target, "JPEG", quality=86)
    return target


def video_frame(source: Path, timestamp: float, target: Path, size=(640, 400)) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{timestamp:.3f}", "-i", str(source), "-frames:v", "1",
            "-vf", f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease,"
            f"pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2:color=0x17231e",
            "-q:v", "3", str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


def sample_timestamps(duration: float, profile: str) -> list[float]:
    interval = {"fast": 20.0, "balanced": 10.0, "accurate": 5.0}[profile]
    if duration <= 2:
        return [max(0.0, duration / 2)]
    timestamps = []
    current = min(1.0, duration / 2)
    while current < duration:
        timestamps.append(current)
        current += interval
    return timestamps or [duration / 2]
