import contextlib
import glob
import os
import shutil
import subprocess
import tempfile
import wave


def prep_for_gemma(input_path: str) -> list[str]:
    """Returns a list of paths to <=25s mono-16kHz WAV chunks for Gemma E4B."""
    workdir = tempfile.mkdtemp(prefix="hs_audio_")
    norm = os.path.join(workdir, "normalized.wav")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            norm,
        ],
        check=True,
        capture_output=True,
    )

    pattern = os.path.join(workdir, "chunk_%03d.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            norm,
            "-f",
            "segment",
            "-segment_time",
            "25",
            "-c",
            "copy",
            pattern,
        ],
        check=True,
        capture_output=True,
    )

    return sorted(glob.glob(os.path.join(workdir, "chunk_*.wav")))


def mulaw_8k_to_pcm_16k(mulaw_bytes: bytes, out_path: str) -> str:
    """Convert Twilio μ-law 8kHz to PCM 16kHz mono WAV for Gemma.

    Applies loudnorm filter to handle quiet receptionist audio.
    """
    raw = tempfile.NamedTemporaryFile(suffix=".ul", delete=False)
    raw.write(mulaw_bytes)
    raw.close()
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "mulaw",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-i",
                raw.name,
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                out_path,
            ],
            check=True,
            capture_output=True,
        )
    finally:
        os.unlink(raw.name)
    return out_path


def validate_wav(path: str) -> dict:
    """Sanity check before sending to Gemma. Catches 90% of audio bugs."""
    with contextlib.closing(wave.open(path, "rb")) as w:
        info = {
            "channels": w.getnchannels(),
            "rate": w.getframerate(),
            "width_bytes": w.getsampwidth(),
            "duration_s": w.getnframes() / w.getframerate(),
        }
    ok = (
        info["channels"] == 1
        and info["rate"] == 16000
        and info["width_bytes"] == 2
        and info["duration_s"] <= 30
    )
    info["ok"] = ok
    return info


def cleanup(paths: list[str]):
    if not paths:
        return
    shutil.rmtree(os.path.dirname(paths[0]), ignore_errors=True)
