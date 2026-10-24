"""Processamento de audio do Dictado: gate de silencio e loudnorm.

O gate e uma porta simples baseada em RMS; o loudnorm usa a mesma cadeia
do editor (compressor + EBU R128 dual-pass) via ffmpeg.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

GATE_HOP = 0.025
GATE_MIN_SIL = 0.15
GATE_HYST_DB = 6.0
GATE_MERGE_GAP = 0.12
GATE_SHRINK_A = 0.04
GATE_SHRINK_B = 0.08
GATE_MIN_KEEP = 0.08
GATE_FADE_OUT = 0.030
GATE_FADE_IN = 0.015

STRENGTHS = {
    "suave": ("acompressor=threshold=-16dB:ratio=2:attack=25:release=300:makeup=1", 11),
    "padrao": ("acompressor=threshold=-20dB:ratio=3:attack=20:release=250:makeup=1", 9),
    "forte": ("acompressor=threshold=-20dB:ratio=4:attack=20:release=250:makeup=1", 7),
}

SENS_FACTORS = (2.0, 1.6, 1.25, 1.0, 0.8, 0.63, 0.5)
EDITOR_FFMPEG = Path(r"E:\APP\EDITOR\tools\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _mono(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    return np.ascontiguousarray(arr.reshape(-1))


@lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    """Retorna o primeiro ffmpeg disponivel, ou None."""
    env = os.environ.get("DICTADO_FFMPEG")
    if env and Path(env).is_file():
        return str(Path(env))
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(Path(exe))
    except Exception:
        pass
    if EDITOR_FFMPEG.is_file():
        return str(EDITOR_FFMPEG)
    found = shutil.which("ffmpeg")
    return found or None


def _db(rms: float) -> float:
    if rms < 1e-6:
        return -120.0
    return float(20.0 * math.log10(max(rms, 1e-12)))


def gate_intervals(
    audio: np.ndarray,
    sr: int,
    sensitivity_db: float = 0.0,
) -> list[tuple[float, float]]:
    """Retorna intervalos (inicio, fim) de silencio que devem ser zerados."""
    x = _mono(audio)
    if sr <= 0 or x.size == 0:
        return []

    hop = max(1, int(sr * GATE_HOP))
    n_frames = x.size // hop
    if n_frames <= 0:
        return []

    frames = x[: n_frames * hop].reshape(n_frames, hop)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    db = np.array([_db(float(v)) for v in rms], dtype=np.float64)

    skip = max(0, int(0.4 / GATE_HOP))
    base = db[skip:] if db[skip:].size else db
    floor = float(np.percentile(base, 10.0)) if base.size else -120.0
    if floor > -50.0:
        margin = 12.0
    elif floor < -62.0:
        margin = 8.0
    else:
        margin = 10.0

    threshold = _clamp(floor + margin + float(sensitivity_db), -55.0, -20.0)
    release_at = min(threshold + GATE_HYST_DB, -16.0)

    raw: list[tuple[float, float]] = []
    in_silence = False
    start = 0
    for i, value in enumerate(db):
        if not in_silence and value < threshold:
            in_silence = True
            start = i
        elif in_silence and value > release_at:
            raw.append((start * GATE_HOP, i * GATE_HOP))
            in_silence = False
    if in_silence:
        raw.append((start * GATE_HOP, n_frames * GATE_HOP))

    raw = [(a, b) for a, b in raw if b - a >= GATE_MIN_SIL - 1e-9]
    if not raw:
        return []

    merged: list[list[float]] = []
    for a, b in raw:
        if merged and a - merged[-1][1] < GATE_MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    duration = x.size / float(sr)
    result: list[tuple[float, float]] = []
    for a, b in merged:
        a2 = min(duration, max(0.0, a + GATE_SHRINK_A))
        b2 = min(duration, max(0.0, b - GATE_SHRINK_B))
        if b2 - a2 >= GATE_MIN_KEEP:
            result.append((a2, b2))
    return result


def gate_audio(
    audio: np.ndarray,
    sr: int,
    sensitivity_db: float = 0.0,
    logger: Callable[[str], None] | None = None,
) -> np.ndarray:
    """Aplica o gate com fades lineares, preservando o comprimento."""
    x = _mono(audio)
    intervals = gate_intervals(x, sr, sensitivity_db)
    if not intervals:
        return x.copy()

    duration = x.size / float(sr) if sr > 0 else 0.0
    covered = sum(
        max(0.0, min(duration, end) - max(0.0, start))
        for start, end in intervals
    )
    if duration > 0 and covered >= duration * 0.6:
        if logger:
            logger("gate: take continuo; mantendo o audio sem cortes")
        return x.copy()

    n = x.size
    envelope = np.ones(n, dtype=np.float32)
    fade_out = max(1, int(sr * GATE_FADE_OUT))
    fade_in = max(1, int(sr * GATE_FADE_IN))
    for start_s, end_s in intervals:
        start = min(n, max(0, int(start_s * sr)))
        end = min(n, max(start, int(end_s * sr)))
        out_start = max(0, start - fade_out)
        if start > out_start:
            envelope[out_start:start] = np.linspace(1.0, 0.0, start - out_start, dtype=np.float32)
        envelope[start:end] = 0.0
        in_end = min(n, end + fade_in)
        if in_end > end:
            envelope[end:in_end] = np.linspace(0.0, 1.0, in_end - end, dtype=np.float32)
    return (x * envelope).astype(np.float32)


def loudnorm_filter(strength: str, target_lufs: float = -23.0, lra: int = 11) -> str:
    comp, _ = STRENGTHS.get(strength, STRENGTHS["suave"])
    return f"{comp},loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA={lra}"


def _parse_loudnorm_json(stderr: str) -> dict | None:
    end = stderr.rfind("}")
    start = stderr.rfind("{", 0, end + 1)
    if start < 0 or end <= start:
        return None
    text = stderr[start : end + 1]
    text = text.replace("-inf", "-120.0").replace("inf", "120.0")
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    kwargs = {"capture_output": True, "text": True, "timeout": 120}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if flags:
        kwargs["creationflags"] = flags
    return subprocess.run(args, **kwargs)


def loudnorm_audio(
    audio: np.ndarray,
    sr: int,
    target_lufs: float = -23.0,
    strength: str = "suave",
    ffmpeg: str | None = None,
) -> np.ndarray:
    """Normaliza com compressor + EBU R128 em duas passagens."""
    x = _mono(audio)
    if x.size == 0 or sr <= 0:
        return x

    exe = ffmpeg or find_ffmpeg()
    if not exe:
        raise RuntimeError("ffmpeg nao encontrado")

    _, lra = STRENGTHS.get(strength, STRENGTHS["suave"])
    chain = loudnorm_filter(strength, target_lufs, lra)
    in_path = out_path = None
    try:
        fd, in_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sf.write(in_path, x, sr, subtype="PCM_16")

        measure_cmd = [
            exe, "-hide_banner", "-nostats", "-loglevel", "error",
            "-i", in_path,
            "-af", f"{chain}:print_format=json", "-f", "null", "-",
        ]
        measured = _run_ffmpeg(measure_cmd)
        if measured.returncode != 0:
            return x
        data = _parse_loudnorm_json(measured.stderr or "")
        if not data:
            return x
        fields = ("input_i", "input_tp", "input_lra", "input_thresh")
        try:
            values = [float(data[k]) for k in fields]
        except (KeyError, TypeError, ValueError):
            return x
        if any(not math.isfinite(v) for v in values):
            return x
        mi, mt, ml, mth = values

        apply_cmd = [
            exe, "-hide_banner", "-nostats", "-loglevel", "error",
            "-y", "-i", in_path,
            "-af",
            f"{chain}:measured_I={mi:.6f}:measured_TP={mt:.6f}:"
            f"measured_LRA={ml:.6f}:measured_thresh={mth:.6f}:linear=true",
            "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", out_path,
        ]
        applied = _run_ffmpeg(apply_cmd)
        if applied.returncode != 0:
            return x

        out, _ = sf.read(out_path, dtype="float32", always_2d=False)
        out = _mono(out)
        if out.size == 0 or float(np.max(np.abs(out))) < 1e-6:
            return x
        if out.size > x.size:
            out = out[: x.size]
        elif out.size < x.size:
            out = np.pad(out, (0, x.size - out.size))
        return out.astype(np.float32)
    finally:
        for path in (in_path, out_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def normalize_audio(
    audio: np.ndarray,
    sr: int,
    sensitivity_db: float = 0.0,
    strength: str = "suave",
    logger: Callable[[str], None] | None = None,
) -> np.ndarray:
    """Gate + loudnorm; nunca levanta excecao para o chamador."""
    gated = gate_audio(audio, sr, sensitivity_db, logger=logger)
    try:
        exe = find_ffmpeg()
        if not exe:
            if logger:
                logger("normalizacao: ffmpeg nao encontrado; usando apenas o gate")
            return gated
        return loudnorm_audio(gated, sr, strength=strength, ffmpeg=exe)
    except Exception as exc:
        if logger:
            logger(f"normalizacao falhou ({exc}); usando apenas o gate")
        return gated


def sensitivity_factor(level: int) -> float:
    n = int(_clamp(level, 1, 7))
    return SENS_FACTORS[n - 1]


def effective_thresholds(silence: float, voice: float, level: int) -> tuple[float, float]:
    factor = sensitivity_factor(level)
    s = _clamp(float(silence) * factor, 0.0002, 0.5)
    v = _clamp(float(voice) * factor, 0.0004, 0.5)
    if v < s * 1.5:
        v = min(0.5, s * 1.5)
    return s, v


def gate_sensitivity_db(level: int) -> float:
    return (4.0 - float(_clamp(level, 1, 7))) * 2.0


def next_sensitivity_level(level: int, delta: int) -> int:
    current = int(_clamp(level, 1, 7))
    if delta == 0:
        return current
    step = 1 if delta > 0 else -1
    return int(_clamp(current + step, 1, 7))



