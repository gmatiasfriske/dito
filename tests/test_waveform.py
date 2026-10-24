import threading
import unittest
from types import MethodType, SimpleNamespace

import numpy as np

from dictado_app import dictado

SR = dictado.SAMPLE_RATE


def _audio(value, seconds=0.9):
    return np.full(int(SR * seconds), value, dtype=np.float32)


class WaveformScaleTest(unittest.TestCase):
    def _bars(self, audio):
        app = SimpleNamespace(
            recorder_mode=False,
            buffer_lock=threading.Lock(),
            buffer=[audio],
            cfg={"silence": 0.006, "voice": 0.02},
            sens_level=4,
        )
        app._effective_thresholds = MethodType(
            dictado.DictadoApp._effective_thresholds, app)
        return dictado.DictadoApp._waveform_bars(app, n=36, span=0.9)

    def test_silence_stays_at_baseline(self):
        bars = self._bars(_audio(0.001))
        self.assertEqual(bars, [0.02] * 36)

    def test_steady_noise_does_not_fill_the_waveform(self):
        bars = self._bars(_audio(0.02))
        self.assertLess(max(bars), 0.25)

    def test_speech_rises_above_noise(self):
        noise = self._bars(_audio(0.02))
        speech = self._bars(_audio(0.12))
        self.assertGreater(max(speech), 0.7)
        self.assertGreater(max(speech), max(noise) * 3.0)

    def test_loud_neighbor_does_not_rescale_existing_noise(self):
        quiet = self._bars(_audio(0.02))
        mixed = self._bars(np.concatenate([
            _audio(0.02, 0.45),
            _audio(0.20, 0.45),
        ]))
        # Os primeiros 18 quadros sao o mesmo ruido de 0,02 nos dois casos.
        # Com a normalizacao antiga, o trecho barulhento reduzia esses quadros.
        np.testing.assert_allclose(quiet[:18], mixed[:18], atol=1e-6)


if __name__ == "__main__":
    unittest.main()

