"""Gravador de microfone em processo separado.

Isolamento contra crashes do PortAudio quando outros aplicativos disputam
o microfone: se este processo morrer, o app principal sobrevive.

Protocolo (stdout binario):
  [u32 LE tamanho][dados float32 mono 16kHz]   lote de audio
  [u32 LE 0xFFFFFFFF]                          fim da gravacao ("stop")

Comandos (stdin, uma linha cada):
  start / stop / quit
"""
import struct
import sys
import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
END_MARKER = 0xFFFFFFFF
out = sys.stdout.buffer


def err(msg):
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def find_device():
    try:
        hostapis = sd.query_hostapis()
        wasapi_idx = next(
            (i for i, h in enumerate(hostapis) if "WASAPI" in h["name"].upper()),
            None,
        )
        devs = sd.query_devices()
        default_in = sd.default.device[0]
        info = None
        if 0 <= default_in < len(devs):
            info = devs[default_in]
        if info is not None and info["hostapi"] == wasapi_idx \
                and info["max_input_channels"] > 0:
            return default_in
        if wasapi_idx is not None:
            for i, d in enumerate(devs):
                if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0 \
                        and (info is None or d["name"] == info["name"]):
                    return i
    except Exception:
        pass
    return None


class Recorder:
    def __init__(self):
        self.stream = None

    def _callback(self, indata, frames, time_info, status):
        try:
            data = indata.tobytes()
            out.write(struct.pack("<I", len(data)))
            out.write(data)
            out.flush()
        except Exception:
            pass

    def start(self):
        if self.stream is not None:
            return
        kwargs = dict(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=self._callback,
        )
        dev = find_device()
        if dev is not None:
            kwargs["device"] = dev
            try:
                kwargs["extra_settings"] = sd.WasapiSettings(
                    exclusive=False, auto_convert=True)
            except Exception:
                pass
        try:
            self.stream = sd.InputStream(**kwargs)
            self.stream.start()
        except Exception as exc:
            err("wasapi falhou (%s), tentando padrao" % exc)
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            kwargs.pop("extra_settings", None)
            kwargs.pop("device", None)
            self.stream = sd.InputStream(**kwargs)
            self.stream.start()
        err("started")

    def stop(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass


def main():
    rec = Recorder()
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if not line:
            break
        cmd = line.strip()
        if cmd == "start":
            try:
                rec.start()
            except Exception as exc:
                err("erro: %s" % exc)
                rec.stop()
        elif cmd == "stop":
            rec.stop()
            try:
                out.write(struct.pack("<I", END_MARKER))
                out.flush()
            except Exception:
                break
        elif cmd == "quit":
            rec.stop()
            break


if __name__ == "__main__":
    main()
