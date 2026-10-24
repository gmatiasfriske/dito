import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dictado_app import audio_fx

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

    def test_gate_keeps_quiet_tone_when_floor_is_low(self):
        audio = np.zeros(SR * 3, dtype=np.float32)
        audio[SR:SR * 2] = _tone(1.0, amp=0.01)
        out = audio_fx.gate_audio(audio, SR)
        self.assertGreater(_rms(out[SR:SR * 2]), 0.003)

    def test_gate_short_audio_returns_same_shape(self):
        audio = _tone(0.1)
        out = audio_fx.gate_audio(audio, SR)
        self.assertEqual(out.shape, audio.shape)
        self.assertEqual(out.dtype, np.float32)

    def test_gate_does_not_erase_continuous_tone(self):
        audio = _tone(2.0, amp=0.012)
        out = audio_fx.gate_audio(audio, SR)
        self.assertGreater(_rms(out), _rms(audio) * 0.9)


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
        with mock.patch("dictado_app.audio_fx.find_ffmpeg", return_value=None):
            out = audio_fx.normalize_audio(audio, SR)
        self.assertEqual(out.shape, audio.shape)
        self.assertTrue(np.isfinite(out).all())

    def test_ffmpeg_runs_without_a_console_window(self):
        with mock.patch("dictado_app.audio_fx.subprocess.run") as run:
            audio_fx._run_ffmpeg(["ffmpeg", "-version"])
        flags = run.call_args.kwargs.get("creationflags")
        self.assertEqual(flags, getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    unittest.main()

