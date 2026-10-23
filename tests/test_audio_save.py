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


class DictadoIntegrationTests(unittest.TestCase):
    def test_dictado_exposes_test_audio_dir_and_saver(self):
        import dictado

        self.assertEqual(Path(dictado.TEST_AUDIO_DIR).name, "audios_teste")
        self.assertTrue(hasattr(dictado.DictadoApp, "_save_test_audio"))


if __name__ == "__main__":
    unittest.main()
