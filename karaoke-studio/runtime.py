"""Use the installed decoder or the binary bundled by imageio-ffmpeg."""

import os

BACKEND_VERSION = 20
import shutil
from pathlib import Path


def ffmpeg_path():
    existing = shutil.which("ffmpeg")
    if existing:
        return existing
    import imageio_ffmpeg

    directory = Path(__file__).resolve().parent / ".runtime"
    directory.mkdir(exist_ok=True)
    target = directory / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not target.exists():
        shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), target)
    return str(target)


def configure_decoder():
    decoder = ffmpeg_path()
    os.environ["PATH"] = str(Path(decoder).parent) + os.pathsep + os.environ.get("PATH", "")
    return decoder
