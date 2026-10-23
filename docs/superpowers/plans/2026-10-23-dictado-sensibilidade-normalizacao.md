# Dictado Sensitivity, Audio Normalization, and Transcription Visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a session-only sensitivity slider, faithful gate + EBU R128 normalization, test WAV capture, and a circular processing visual to Dictado.

**Architecture:** A new `audio_fx.py` owns the pure-numpy gate and the ffmpeg loudnorm chain. `dictado.py` calls it after denoise, saves the original/processed WAVs, and exposes effective thresholds to the VAD and waveform. `widget_ui.py` draws the 7-step slider and the circular processing arc, and forwards `WM_MOUSEWHEEL` to the app.

**Tech Stack:** Python 3.11, numpy 1.26, soundfile 0.12, ffmpeg via imageio-ffmpeg 0.6.0, Pillow, Tk/Win32 layered widget.

**Spec:** `docs/superpowers/specs/2026-10-23-dictado-sensibilidade-normalizacao-design.md`

## Global Constraints

- Audio is mono `float32` at 16000 Hz.
- Sensitivity is session-only, 7 levels, default 4/7; never write it to `dictado_config.json`.
- Higher level = more sensitive. Factors: `(2.0, 1.6, 1.25, 1.0, 0.8, 0.63, 0.5)`, level 4 = 1.0.
- Gate runs before loudnorm; loudnorm target is −23 LUFS, strength `suave`, TP −1.5, LRA 11.
- Save test audio only in `audios_teste/`; add it to `.gitignore` and never stage personal audio.
- Native widget is the target; `ClassicWidget` gets a no-op `set_sensitivity`.
- Keep all existing tests passing; use `unittest`, not pytest.
- Do not change the model, language, hotkey, paste flow, or RPC protocol.
- Do not commit `dictado.log`, `dictado_fault.log`, `dictado_ultimo.wav`, `dictado_config.json`, `dictado_rpc.json`, or `audios_teste/`.

## Review Focus

- **Very quiet speech at level 7:** the gate must not erase the whole take; the VAD/waveform must still see it. Test with a low-amplitude tone and with gate sensitivity −6 dB.
- **Silence-only or very short recordings:** loudnorm can return silence/NaN; the app must not crash and must keep the original. Test `loudnorm_audio` with zeros and a 0.1 s tone.
- **Wheel over a no-activate layered window:** the wheel must change only the sensitivity while ready or recording, not scroll the app underneath. Test the sign/clamp helper and verify manually on Windows 10; if Windows does not deliver `WM_MOUSEWHEEL`, add the `WH_MOUSE_LL` contingency from the spec.
- **Short transcription jobs:** progress duration can be below 1.5 s; the orange ring must still draw and must not stay stuck at 0%.
- **Missing/broken ffmpeg:** normalization must fall back to gated audio, still save the files it can, and still transcribe.

---

### Task 1: Pure-numpy gate + ffmpeg loudnorm module

**Files:**
- Create: `E:\APP\MIC\audio_fx.py`
- Create: `E:\APP\MIC\tests\test_audio_fx.py`
- Modify: `E:\APP\MIC\requirements.txt`

**Interfaces:**
- `find_ffmpeg() -> str | None`
- `gate_intervals(audio: np.ndarray, sr: int, sensitivity_db: float = 0.0) -> list[tuple[float, float]]`
- `gate_audio(audio: np.ndarray, sr: int, sensitivity_db: float = 0.0) -> np.ndarray`
- `loudnorm_filter(strength: str, target_lufs: float = -23.0, lra: int = 11) -> str`
- `loudnorm_audio(audio: np.ndarray, sr: int, target_lufs: float = -23.0, strength: str = "suave", ffmpeg: str | None = None) -> np.ndarray`
- `normalize_audio(audio: np.ndarray, sr: int, sensitivity_db: float = 0.0, strength: str = "suave", logger=None) -> np.ndarray`
- `sensitivity_factor(level: int) -> float`
- `effective_thresholds(silence: float, voice: float, level: int) -> tuple[float, float]`
- `gate_sensitivity_db(level: int) -> float`
- `next_sensitivity_level(level: int, delta: int) -> int`
- `save_wav(path: pathlib.Path, audio: np.ndarray, sr: int) -> None`
- `save_test_audio(audio: np.ndarray, sr: int, tag: str, directory: pathlib.Path) -> pathlib.Path`

- [ ] **Step 1: Write the failing tests**

```python
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_fx

SR = 16000


def _tone(seconds, amp=0.2):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


class GateTests(unittest.TestCase):
    def test_gate_zeros_silence_and_keeps_tone(self):
        audio = np.zeros(SR * 3, dtype=np.float32)
        audio[SR:SR * 2] = _tone(1.0)
        out = audio_fx.gate_audio(audio, SR)
        self.assertLess(_rms(out[:SR // 2]), 1e-4)
        self.assertGreater(_rms(out[SR:SR * 2]), 0.05)

    def test_gate_keeps_quiet_tone_at_high_sensitivity(self):
        audio = np.zeros(SR * 3, dtype=np.float32)
        audio[SR:SR * 2] = _tone(1.0, amp=0.01)
        out = audio_fx.gate_audio(audio, SR, sensitivity_db=-6.0)
        self.assertGreater(_rms(out[SR:SR * 2]), 0.003)

    def test_gate_short_audio_returns_same_shape(self):
        audio = _tone(0.1)
        out = audio_fx.gate_audio(audio, SR)
        self.assertEqual(out.shape, audio.shape)
        self.assertEqual(out.dtype, np.float32)


class MappingTests(unittest.TestCase):
    def test_level_factors_are_monotonic_and_default_is_one(self):
        factors = [audio_fx.sensitivity_factor(i) for i in range(1, 8)]
        self.assertEqual(factors[3], 1.0)
        self.assertEqual(factors, sorted(factors, reverse=True))

    def test_effective_thresholds_preserve_voice_above_silence(self):
        s, v = audio_fx.effective_thresholds(0.006, 0.02, 7)
        self.assertLess(s, 0.006)
        self.assertLess(v, 0.02)
        self.assertGreaterEqual(v, s * 1.5)

    def test_wheel_level_clamps(self):
        self.assertEqual(audio_fx.next_sensitivity_level(7, 120), 7)
        self.assertEqual(audio_fx.next_sensitivity_level(1, -120), 1)
        self.assertEqual(audio_fx.next_sensitivity_level(4, 120), 5)
        self.assertEqual(audio_fx.next_sensitivity_level(4, 0), 4)


class FfmpegTests(unittest.TestCase):
    def test_suave_chain_has_editor_values(self):
        chain = audio_fx.loudnorm_filter("suave", -23.0, 11)
        self.assertIn("acompressor=threshold=-16dB", chain)
        self.assertIn("ratio=2", chain)
        self.assertIn("loudnorm=I=-23.0", chain)

    @unittest.skipUnless(audio_fx.find_ffmpeg(), "ffmpeg not available")
    def test_loudnorm_real_ffmpeg_returns_audio(self):
        out = audio_fx.loudnorm_audio(_tone(1.0), SR)
        self.assertGreater(len(out), SR // 2)
        self.assertTrue(np.isfinite(out).all())
        self.assertGreater(float(np.abs(out).max()), 0.001)

    @unittest.skipUnless(audio_fx.find_ffmpeg(), "ffmpeg not available")
    def test_loudnorm_silence_does_not_crash(self):
        out = audio_fx.loudnorm_audio(np.zeros(SR, dtype=np.float32), SR)
        self.assertEqual(out.shape[0], SR)

    def test_normalize_falls_back_when_ffmpeg_is_missing(self):
        audio = _tone(0.5)
        with mock.patch("audio_fx.find_ffmpeg", return_value=None):
            out = audio_fx.normalize_audio(audio, SR)
        self.assertEqual(out.shape, audio.shape)
        self.assertTrue(np.isfinite(out).all())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_audio_fx.py" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_fx'`.

- [ ] **Step 3: Implement `audio_fx.py`**

Implement the gate with these exact constants:

```python
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
    "suave":  ("acompressor=threshold=-16dB:ratio=2:attack=25:release=300:makeup=1", 11),
    "padrao": ("acompressor=threshold=-20dB:ratio=3:attack=20:release=250:makeup=1", 9),
    "forte":  ("acompressor=threshold=-20dB:ratio=4:attack=20:release=250:makeup=1", 7),
}
```

`gate_intervals` must:
- Compute RMS per `int(sr * GATE_HOP)` block, convert to dB (`-120` for <1e-6).
- Take the floor as the 10th percentile of frames after skipping `int(0.4 / GATE_HOP)`; if empty, use all frames.
- Use margin 12 dB if floor > −50, 8 dB if floor < −62, otherwise 10 dB.
- Set `threshold = clamp(floor + margin + sensitivity_db, -55, -20)` and `release_at = min(threshold + 6, -16)`.
- Open a silent interval when `db < threshold`, close when `db > release_at`; keep only intervals ≥ 0.15 s.
- Merge intervals whose gap is < 0.12 s; shrink start by 0.04 s and end by 0.08 s; keep only intervals ≥ 0.08 s.
- Return seconds.

`gate_audio` must apply a gain envelope with linear fades: 1.0 until `start-0.030`, fall to 0 at `start`, stay 0 until `end`, rise to 1.0 at `end+0.015`, then 1.0. Apply to a float32 copy; if no intervals, return a copy unchanged.

`loudnorm_filter(strength, target_lufs, lra)` returns `f"{comp},loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA={lra}"` (for `-23.0`, the text is `loudnorm=I=-23.0`).

`loudnorm_audio` must:
- Use `find_ffmpeg()`; if None, raise `RuntimeError("ffmpeg nao encontrado")`.
- Write the input to a temporary 16 kHz mono PCM_16 WAV with `soundfile`.
- Run pass 1 with `-af f"{chain}:print_format=json" -f null -`; parse the last JSON object in stderr with `json.loads` after locating the first `{` of the last block.
- Run pass 2 with `measured_I`, `measured_TP`, `measured_LRA`, `measured_thresh`, `linear=true`; output a temporary WAV with `-ar 16000 -ac 1 -c:a pcm_s16le`.
- Read the output with `soundfile`; convert to mono float32; fit it to the original length by truncating or zero-padding.
- If measurement values are `-inf`, `nan`, or the output is silent, return the input unchanged (or the gated input when called from `normalize_audio`).
- Use `subprocess.run(..., capture_output=True, text=True, timeout=120)` and clean both temp files in `finally`.

`normalize_audio` runs `gate_audio` first, then `loudnorm_audio`; on any exception it logs (if `logger`) and returns the gated audio. Never raise to the caller.

`find_ffmpeg` tries, in order: `DICTADO_FFMPEG`; `imageio_ffmpeg.get_ffmpeg_exe()` (import guarded); `E:\APP\EDITOR\tools\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe`; `shutil.which("ffmpeg")`. Cache the result with `functools.lru_cache(maxsize=1)`.

`sensitivity_factor(level)` clamps to 1..7 and indexes `(2.0, 1.6, 1.25, 1.0, 0.8, 0.63, 0.5)`.
`effective_thresholds` clamps `silence * factor` to `[0.0002, 0.5]`, `voice * factor` to `[0.0004, 0.5]`, then raises voice to at least `silence * 1.5`.
`gate_sensitivity_db(level)` returns `(4 - clamp(level, 1, 7)) * 2.0`.
`next_sensitivity_level(level, delta)` returns `clamp(level, 1, 7)` when `delta == 0`; otherwise it steps one level in the sign direction and clamps to 1..7.
`save_wav` writes `float32` mono with `soundfile.write(path, audio, sr, subtype="PCM_16")`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_audio_fx.py" -v`
Expected: PASS (the two ffmpeg tests may be skipped until Step 5).

- [ ] **Step 5: Install the dependency and pin it**

Run: `.venv\Scripts\python.exe -m pip install imageio-ffmpeg==0.6.0`
Add `imageio-ffmpeg==0.6.0` to `requirements.txt` (after `soundfile`).
Run the tests again; the two ffmpeg tests must now PASS.

- [ ] **Step 6: Commit**

```powershell
git add audio_fx.py tests/test_audio_fx.py requirements.txt
git commit -m "feat: add gate and loudnorm audio processing"
```

---

### Task 2: Save original and processed test WAVs, integrate into the pipeline

**Files:**
- Modify: `E:\APP\MIC\audio_fx.py` (add `save_test_audio`)
- Modify: `E:\APP\MIC\dictado.py` (constants near 31–61; `_process_job` around 1379)
- Modify: `E:\APP\MIC\.gitignore`
- Test: `E:\APP\MIC\tests\test_audio_save.py`

**Interfaces:**
- `TEST_AUDIO_DIR: pathlib.Path` in `dictado.py`
- `_save_test_audio(audio: np.ndarray, tag: str) -> pathlib.Path` method on `DictadoApp`
- `audio_fx.save_wav(path, audio, sr)` from Task 1

- [ ] **Step 1: Write the failing test**

```python
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_fx


class SaveTests(unittest.TestCase):
    def test_save_wav_creates_mono_pcm16(self):
        with tempfile.TemporaryDirectory() as td:
            path = audio_fx.save_test_audio(
                np.zeros(1600, dtype=np.float32), 16000, "amostra", Path(td))
            data, sr = sf.read(path, dtype="float32")
            self.assertEqual(sr, 16000)
            self.assertEqual(data.shape, (1600,))
            self.assertEqual(data.dtype, np.float32)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_audio_save.py" -v`
Expected: FAIL with `AttributeError: module 'audio_fx' has no attribute 'save_test_audio'`.

- [ ] **Step 3: Implement the save path and the pipeline**

In `dictado.py`, add near the other paths:

```python
TEST_AUDIO_DIR = BASE_DIR / "audios_teste"
```

Add `save_test_audio` to `audio_fx.py`:

```python
def save_test_audio(audio, sr, tag, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{tag}.wav"
    save_wav(path, audio, sr)
    return path
```

Add the method to `DictadoApp`:

```python
def _save_test_audio(self, audio, tag):
    return audio_fx.save_test_audio(
        np.asarray(audio, dtype=np.float32), SAMPLE_RATE, tag, TEST_AUDIO_DIR
    )
```

At the start of `_process_job(audio)`, before denoise:

```python
stamp = time.strftime("%Y%m%d_%H%M%S")
try:
    self._save_test_audio(audio, f"{stamp}_original")
except Exception as exc:
    log(f"falha ao salvar audio original de teste: {exc}")
```

After denoise and before `_vad_trim`:

```python
try:
    audio = audio_fx.normalize_audio(
        audio, SAMPLE_RATE,
        sensitivity_db=0.0,  # Task 3 troca por self._gate_sensitivity_db()
        strength="suave",
        logger=log,
    )
    self._save_test_audio(audio, f"{stamp}_processado")
except Exception as exc:
    log(f"normalizacao falhou; seguindo com audio sem normalizar: {exc}")
```

Add `import audio_fx` at the top. Add `audios_teste/`, `build/`, and `dist/` to `.gitignore`.

- [ ] **Step 4: Run the save test and the full suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 5: Manual end-to-end check**

Start the app, record a short phrase, stop. Verify:
- `E:\APP\MIC\audios_teste\*_original.wav` and `*_processado.wav` exist.
- The original is the raw take; the processed one is louder/leveled and has silence reduced.
- The transcription still appears and is pasted.

- [ ] **Step 6: Commit**

```powershell
git add dictado.py .gitignore tests/test_audio_save.py
git commit -m "feat: save original and normalized test audio"
```

---

### Task 3: Session sensitivity, waveform coupling, slider, and mouse wheel

**Files:**
- Modify: `E:\APP\MIC\dictado.py` (constants; `__init__`; `_waveform_bars`; `_vad_trim`; `_start_recording`; `_stop_recording`)
- Modify: `E:\APP\MIC\widget_ui.py` (`Renderer.render`, `_draw_expanded`, `NativeWidget`, `_on_message`, `create_view`, `ClassicWidget`)
- Test: `E:\APP\MIC\tests\test_sensitivity.py`

**Interfaces:**
- `SENS_LEVELS = 7`, `SENS_DEFAULT = 4`
- `_effective_thresholds(self) -> tuple[float, float]`
- `_gate_sensitivity_db(self) -> float`
- `_set_sensitivity(self, level: int) -> None`
- `_on_sensitivity_wheel(self, delta: int) -> None`
- `NativeWidget.set_sensitivity(level: int, levels: int = 7, visible: bool = True) -> None`
- `Renderer.render(..., sens_level: int = 4, sens_levels: int = 7, sens_visible: bool = False)`
- `create_view(..., on_sensitivity=None)`

- [ ] **Step 1: Write the failing tests**

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_fx
import widget_ui


class SensitivityTests(unittest.TestCase):
    def test_default_factor_is_one(self):
        self.assertEqual(audio_fx.sensitivity_factor(4), 1.0)

    def test_higher_level_is_more_sensitive(self):
        s4, v4 = audio_fx.effective_thresholds(0.006, 0.02, 4)
        s7, v7 = audio_fx.effective_thresholds(0.006, 0.02, 7)
        self.assertLess(s7, s4)
        self.assertLess(v7, v4)
        self.assertGreaterEqual(v7, s7 * 1.5)

    def test_gate_sensitivity_is_negative_at_high_level(self):
        self.assertEqual(audio_fx.gate_sensitivity_db(4), 0.0)
        self.assertEqual(audio_fx.gate_sensitivity_db(7), -6.0)
        self.assertEqual(audio_fx.gate_sensitivity_db(1), 6.0)

    def test_wheel_changes_one_level(self):
        self.assertEqual(audio_fx.next_sensitivity_level(4, 120), 5)
        self.assertEqual(audio_fx.next_sensitivity_level(4, -120), 3)


class SliderStateTests(unittest.TestCase):
    def test_set_sensitivity_stores_level_and_visibility(self):
        w = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        w.sens_level = 4
        w.sens_levels = 7
        w.sens_visible = False
        w._dirty = False
        widget_ui.NativeWidget.set_sensitivity(w, 6, 7, True)
        self.assertEqual(w.sens_level, 6)
        self.assertEqual(w.sens_levels, 7)
        self.assertTrue(w.sens_visible)
        self.assertTrue(w._dirty)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_sensitivity.py" -v`
Expected: FAIL with `AttributeError: type object 'NativeWidget' has no attribute 'set_sensitivity'` (the audio_fx mapping tests should already pass from Task 1).

- [ ] **Step 3: Add the app state and effective thresholds**

In `dictado.py` add:

```python
SENS_LEVELS = 7
SENS_DEFAULT = 4
```

In `__init__`, after `self.cfg` is loaded:

```python
self.sens_level = SENS_DEFAULT
```

Add:

```python
def _effective_thresholds(self):
    return audio_fx.effective_thresholds(
        float(self.cfg.get("silence", 0.006)),
        float(self.cfg.get("voice", 0.02)),
        self.sens_level,
    )

def _gate_sensitivity_db(self):
    return audio_fx.gate_sensitivity_db(self.sens_level)

def _set_sensitivity(self, level):
    self.sens_level = audio_fx.next_sensitivity_level(level, 0)
    self.view.set_sensitivity(
        self.sens_level,
        SENS_LEVELS,
        self.state in (STATE_READY, STATE_RECORDING),
    )

def _on_sensitivity_wheel(self, delta):
    if self.state not in (STATE_READY, STATE_RECORDING) or not delta:
        return
    self.sens_level = audio_fx.next_sensitivity_level(self.sens_level, delta)
    self.view.set_sensitivity(self.sens_level, SENS_LEVELS, True)
```

In `_waveform_bars`, replace the direct `cfg["voice"]`/`cfg["silence"]` reads with:

```python
eff_silence, eff_voice = self._effective_thresholds()
voice = max(eff_voice, 0.0005)
floor = max(eff_silence, voice * 0.75, 0.0004)
```

In `_vad_trim`, use:

```python
_, eff_voice = self._effective_thresholds()
thr = max(eff_voice * 0.5, p90 * 0.25, 0.003)
thr = min(thr, eff_voice * 1.5)
```

In `_process_job`, replace the temporary `sensitivity_db=0.0` with:

```python
sensitivity_db=self._gate_sensitivity_db(),
```

In `_start_recording`, after entering `STATE_RECORDING`, call:

```python
self.view.set_sensitivity(self.sens_level, SENS_LEVELS, True)
```

In `_stop_recording`, after sending `stop`, keep the slider available for the
next READY hover:

```python
self.view.set_sensitivity(self.sens_level, SENS_LEVELS, True)
```

- [ ] **Step 4: Add the native slider and wheel handler**

In `widget_ui.py`:
- Add `WM_MOUSEWHEEL = 0x020A` near the other Win32 constants.
- In `_setup_win32`, declare `user32.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]` and `restype = wt.BOOL`.
- Add a `wt.POINT` structure if not already present.
- `NativeWidget.__init__` accepts `on_sensitivity=None`; store it and initialize `self.sens_level = 4`, `self.sens_levels = 7`, `self.sens_visible = False`.
- Add:

```python
def set_sensitivity(self, level, levels=7, visible=True):
    level = max(1, min(int(levels), int(level)))
    if (level, int(levels), bool(visible)) == (
        self.sens_level, self.sens_levels, self.sens_visible
    ):
        return
    self.sens_level = level
    self.sens_levels = int(levels)
    self.sens_visible = bool(visible)
    self._dirty = True
```

- `Renderer.render` accepts `sens_level`, `sens_levels`, `sens_visible` and passes them to `_draw_expanded`.
- In `NativeWidget._render`, pass `sens_level=self.sens_level`, `sens_levels=self.sens_levels`, and `sens_visible=self.sens_visible` to `self.renderer.render(...)`.
- In `NativeWidget._target_width`, allow the READY hover to expand the pill so the
  slider is available before recording:

```python
if self.state == STATE_READY and self.hover > 0.01:
    return float(EXPANDED_W)
```

- In `_draw_expanded`, in the `STATE_RECORDING` branch, after the bars/timer, draw the slider when `sens_visible`. In the READY branch, after drawing the check/status text, draw the same slider when `sens_visible` (the track sits at `cy2 - 6.0`, below the text). Use:

```python
track_x1 = cx1 + 30.0
track_x2 = cx2 - 58.0
track_y = cy2 - 6.0
d.rounded_rectangle(
    [self._px(track_x1), self._px(track_y - 1.0),
     self._px(track_x2), self._px(track_y + 1.0)],
    radius=self._px(1.0), fill=(255, 255, 255, 40),
)
for i in range(sens_levels):
    tx = track_x1 + (track_x2 - track_x1) * i / max(1, sens_levels - 1)
    d.ellipse(
        [self._px(tx - 1.1), self._px(track_y - 1.1),
         self._px(tx + 1.1), self._px(track_y + 1.1)],
        fill=(255, 255, 255, 80),
    )
knob_x = track_x1 + (track_x2 - track_x1) * (sens_level - 1) / max(1, sens_levels - 1)
d.ellipse(
    [self._px(knob_x - 2.6), self._px(track_y - 2.6),
     self._px(knob_x + 2.6), self._px(track_y + 2.6)],
    fill=accent + (245,),
)
```

- In `_on_message`, handle `WM_MOUSEWHEEL`:

```python
if msg == WM_MOUSEWHEEL:
    delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
    pt = wt.POINT(ctypes.c_short(lparam & 0xFFFF).value,
                  ctypes.c_short((lparam >> 16) & 0xFFFF).value)
    user32.ScreenToClient(wt.HWND(self._hwnd), ctypes.byref(pt))
    if self._hit_local(pt.x, pt.y) == "content" and self.on_sensitivity:
        self._call(lambda d=delta: self.on_sensitivity(d))
        return 0
    return DefWindowProc(hwnd, msg, wparam, lparam)
```

- Add `on_sensitivity=None` to `create_view` and pass it to `NativeWidget` and `ClassicWidget`.
- Add a no-op `set_sensitivity` to `ClassicWidget`.

- [ ] **Step 5: Run the tests and manual check**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
Expected: all tests PASS.

Manual:
- Start a recording; the slider appears below the waveform.
- Hover the pill and roll the wheel up/down; the knob moves one step per notch and the waveform rescales.
- Stop and start another recording; the level persists.
- Restart the app; the level returns to 4/7.
- If the wheel does nothing, check Windows “Scroll inactive windows when I hover over them”; if still nothing, implement the `WH_MOUSE_LL` contingency from the spec.

- [ ] **Step 6: Commit**

```powershell
git add dictado.py widget_ui.py tests/test_sensitivity.py
git commit -m "feat: add session sensitivity slider and wheel control"
```

---

### Task 4: Circular processing with orange perimeter and 2-second transcription text

**Files:**
- Modify: `E:\APP\MIC\widget_ui.py` (`Renderer.render`, `_draw_idle`, `_target_width`)
- Modify: `E:\APP\MIC\dictado.py` (`_schedule_revert`, `_tick_progress`)
- Test: `E:\APP\MIC\tests\test_processing_visual.py`

**Interfaces:**
- `_target_width()` returns `IDLE_W` for `STATE_PROCESSING`.
- `Renderer._draw_idle(..., progress=None)`
- `STATUS_REVERT_MS = 2000` in `dictado.py`

- [ ] **Step 1: Write the failing tests**

```python
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import widget_ui


class TargetWidthTests(unittest.TestCase):
    def test_processing_is_circular(self):
        w = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        w.state = widget_ui.STATE_PROCESSING
        w.status = ""
        self.assertEqual(w._target_width(), widget_ui.IDLE_W)

    def test_status_is_expanded(self):
        w = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        w.state = widget_ui.STATE_READY
        w.status = "texto"
        self.assertEqual(w._target_width(), widget_ui.EXPANDED_W)


class RingTests(unittest.TestCase):
    def test_processing_draws_orange_pixels(self):
        r = widget_ui.Renderer(0.8)
        img = r.render(state=widget_ui.STATE_PROCESSING,
                       width=widget_ui.IDLE_W, progress=50)
        self.assertIsInstance(img, Image.Image)
        pixels = img.convert("RGBA").getdata()
        orange = sum(1 for r_, g_, b_, a_ in pixels
                     if r_ > 150 and g_ > 60 and b_ < 80 and a_ > 0)
        self.assertGreater(orange, 10)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_processing_visual.py" -v`
Expected: FAIL because `_target_width` returns `EXPANDED_W` for processing and `_draw_idle` has no processing ring.

- [ ] **Step 3: Implement the circular processing state**

In `NativeWidget._target_width`:

```python
if self.state == STATE_RECORDING:
    return float(EXPANDED_W)
if self.state == STATE_PROCESSING:
    return float(IDLE_W)
if self.state == STATE_ERROR or self.status:
    return float(EXPANDED_W)
if self.state == STATE_READY and self.hover > 0.01:
    return float(EXPANDED_W)
return float(IDLE_W)
```

In `Renderer.render`, pass `progress` to `_draw_idle`:

```python
self._draw_idle(idle, state, accent, cx1, cx2, cy1, cy2,
                spinner, pulse, progress)
```

In `_draw_idle`, add the processing branch after the mic:

```python
if state == STATE_PROCESSING:
    pct = _clamp(float(progress or 0.0), 0.0, 100.0)
    pct = max(2.0, pct)
    rad = 26.0
    box = [self._px(cx - rad), self._px(cy - rad),
           self._px(cx + rad), self._px(cy + rad)]
    d.arc(box, start=0, end=360, fill=(255, 159, 10, 45),
          width=max(1, int(round(2.4 * u))))
    d.arc(box, start=-90.0, end=-90.0 + 360.0 * pct / 100.0,
          fill=accent + (245,), width=max(1, int(round(2.4 * u))))
    return
```

In `dictado.py`:
- Add `STATUS_REVERT_MS = 2000`.
- `_schedule_revert` uses `self.root.after(STATUS_REVERT_MS, self._do_revert)`.
- `_tick_progress` no longer returns early for short jobs; use `pct = max(4, min(97, int(elapsed / self._progress_dur * 100)))` and always schedule the next tick while processing.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
Expected: all tests PASS.

Manual:
- Record, stop; the pill becomes a circle with an orange arc around the perimeter.
- When the text is ready, the pill expands and shows the snippet; after ~2 s it returns to the circle.
- Test a very short take (less than 1.5 s) and confirm the ring still appears.

- [ ] **Step 5: Commit**

```powershell
git add dictado.py widget_ui.py tests/test_processing_visual.py
git commit -m "feat: add circular processing progress and transient transcript text"
```

---

### Task 5: Documentation, ignored artifacts, and final verification

**Files:**
- Modify: `E:\APP\MIC\README.md` (add a short “Sensibilidade durante a gravação” paragraph under the usage section)
- Modify: `E:\APP\MIC\.gitignore` if not already updated
- Test: full suite + manual checklist

- [ ] **Step 1: Update the README**

Add, under the “Como usar” section:

```markdown
Durante a gravação, passe o mouse sobre a pílula e use a rodinha para ajustar
a sensibilidade (7 níveis). O ajuste vale só nesta sessão e volta ao padrão
quando o Dictado é reaberto. A onda acompanha o nível escolhido.
```

- [ ] **Step 2: Confirm ignored artifacts**

`git status --short` must not list `audios_teste/`, `dictado.log`, `dictado_fault.log`, `dictado_ultimo.wav`, `dictado_config.json`, `dictado_rpc.json`, `build/`, or `dist/`.

- [ ] **Step 3: Run the full test suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 4: Manual acceptance**

- Record a quiet phrase at level 7; confirm the waveform moves and the transcript is not empty.
- Record a normal phrase; confirm the processed WAV is leveled and the original is preserved.
- Stop a recording and watch the circle/ring/text sequence.
- Confirm the wheel does not scroll the app underneath.

- [ ] **Step 5: Commit**

```powershell
git add README.md .gitignore
git commit -m "docs: document sensitivity control and test audio"
```
