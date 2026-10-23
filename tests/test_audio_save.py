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

    def test_save_latest_clears_previous_wavs(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            old = directory / "20260101_120000_original.wav"
            old.write_bytes(b"antigo")
            audio_fx.save_test_audio(
                np.zeros(1600, dtype=np.float32), 16000,
                "ultimo_original", directory, clear_previous=True)
            self.assertFalse(old.exists())
            self.assertTrue((directory / "ultimo_original.wav").exists())

    def test_processed_does_not_remove_original(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            audio = np.zeros(1600, dtype=np.float32)
            audio_fx.save_test_audio(
                audio, 16000, "ultimo_original", directory,
                clear_previous=True)
            audio_fx.save_test_audio(
                audio, 16000, "ultimo_processado", directory)
            self.assertTrue((directory / "ultimo_original.wav").exists())
            self.assertTrue((directory / "ultimo_processado.wav").exists())


class DictadoIntegrationTests(unittest.TestCase):
    def test_dictado_exposes_test_audio_dir_and_saver(self):
        import dictado

        self.assertEqual(Path(dictado.TEST_AUDIO_DIR).name, "audios_teste")
        self.assertTrue(hasattr(dictado.DictadoApp, "_save_test_audio"))


if __name__ == "__main__":
    unittest.main()
