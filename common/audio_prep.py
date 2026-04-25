import subprocess
import tempfile
import os
import glob
import shutil


def prep_for_gemma(input_path: str) -> list[str]:
    """Returns a list of paths to <=25s mono-16kHz WAV chunks for Gemma E4B."""
    workdir = tempfile.mkdtemp(prefix="kin_audio_")
    norm = os.path.join(workdir, "normalized.wav")

    # 1. Downmix to mono + resample to 16kHz + 16-bit PCM
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
            norm,
        ],
        check=True,
        capture_output=True,
    )

    # 2. Chunk to 25s segments (5s safety margin under Gemma's 30s cap)
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
    """Remove the temp directory created by prep_for_gemma."""
    if not paths:
        return
    shutil.rmtree(os.path.dirname(paths[0]), ignore_errors=True)
