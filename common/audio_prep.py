import subprocess
import tempfile
import os
import glob
import shutil


def prep_for_gemma(input_path: str) -> list[str]:
    """Returns a list of paths to <=25s mono-16kHz WAV chunks for Gemma E4B."""
    workdir = tempfile.mkdtemp(prefix="hs_audio_")
    norm = os.path.join(workdir, "normalized.wav")

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
            norm,
        ],
        check=True,
        capture_output=True,
    )

    pattern = os.path.join(workdir, "chunk_%03d.wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", norm,
            "-f", "segment", "-segment_time", "25",
            "-c", "copy", pattern,
        ],
        check=True,
        capture_output=True,
    )

    return sorted(glob.glob(os.path.join(workdir, "chunk_*.wav")))


def cleanup(paths: list[str]):
    if not paths:
        return
    shutil.rmtree(os.path.dirname(paths[0]), ignore_errors=True)
