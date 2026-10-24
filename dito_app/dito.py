import ctypes
import ctypes.wintypes
import gc
import json
import math
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque

import numpy as np

try:
    from . import audio_fx, ui_dispatch, widget_ui
except ImportError:  # permite rodar dito.py diretamente, se necessario
    import audio_fx
    import ui_dispatch
    import widget_ui

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

import warnings
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
warnings.filterwarnings("ignore", message=".*torch_dtype.*")

import logging
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

MODEL_SIZE = "large"
LANGUAGE = "pt"
SAMPLE_RATE = 16000
HOTKEY = "ctrl+y"
SENS_LEVELS = 7
SENS_DEFAULT = 4
LANGUAGES = {
    "Português": "pt",
    "English": "en",
    "Español": "es",
}

DEFAULT_CFG = {
    "silence": 0.006,
    "voice": 0.02,
    "denoise": True,
    "ui": "auto",
    "ui_scale": 0.8,
    "language": "pt",
}

STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_RECORDING = "recording"
STATE_PROCESSING = "processing"
STATE_ERROR = "error"

FROZEN = bool(getattr(sys, "frozen", False))
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
            else os.path.dirname(PACKAGE_DIR))
RES_DIR = getattr(sys, "_MEIPASS", BASE_DIR) if FROZEN else PACKAGE_DIR
LOG_PATH = os.path.join(BASE_DIR, "dito.log")
LAST_AUDIO_PATH = os.path.join(BASE_DIR, "dito_ultimo.wav")
CFG_PATH = os.path.join(BASE_DIR, "dito_config.json")
ICON_PATH = os.path.join(BASE_DIR, "dito.ico")
if not os.path.exists(ICON_PATH):
    ICON_PATH = os.path.join(RES_DIR, "dito.ico")
SPLASH_PATH = os.path.join(RES_DIR, "splash_ui.py")
if FROZEN:
    RECORDER_PATH = os.path.join(BASE_DIR, "mic_recorder.exe")
    if not os.path.isfile(RECORDER_PATH):
        RECORDER_PATH = os.path.join(RES_DIR, "mic_recorder.exe")
else:
    RECORDER_PATH = os.path.join(PACKAGE_DIR, "mic_recorder.py")
RPC_CFG_PATH = os.path.join(BASE_DIR, "dito_rpc.json")
RPC_DEFAULT_PORT = 8765

WM_PASTE = 0x0302

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_Y = 0x59
HOTKEY_ID = 0xB00B
WATCHDOG_MS = 20000
STATUS_REVERT_MS = 2000


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, value in data.items():
            if key not in cfg:
                continue
            if isinstance(DEFAULT_CFG[key], str):
                cfg[key] = str(value)
            else:
                cfg[key] = float(value)
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception as exc:
        log(f"falha salvar config: {exc}")


def meter_pos(level):
    if level <= 0:
        return 0.0
    pos = math.log10(level / 0.0005) / 3.0
    return max(0.0, min(1.0, pos))


def audio_envelope(audio, frame=0.02, attack=0.35, release=0.04):
    n = max(1, int(SAMPLE_RATE * frame))
    usable = audio[: len(audio) - (len(audio) % n)]
    rms = np.sqrt((usable.reshape(-1, n) ** 2).mean(axis=1))
    env = np.empty_like(rms)
    e = 0.0
    for i, v in enumerate(rms):
        e += (v - e) * (attack if v > e else release)
        env[i] = e
    return env, n


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", ctypes.wintypes.RECT),
    ]


class DitoApp:
    def __init__(self, root):
        self.root = root
        self.state = STATE_LOADING
        self.recording = False
        self.buffer = []
        self.buffer_lock = threading.Lock()
        self.level_peaks = deque(maxlen=48)
        self.stream = None
        self.model = None
        self.error_msg = ""
        self.last_text = ""
        self.last_rms = 0.0
        self._revert_id = None
        self.jobs = queue.Queue()
        self.gpu_lock = threading.Lock()
        self.hotkey_queue = queue.Queue()
        self.env = 0.0
        self.cfg = load_cfg()
        self.sens_level = SENS_DEFAULT
        self.settings_open = False
        self.settings_win = None
        self.preview_stream = None
        self.preview_peaks = deque(maxlen=48)
        self.record_start = None
        self.rtf = 0.4  # seg de processamento por seg de audio (GPU+chunks)
        self._progress_start = 0.0
        self._progress_dur = 0.0
        self.recorder_proc = None
        self.recorder_mode = False
        self.recorder_chunks = []
        self._rec_done = threading.Event()
        self._model_loading = False
        self._load_lock = threading.Lock()
        self._hotkey_tid = 0
        self._hotkey_stop = None
        self.ui_queue = ui_dispatch.UiDispatcher(logger=log)

        self._splash_proc = None
        self._splash_watch_id = None
        self.view = widget_ui.create_view(
            root, self.cfg,
            on_toggle=self.toggle,
            on_settings=self._open_settings,
            on_copy=self.on_copy,
            on_close=self.on_close,
            on_sensitivity=self._on_sensitivity_wheel,
            logger=log,
            show=False,
        )
        self.scale = getattr(
            self.view, "settings_scale",
            getattr(self.view, "scale", 1.0))
        self.view.set_state(STATE_LOADING)
        self.view.set_sensitivity(self.sens_level, SENS_LEVELS, True)
        if isinstance(self.view, widget_ui.NativeWidget):
            self._start_splash()
        else:
            self.view.show()
        log(f"app iniciado (silêncio={self.cfg['silence']}, "
            f"voz={self.cfg['voice']}, denoise={self.cfg.get('denoise', True)}, "
            f"ui={self.cfg.get('ui', 'auto')})")

        self._start_load_once()
        threading.Thread(target=self._job_loop, daemon=True).start()
        threading.Thread(target=self._warm_recorder, daemon=True).start()
        threading.Thread(target=self._start_rpc, daemon=True).start()
        self._tick_level()
        self.root.after(16, self._drain_ui)

        # RegisterHotKey do Windows: nao expira como o hook de baixo nivel da
        # lib keyboard (que era removido em silencio apos um timeout).
        self._start_hotkey_listener()
        self.root.report_callback_exception = self._report_callback_exception
        self.root.after(WATCHDOG_MS, self._watchdog)

        try:
            import sounddevice as sd
            dev = sd.query_devices(sd.default.device[0])
            log(f"microfone default: {dev['name']}")
        except Exception as exc:
            log(f"sem microfone consultavel: {exc}")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _start_splash(self):
        # A interface de loading roda em um processo separado para o
        # carregamento pesado do modelo nao roubar o GIL do widget.
        if self._splash_proc is not None:
            return
        try:
            factor = self.cfg.get("ui_scale", widget_ui.DEFAULT_UI_SCALE)
            if FROZEN:
                cmd = [sys.executable, "--splash", str(factor)]
                stdin = subprocess.DEVNULL
            else:
                if not os.path.isfile(SPLASH_PATH):
                    raise RuntimeError("splash ausente")
                cmd = [sys.executable, SPLASH_PATH, str(factor)]
                stdin = subprocess.PIPE
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            env = os.environ.copy()
            env["DITO_PARENT_PID"] = str(os.getpid())
            self._splash_proc = subprocess.Popen(
                cmd,
                stdin=stdin,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=BASE_DIR,
                env=env,
                creationflags=creationflags,
            )
            log("splash de carregamento em processo separado")
            self._splash_watch_id = self.root.after(
                1200, self._check_splash)
        except Exception as exc:
            self._splash_proc = None
            log(f"sem splash separado: {exc}")
            try:
                self.view.set_visible(True)
            except Exception:
                pass

    def _check_splash(self):
        self._splash_watch_id = None
        proc = self._splash_proc
        if proc is None:
            return
        if proc.poll() is not None:
            self._splash_proc = None
            log("splash encerrou antes do modelo")
            try:
                self.view.set_visible(True)
            except Exception:
                pass
            return
        if self.state == STATE_LOADING:
            self._splash_watch_id = self.root.after(
                1200, self._check_splash)

    def _stop_splash(self, show_view=True):
        proc = self._splash_proc
        self._splash_proc = None
        if self._splash_watch_id is not None:
            try:
                self.root.after_cancel(self._splash_watch_id)
            except Exception:
                pass
            self._splash_watch_id = None
        if proc is not None:
            if proc.stdin is not None:
                try:
                    proc.stdin.write(b"quit\n")
                    proc.stdin.flush()
                    proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            else:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass
        if show_view:
            try:
                self.view.set_visible(True)
            except Exception:
                pass

    def _start_hotkey_listener(self):
        self._hotkey_stop = threading.Event()
        threading.Thread(target=self._hotkey_loop, daemon=True).start()

    def _hotkey_loop(self):
        # RegisterHotKey num thread proprio com GetMessage: o Windows mantem o
        # registro enquanto o processo viver (nao depende de hook de baixo
        # nivel, que o Windows remove sem avisar quando demora > ~300ms)
        import ctypes.wintypes as wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT,
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._hotkey_tid = int(kernel32.GetCurrentThreadId())
        registered = False
        while not self._hotkey_stop.is_set():
            if not registered:
                if user32.RegisterHotKey(
                        None, HOTKEY_ID, MOD_CONTROL | MOD_NOREPEAT, VK_Y):
                    registered = True
                    log(f"hotkey {HOTKEY} registrado (RegisterHotKey)")
                else:
                    err = ctypes.get_last_error()
                    log(f"falha ao registrar hotkey {HOTKEY} "
                        f"(erro {err}); tentando de novo em 15s")
                    self._hotkey_stop.wait(15)
                    continue
            msg = wintypes.MSG()
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                # nao mexe no Tk nem no estado daqui: so avisa a thread da
                # interface, que executa o toggle sem corrida com o gravador
                self.hotkey_queue.put(True)
        if registered:
            try:
                user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass

    def _watchdog(self):
        try:
            self._check_window()
        except Exception as exc:
            log(f"watchdog: {exc}")
        self.root.after(WATCHDOG_MS, self._watchdog)

    def _is_own_hwnd(self, hwnd):
        if not hwnd:
            return False
        try:
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                int(hwnd), ctypes.byref(pid))
            return int(pid.value) == os.getpid()
        except Exception:
            return False

    def _check_window(self):
        # o topmost e a janela sem borda podem se perder sozinhos depois de
        # horas (economia de energia, lock, fullscreen, app maximizado
        # cobrindo); conserta sem precisar reiniciar o app
        user32 = ctypes.windll.user32
        if not getattr(self.view, "visible", True):
            return
        hwnd = self.view.hwnd if self.view is not None else 0
        if not hwnd:
            return
        if not user32.IsWindowVisible(hwnd):
            log("watchdog: janela invisivel; restaurando")
            self.view.show()
            self.view.reassert()
            return
        x, y, w, h = self.view.rect()
        if w <= 0 or h <= 0:
            log("watchdog: janela colapsada; reposicionando")
            self.view.place_bottom_right()
            self.view.reassert()
            return
        rect = ctypes.wintypes.RECT(x, y, x + w, y + h)
        if not user32.MonitorFromRect(ctypes.byref(rect), 0):
            log("watchdog: janela fora da tela; reposicionando")
            self.view.place_bottom_right()
            self.view.reassert()
            return
        # NOTA: checar so o bit WS_EX_TOPMOST (0x8) NAO basta — o bit
        # permanece setado mesmo com a janela enterrada sob maximizadas.
        # Reafirma sempre e detecta oclusao real pelo ponto visivel.
        self.view.reassert()
        try:
            cx, cy = self.view.visible_center()
            pt_hwnd = user32.WindowFromPoint(ctypes.wintypes.POINT(cx, cy))
            if pt_hwnd and int(pt_hwnd) != int(hwnd):
                try:
                    root_hwnd = user32.GetAncestor(int(pt_hwnd), 2)
                except Exception:
                    root_hwnd = pt_hwnd
                if int(root_hwnd) != int(hwnd):
                    log("watchdog: janela ocluida sob outro app; "
                        "trazendo ao topo")
                    self.view.reassert()
        except Exception:
            pass

    def _set_state(self, state, extra=None):
        if state != STATE_LOADING and self._splash_proc is not None:
            self._stop_splash(show_view=False)
        self.state = state
        if extra is None and state == STATE_ERROR and self.error_msg:
            extra = self.error_msg[:70]
        self.view.set_state(state, extra)
        if state != STATE_LOADING and not self.view.visible:
            self.view.show()
        self._schedule_revert()

    def _show_status(self, text):
        self.view.set_status(text)
        self._schedule_revert()

    def _schedule_revert(self):
        if self._revert_id is not None:
            self.root.after_cancel(self._revert_id)
        self._revert_id = self.root.after(
            STATUS_REVERT_MS, self._do_revert)

    def _do_revert(self):
        self._revert_id = None
        if self.recording:
            return
        self.view.clear_status()

    def _tick_progress(self):
        if self.state != STATE_PROCESSING or self._progress_dur <= 0:
            return
        elapsed = time.time() - self._progress_start
        pct = max(4, min(97, int(elapsed / self._progress_dur * 100)))
        self.view.set_progress(pct)
        self.root.after(200, self._tick_progress)

    def _ui(self, fn, *args):
        # Tkinter so pode ser tocado pela thread principal.  As threads de
        # modelo/gravacao/RPC enfileiram aqui; _drain_ui roda no Tk.
        self.ui_queue.submit(fn, *args)

    def _drain_ui(self):
        if self.ui_queue.closed:
            return
        self.ui_queue.drain()
        self.root.after(16, self._drain_ui)

    def _effective_thresholds(self):
        return audio_fx.effective_thresholds(
            float(self.cfg.get("silence", 0.006)),
            float(self.cfg.get("voice", 0.02)),
            self.sens_level,
        )

    def _language(self):
        value = str(self.cfg.get("language", LANGUAGE) or LANGUAGE).strip()
        return value if value in LANGUAGES.values() else LANGUAGE

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
        log(f"sensibilidade: {self.sens_level}/{SENS_LEVELS}")

    def _waveform_bars(self, n=36, span=0.9):
        # desenha o envelope real dos ultimos ~0,9s; sem som, fica parado
        need = max(1, int(SAMPLE_RATE * span))
        blocks = []
        total = 0
        try:
            if self.recorder_mode:
                for data in reversed(list(self.recorder_chunks)):
                    if not data:
                        continue
                    arr = np.frombuffer(data, dtype=np.float32)
                    if arr.size == 0:
                        continue
                    blocks.append(arr)
                    total += arr.size
                    if total >= need:
                        break
            else:
                with self.buffer_lock:
                    recent = list(self.buffer)
                for arr in reversed(recent):
                    if arr is None or arr.size == 0:
                        continue
                    arr = arr.reshape(-1)
                    blocks.append(arr)
                    total += arr.size
                    if total >= need:
                        break
            if not blocks:
                return [0.02] * n
            audio = np.concatenate(blocks[::-1])[-need:]
        except Exception:
            return [0.02] * n
        edges = np.linspace(0, audio.size, n + 1).astype(np.int32)
        vals = np.zeros(n, dtype=np.float32)
        for i in range(n):
            seg = audio[edges[i]:edges[i + 1]]
            if seg.size:
                peak = float(np.max(np.abs(seg)))
                rms = float(np.sqrt(np.mean(seg * seg)))
                vals[i] = 0.72 * peak + 0.28 * rms
        # Escala fixa: o mesmo ruido sempre gera a mesma altura. Antes a
        # referencia era o maior pico da janela, entao um ruido passageiro
        # fazia a onda inteira "redimensionar" para cima.
        eff_silence, eff_voice = self._effective_thresholds()
        voice = max(eff_voice, 0.0005)
        ref = min(max(voice * 8.0, 0.12), 0.5)
        floor = max(eff_silence, voice * 0.75, 0.0004)
        floor = min(floor, ref * 0.75)
        out = []
        for v in vals:
            if v <= floor:
                out.append(0.02)
            else:
                h = ((v - floor) / max(0.0001, ref - floor)) ** 0.62
                out.append(min(1.0, max(0.03, h)))
        return out

    def _tick_level(self):
        try:
            while True:
                self.hotkey_queue.get_nowait()
                self.toggle()
        except queue.Empty:
            pass
        if self.recording:
            if self.record_start is not None:
                el = int(time.time() - self.record_start)
                self.view.set_timer(f"{el // 60}:{el % 60:02d}")
            if self.recorder_mode:
                ch = self.recorder_chunks
                if ch:
                    tail = np.frombuffer(ch[-1][-8192:], dtype=np.float32)
                    level = float(np.abs(tail).max()) if tail.size else 0.0
                else:
                    level = 0.0
            else:
                with self.buffer_lock:
                    peaks = list(self.level_peaks)
                level = max(peaks) if peaks else 0.0
            self.view.set_waveform(self._waveform_bars())
        else:
            level = 0.0
        if level > self.env:
            self.env += (level - self.env) * 0.85
        else:
            self.env += (level - self.env) * 0.30
        self.view.set_level(self.env)
        self._check_recorder_alive()
        self.root.after(50, self._tick_level)

    def _check_recorder_alive(self):
        # gravador externo pode falhar ao abrir o dispositivo (ex.: USB caiu,
        # mic sumiu do sistema): nesse caso os "chamados" gravam 0 bytes e o
        # app ficaria "gravando" para sempre; aborta e avisa
        if not (self.recording and self.recorder_mode) \
                or self.record_start is None:
            return
        if time.time() - self.record_start < 2.5:
            return
        if self.recorder_chunks:
            return
        self.recording = False
        self.record_start = None
        try:
            proc = self.recorder_proc
            if proc is not None and proc.stdin is not None:
                proc.stdin.write(b"stop\n")
                proc.stdin.flush()
        except Exception:
            pass
        log("ALERTA: gravador externo nao retornou audio; "
            "verifique o microfone (desconectado/erro?)")
        self._set_state(STATE_READY, "mic sumiu?")

    def _slider_to_level(self, v):
        return 0.0005 * 10 ** (3.0 * v / 100.0)

    def _level_to_slider(self, level):
        return max(0, min(100, int(
            100.0 * (math.log10(max(level, 0.0005) / 0.0005) / 3.0))))

    def _open_settings(self, event=None):
        if self.settings_open:
            return
        self.settings_open = True
        s = self.scale
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.title("Níveis de áudio")
        try:
            win.iconbitmap(ICON_PATH)
        except Exception:
            pass
        win.configure(bg="#141416")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_settings(win))

        silence_var = tk.DoubleVar(
            value=self._level_to_slider(self.cfg["silence"]))
        voice_var = tk.DoubleVar(
            value=self._level_to_slider(self.cfg["voice"]))
        denoise_var = tk.BooleanVar(value=self.cfg.get("denoise", True))
        current_language = self._language()
        language_label = next(
            (name for name, code in LANGUAGES.items()
             if code == current_language),
            "Português",
        )
        language_var = tk.StringVar(value=language_label)

        outer = tk.Frame(win, bg="#141416", padx=int(round(18 * s)),
                         pady=int(round(14 * s)))
        outer.pack(fill="both", expand=True)

        tk.Label(
            outer, text="Níveis de áudio", bg="#141416", fg="#f5f5f7",
            font=("Segoe UI", 12, "bold"), anchor="w",
        ).pack(fill="x")
        tk.Label(
            outer,
            text="Ajuste para o ruído do ambiente ficar abaixo do silêncio.",
            bg="#141416", fg="#8e8e93", font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x", pady=(2, 12))

        tk.Label(
            outer, text="Silêncio  ·  abaixo disso é ignorado",
            bg="#141416", fg="#c7c7cc", font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x")
        widget_ui.ModernSlider(
            outer, silence_var, length=260, scale=s,
        ).pack(pady=(2, 10))

        tk.Label(
            outer, text="Voz  ·  acima disso é fala",
            bg="#141416", fg="#c7c7cc", font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x")
        widget_ui.ModernSlider(
            outer, voice_var, length=260, scale=s,
        ).pack(pady=(2, 12))

        preview = tk.Canvas(
            outer, width=int(round(260 * s)), height=int(round(18 * s)),
            bg="#141416", highlightthickness=0, bd=0,
        )
        preview.pack(fill="x")
        pw = int(round(260 * s))
        ph = int(round(18 * s))
        py = ph // 2
        bar_w = max(6, int(round(12 * s)))
        preview.create_line(
            0, py, pw, py, fill="#26262c", width=bar_w, capstyle="round")
        pfill = preview.create_line(
            0, py, 0, py, fill="#34c759", width=bar_w, capstyle="round")
        pmark_voice = preview.create_line(
            0, 0, 0, ph, fill="#ff453a", width=max(1, int(round(s))))
        pmark_sil = preview.create_line(
            0, 0, 0, ph, fill="#8e8e93", width=max(1, int(round(s))))
        tk.Label(
            outer, text="fale agora para ajustar", bg="#141416",
            fg="#636366", font=("Segoe UI", 8), anchor="w",
        ).pack(fill="x", pady=(2, 10))

        lang_row = tk.Frame(outer, bg="#141416")
        lang_row.pack(fill="x", pady=(0, 10))
        tk.Label(
            lang_row, text="Idioma da transcrição", bg="#141416",
            fg="#e5e5ea", font=("Segoe UI", 9), anchor="w",
        ).pack(side="left")
        lang_menu = tk.OptionMenu(
            lang_row, language_var, *LANGUAGES.keys())
        lang_menu.config(
            bg="#2c2c33", fg="#f5f5f7", activebackground="#3a3a42",
            activeforeground="#ffffff", highlightthickness=0, bd=0,
            font=("Segoe UI", 9), width=12, anchor="w",
        )
        lang_menu["menu"].config(
            bg="#2c2c33", fg="#f5f5f7", activebackground="#0a84ff",
            activeforeground="#ffffff", font=("Segoe UI", 9),
        )
        lang_menu.pack(side="right")

        denoise_row = tk.Frame(outer, bg="#141416")
        denoise_row.pack(fill="x", pady=(0, 12))
        tk.Label(
            denoise_row, text="Redução de ruído", bg="#141416",
            fg="#e5e5ea", font=("Segoe UI", 9), anchor="w",
        ).pack(side="left")
        widget_ui.ModernToggle(
            denoise_row, denoise_var, bg="#141416", scale=s,
        ).pack(side="right")

        btns = tk.Frame(outer, bg="#141416")
        btns.pack(fill="x", pady=(2, 0))
        widget_ui.PillButton(
            btns, "Cancelar", lambda: self._close_settings(win),
            width=92, height=30, fill="#2c2c33", hover="#3a3a42",
            bg="#141416", scale=s,
        ).pack(side="right", padx=(8, 0))
        widget_ui.PillButton(
            btns, "Salvar",
            lambda: self._save_settings(
                win, silence_var, voice_var, denoise_var, language_var),
            width=92, height=30, fill="#0a84ff", hover="#2f9bff",
            bg="#141416", scale=s,
        ).pack(side="right")

        self.preview_peaks.clear()

        def cb(indata, frames, time_info, status):
            try:
                self.preview_peaks.append(float(np.abs(indata).max()))
            except Exception:
                pass

        try:
            import sounddevice as sd
            self.preview_stream = self._open_input(sd, cb)
            self.preview_stream.start()
        except Exception as exc:
            log(f"sem preview: {exc}")

        def tick_preview():
            if not self.settings_open or not win.winfo_exists():
                return
            peaks = list(self.preview_peaks)
            level = max(peaks) if peaks else 0.0
            w = pw * meter_pos(level)
            if level >= self._slider_to_level(voice_var.get()):
                fill = "#34c759"
            elif level >= self._slider_to_level(silence_var.get()):
                fill = "#ffd60a"
            else:
                fill = "#48484a"
            preview.itemconfig(pfill, fill=fill)
            preview.coords(pfill, 0, py, max(1, w), py)
            vx = pw * meter_pos(self._slider_to_level(voice_var.get()))
            sx = pw * meter_pos(self._slider_to_level(silence_var.get()))
            preview.coords(pmark_voice, vx, 0, vx, ph)
            preview.coords(pmark_sil, sx, 0, sx, ph)
            win.after(80, tick_preview)

        tick_preview()
        win.update_idletasks()
        ww = win.winfo_reqwidth()
        wh = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f"+{max(0, (sw - ww) // 2)}+{max(0, (sh - wh) // 2)}")
        win.grab_set()
        win.lift()

    def _save_settings(self, win, silence_var, voice_var, denoise_var,
                       language_var):
        self.cfg["silence"] = round(self._slider_to_level(silence_var.get()), 5)
        self.cfg["voice"] = round(self._slider_to_level(voice_var.get()), 5)
        self.cfg["denoise"] = bool(denoise_var.get())
        self.cfg["language"] = LANGUAGES.get(
            language_var.get(), LANGUAGE)
        if self.cfg["voice"] < self.cfg["silence"]:
            self.cfg["voice"] = self.cfg["silence"]
        save_cfg(self.cfg)
        self.view.set_thresholds(self.cfg["silence"], self.cfg["voice"])
        self.view.refresh_thresholds()
        log(f"config salva: silêncio={self.cfg['silence']}, "
            f"voz={self.cfg['voice']}, denoise={self.cfg['denoise']}, "
            f"idioma={self.cfg['language']}")
        self._close_settings(win)

    def _close_settings(self, win):
        if self.preview_stream is not None:
            try:
                self.preview_stream.stop()
                self.preview_stream.close()
            except Exception:
                pass
            self.preview_stream = None
        self.settings_open = False
        self.settings_win = None
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass

    def _patch_streaming_load(self):
        # IDEMPOTENTE: reaplicar sem restaurar EMPILHAVA o patch — o "orig"
        # salvo virava o lambda do patch anterior e o hf_hub_download entrava
        # em RECURSÃO INFINITA (CPU 100% e GPU parada) quando dois loads
        # começavam (ditado + reload do editor). Restaura antes de aplicar.
        self._restore_load()
        self._orig_from_pretrained = None
        self._orig_processor_from_pretrained = None
        self._orig_hf_hub_download = None
        self._orig_hub_cached_files = None
        try:
            import transformers

            def _load_cached(orig, *args, **kwargs):
                # usa apenas o cache local quando existir; evita contatar o
                # huggingface.co a cada inicio (que era a demora antes do
                # carregamento dos pesos). Se nao estiver em cache, baixa.
                try:
                    kwargs["local_files_only"] = True
                    return orig(*args, **kwargs)
                except Exception:
                    kwargs.pop("local_files_only", None)
                    return orig(*args, **kwargs)

            def _cached_files_wrapper(*args, **kwargs):
                try:
                    kwargs["local_files_only"] = True
                    return self._orig_hub_cached_files(*args, **kwargs)
                except Exception:
                    kwargs.pop("local_files_only", None)
                    # sondas de arquivos opcionais (processor_config.json,
                    # chat_template etc.) nao devem ir a internet; somente
                    # arquivos obrigatorios (1a vez sem cache) baixam
                    if not kwargs.get("_raise_exceptions_for_missing_entries", True):
                        return None
                    return self._orig_hub_cached_files(*args, **kwargs)

            self._orig_from_pretrained = \
                transformers.AutoModelForSpeechSeq2Seq.from_pretrained

            def patched(*args, **kwargs):
                kwargs.setdefault("device_map", "cuda")
                return _load_cached(self._orig_from_pretrained, *args, **kwargs)

            transformers.AutoModelForSpeechSeq2Seq.from_pretrained = patched

            self._orig_processor_from_pretrained = \
                transformers.AutoProcessor.from_pretrained
            transformers.AutoProcessor.from_pretrained = (
                lambda *a, **k: _load_cached(
                    self._orig_processor_from_pretrained, *a, **k)
            )

            # o transformers ignora local_files_only em alguns caminhos
            # internos; forcar no cached_files do modulo hub cobre todas
            self._orig_hub_cached_files = transformers.utils.hub.cached_files
            transformers.utils.hub.cached_files = _cached_files_wrapper

            # o crisperwhisper checa a versao do modelo baixando arquivos do
            # hub a cada inicio; forca cache local para nao avisar "unauthenticated"
            import huggingface_hub
            self._orig_hf_hub_download = huggingface_hub.hf_hub_download
            huggingface_hub.hf_hub_download = (
                lambda *a, **k: _load_cached(self._orig_hf_hub_download, *a, **k)
            )

            self._silence_noisy_loggers()
            log("streaming de pesos ativado (device_map=cuda, cache local)")
        except Exception as exc:
            log(f"falha patch device_map: {exc}")

    @staticmethod
    def _silence_noisy_loggers():
        # bibliotecas redefinem os niveis dos loggers no import (aviso de
        # "unauthenticated", "torch_dtype deprecated" etc.); filtro nao
        # depende do nivel e silencia tudo abaixo de ERROR
        class _NoBelowError(logging.Filter):
            def filter(self, record):
                return record.levelno >= logging.ERROR

        f = _NoBelowError()
        for name, lg in list(logging.Logger.manager.loggerDict.items()):
            if name.startswith(("transformers", "huggingface_hub")) \
                    and isinstance(lg, logging.Logger):
                lg.setLevel(logging.ERROR)
                lg.addFilter(f)

    def _restore_load(self):
        try:
            import transformers
            if self._orig_from_pretrained is not None:
                transformers.AutoModelForSpeechSeq2Seq.from_pretrained = \
                    self._orig_from_pretrained
            if self._orig_processor_from_pretrained is not None:
                transformers.AutoProcessor.from_pretrained = \
                    self._orig_processor_from_pretrained
            if self._orig_hub_cached_files is not None:
                transformers.utils.hub.cached_files = self._orig_hub_cached_files
            if self._orig_hf_hub_download is not None:
                import huggingface_hub
                huggingface_hub.hf_hub_download = self._orig_hf_hub_download
        except Exception:
            pass

    def _start_load_once(self):
        """Dispara a carga do modelo UMA vez (trava atômica): boot, botão de
        retry e o editor (reload pós-separação) podiam disparar DOIS loads ao
        mesmo tempo — dois modelos na GPU (pico/transbordo) e o patch de
        streaming empilhado (recursão infinita)."""
        with self._load_lock:
            if self.model is not None or self._model_loading or self.state == STATE_ERROR:
                return
            self._model_loading = True
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        try:
            from crisperwhisper import CrisperWhisperModel
        except Exception as exc:
            self.error_msg = f"crisperwhisper: {exc}"
            log(f"erro import: {exc}")
            self._ui(self._set_state, STATE_ERROR)
            return
        self._model_loading = True
        try:
            for attempt in range(1, 4):
                try:
                    log(f"carregando modelo (gpu, tentativa {attempt}/3)... "
                        f"pode levar alguns segundos")
                    self._patch_streaming_load()
                    # NOTA: NÃO tentar backend="ct2" aqui! O pacote aceita o
                    # nome sem checar disponibilidade e entra na CONVERSÃO do
                    # modelo (ensure_ct2_model) ANTES de falhar na checagem do
                    # fork — no Windows isso custava +60s por boot e um pico de
                    # memória que estourava a VRAM (o "transbordo misterioso").
                    # O fork do ct2 não tem build Windows; transformers direto.
                    self.model = CrisperWhisperModel(
                        MODEL_SIZE, backend="transformers",
                        device="cuda", compute_type="float16",
                    )
                    gc.collect()
                    self._trim_gpu_cache()
                    log(f"MODELO PRONTO (gpu, tentativa {attempt})")
                    try:
                        import psutil
                        log(f"ram do processo: "
                            f"{psutil.Process(os.getpid()).memory_info().rss / 1e9:.2f}GB")
                    except Exception:
                        pass
                    self._ui(self._model_ready)
                    return
                except Exception as exc:
                    self._restore_load()
                    self.model = None
                    log(f"gpu falhou (tentativa {attempt}/3): {str(exc)[:200]}")
                    if attempt < 3:
                        log("tentando novamente em 5s...")
                        self._ui(self._model_reloading)
                        time.sleep(5)
                        continue
                    # ultimo recurso: CPU
                    try:
                        log("carregando modelo em CPU (mais lento)...")
                        self.model = CrisperWhisperModel(
                            MODEL_SIZE, backend="transformers",
                            device="cpu", compute_type="float32",
                        )
                        self.rtf = 3.0
                        log("MODELO PRONTO (cpu)")
                        self._ui(self._model_ready)
                        return
                    except Exception as exc2:
                        self.error_msg = f"modelo: {str(exc2)[:200]}"
                        log(f"ERRO ao carregar modelo: {exc2}")
                        self._ui(self._set_state, STATE_ERROR)
                        return
        finally:
            self._model_loading = False

    def _model_reloading(self):
        # se o usuario ja comecou a gravar, nao tira o "gravando"
        if self.recording:
            return
        self._set_state(STATE_LOADING)

    def _retry_model(self):
        if self.model is not None:
            self._set_state(STATE_READY)
            return
        if self._model_loading:
            return
        self._set_state(STATE_LOADING)
        self._start_load_once()

    def _model_ready(self):
        # nao sobrescreve "gravando" se o usuario comecou a gravar durante a carga
        if self.recording:
            return
        self._set_state(STATE_READY)
        if not getattr(self, "_hint_shown", False):
            self._hint_shown = True
            log("PRONTO!")
            log("Como usar: Ctrl+Y para gravar/parar, ou clique na bolinha.")
            log("A transcricao e colada automaticamente no app em foco.")

    def _open_input(self, sd, callback):
        # Prefere WASAPI em modo compartilhado: permite que outros aplicativos
        # (navegador, chat gpt, etc.) usem o microfone ao mesmo tempo, sem
        # conflito. O backend MME trava o dispositivo e causava o fechamento.
        try:
            if not hasattr(sd, "WasapiSettings"):
                raise RuntimeError("sem WasapiSettings")
            hostapis = sd.query_hostapis()
            wasapi_idx = next(
                (i for i, h in enumerate(hostapis)
                 if "WASAPI" in h["name"].upper()),
                None,
            )
            if wasapi_idx is None:
                raise RuntimeError("hostapi WASAPI ausente")
            devs = sd.query_devices()
            default_in = sd.default.device[0]
            info = None
            if 0 <= default_in < len(devs):
                info = devs[default_in]
            device = None
            if info is not None and info["hostapi"] == wasapi_idx \
                    and info["max_input_channels"] > 0:
                device = default_in
            else:
                for i, d in enumerate(devs):
                    if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0 \
                            and (info is None or d["name"] == info["name"]):
                        device = i
                        break
            if device is None:
                raise RuntimeError("nenhum dispositivo de entrada WASAPI")
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                callback=callback, device=device,
                extra_settings=sd.WasapiSettings(exclusive=False, auto_convert=True),
            )
            log(f"stream WASAPI compartilhado (device={device})")
            return stream
        except Exception as exc:
            log(f"fallback stream default: {exc}")
            return sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                callback=callback,
            )

    def toggle(self):
        try:
            log(f"hotkey pressionado, state={self.state}, recording={self.recording}")
            if self.state == STATE_ERROR and not self.recording:
                # modelo falhou; tenta recarregar
                self._ui(self._retry_model)
                return
            if self.state in (STATE_ERROR, STATE_PROCESSING):
                return
            if self.recording:
                self.recording = False
                self.record_start = None
                self._ui(self._stop_recording)
            else:
                self._ui(self._start_recording)
        except Exception as exc:
            log(f"erro no toggle: {exc}")
            self._ui(self._set_state, STATE_ERROR)

    def _warm_recorder(self):
        proc = self._spawn_recorder()
        log("gravador externo: " + ("ativo" if proc else "indisponivel"))

    def _spawn_recorder(self):
        try:
            flags = 0x08000000 if sys.platform == "win32" else 0
            if FROZEN:
                recorder_exe = RECORDER_PATH
                if not os.path.isfile(recorder_exe):
                    log("gravador externo ausente no pacote; usando inline")
                    return None
                cmd = [recorder_exe]
            else:
                cmd = [sys.executable, RECORDER_PATH]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, creationflags=flags,
            )
        except Exception as exc:
            log(f"falha ao iniciar gravador externo: {exc}")
            return None
        self.recorder_proc = proc
        self._rec_done = threading.Event()
        threading.Thread(
            target=self._recorder_reader, args=(proc,), daemon=True).start()
        # erros do gravador externo iam para stderr oculto (invisivel);
        # agora sao registrados no dito.log
        threading.Thread(
            target=self._log_recorder_stderr, args=(proc,), daemon=True).start()
        return proc

    def _log_recorder_stderr(self, proc):
        try:
            for line in proc.stderr:
                text = line.decode(errors="replace").strip()
                if text:
                    log(f"gravador externo: {text}")
        except Exception:
            pass

    def _read_exact(self, out, n):
        data = bytearray()
        while len(data) < n:
            part = out.read(n - len(data))
            if not part:
                return None
            data.extend(part)
        return bytes(data)

    def _recorder_reader(self, proc):
        try:
            while True:
                hdr = self._read_exact(proc.stdout, 4)
                if hdr is None:
                    break
                (n,) = struct.unpack("<I", hdr)
                if n == 0xFFFFFFFF:
                    self._rec_done.set()
                    continue
                data = self._read_exact(proc.stdout, n)
                if data is None:
                    break
                self.recorder_chunks.append(data)
        except Exception:
            pass
        rc = proc.poll()
        log(f"gravador externo encerrou (rc={rc})")
        self._rec_done.set()

    def _start_recording(self):
        # roda na thread principal (Tk)
        self.buffer = []
        self.level_peaks.clear()
        self.record_start = time.time()
        self.view.set_waveform([0.02] * 36)

        proc = self.recorder_proc
        if proc is not None and proc.poll() is not None:
            proc = None
        if proc is None:
            proc = self._spawn_recorder()
        if proc is not None:
            self.recorder_chunks = []
            self._rec_done.clear()
            try:
                proc.stdin.write(b"start\n")
                proc.stdin.flush()
                self.recorder_mode = True
                self.recording = True
                self._set_state(STATE_RECORDING)
                self.view.set_sensitivity(self.sens_level, SENS_LEVELS, True)
                log(">>> GRAVANDO... (Ctrl+Y ou clique para parar)")
                return
            except Exception as exc:
                log(f"falha comando start no gravador: {exc}")
        self._start_inline()

    def _start_inline(self):
        # fallback: stream direto (mesmo processo); roda na thread principal
        import sounddevice as sd

        def callback(indata, frames, time_info, status):
            try:
                with self.buffer_lock:
                    self.buffer.append(indata.copy())
                    self.level_peaks.append(float(np.abs(indata).max()))
            except Exception:
                pass

        try:
            self.stream = self._open_input(sd, callback)
            try:
                self.stream.start()
            except Exception as exc:
                log(f"stream WASAPI falhou ao iniciar, usando default: {exc}")
                try:
                    self.stream.close()
                except Exception:
                    pass
                self.stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    callback=callback,
                )
                self.stream.start()
            self.recorder_mode = False
            self.recording = True
            self._set_state(STATE_RECORDING)
            self.view.set_sensitivity(self.sens_level, SENS_LEVELS, True)
            log(">>> GRAVANDO... (Ctrl+Y ou clique para parar)")
        except Exception as exc:
            self.recording = False
            self.error_msg = f"microfone: {str(exc)[:200]}"
            log(f"erro microfone: {exc}")
            self._set_state(STATE_READY, "mic ocupado?")

    def _denoise(self, audio):
        try:
            import noisereduce as nr
            t0 = time.time()
            out = nr.reduce_noise(
                y=audio, sr=SAMPLE_RATE,
                stationary=True,
                prop_decrease=0.35,
                n_std_thresh_stationary=2.0,
            )
            out = np.ascontiguousarray(out, dtype=np.float32)
            log(f"denoise: {time.time() - t0:.1f}s")
            return out
        except Exception as exc:
            log(f"falha denoise: {exc}")
            return audio

    def _vad_trim(self, audio, want_offset=False):
        # want_offset=True (só p/ o RPC com timestamps): devolve também
        # quantas amostras foram cortadas do INÍCIO — sem isso os tempos
        # das palavras ficam adiantados pelo silêncio removido.
        if audio.size == 0:
            return (audio, False, 0) if want_offset else (audio, False)
        env, n = audio_envelope(audio, frame=0.02, attack=0.5, release=0.04)
        # limiar adaptativo: ajusta-se ao volume real da gravacao
        p90 = float(np.percentile(env, 90))
        _, eff_voice = self._effective_thresholds()
        thr = max(eff_voice * 0.5, p90 * 0.25, 0.003)
        thr = min(thr, eff_voice * 1.5)
        active = env > thr
        if not active.any():
            return (audio, False, 0) if want_offset else (audio, False)
        idx = np.where(active)[0]
        # cauda: limiar mais baixo (50%) para nao perder fim de frase
        # falado mais baixo, com margem extra
        tail = env > thr * 0.5
        tail_idx = np.where(tail)[0]
        last = tail_idx[-1] if tail_idx.size and tail_idx[-1] > idx[-1] else idx[-1]
        pad = int(1.0 * SAMPLE_RATE)
        start = max(0, int(idx[0] * n) - pad)
        end = min(len(audio), int((last + 1) * n) + pad)
        if want_offset:
            return audio[start:end], True, start
        return audio[start:end], True

    def _stop_recording(self):
        # roda na thread principal (Tk) para fechar o stream com seguranca
        if self.recorder_mode:
            proc = self.recorder_proc
            try:
                proc.stdin.write(b"stop\n")
                proc.stdin.flush()
            except Exception:
                pass
            self._rec_done.wait(timeout=3.0)
            chunks = self.recorder_chunks
            self.recorder_chunks = []
            buf = b"".join(chunks)
            raw = np.frombuffer(buf, dtype=np.float32).copy() \
                if buf else np.zeros(0, dtype=np.float32)
            if proc.poll() is not None and proc.returncode not in (0, None):
                log(f"AVISO: gravador externo morreu durante a gravacao "
                    f"(rc={proc.returncode}); usando audio parcial")
                self._show_status("mic reinicia")
                self.recorder_proc = None
        else:
            if self.stream is not None:
                try:
                    self.stream.stop()
                except Exception:
                    pass
                try:
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
            with self.buffer_lock:
                ch = self.buffer
                self.buffer = []
                self.level_peaks.clear()
            raw = np.concatenate(ch) if ch else np.zeros(0, dtype=np.float32)
        raw = np.ascontiguousarray(raw.reshape(-1), dtype=np.float32)
        rms = float(np.sqrt((raw ** 2).mean())) if raw.size else 0.0
        peak = float(np.abs(raw).max()) if raw.size else 0.0
        self.last_rms = rms
        log(f"gravacao parada, {len(raw) / SAMPLE_RATE:.1f}s, "
            f"rms={rms:.4f}, peak={peak:.4f}")
        if rms < 0.005:
            log("ALERTA: audio quase silencioso - verifique ganho do microfone")
        log(">>> TRANSCREVENDO...")
        self._set_state(STATE_PROCESSING)
        self.view.set_sensitivity(self.sens_level, SENS_LEVELS, True)
        self.jobs.put(raw)

    def _trim_gpu_cache(self):
        try:
            import torch
            torch.cuda.empty_cache()
            log(f"vram apos limpeza: {torch.cuda.memory_reserved() / 1e9:.2f}GB reservados")
        except Exception:
            pass

    def _save_audio(self, audio):
        try:
            import soundfile as sf
            sf.write(LAST_AUDIO_PATH, audio, SAMPLE_RATE)
        except Exception as exc:
            log(f"falha salvar audio: {exc}")

    def _job_loop(self):
        while True:
            audio = self.jobs.get()
            if audio is None:
                return
            try:
                self._process_job(audio)
            except Exception as exc:
                log(f"ERRO no processamento: {exc}")
                self._ui(self._set_state, STATE_READY, "erro interno")

    def _chunk_audio(self, audio):
        sr = SAMPLE_RATE
        if len(audio) <= 30 * sr:
            return [audio]
        min_len = int(25.0 * sr)
        max_len = int(30.0 * sr)
        overlap = int(0.4 * sr)
        min_last = int(6.0 * sr)
        cuts = []
        start = 0
        total = len(audio)
        while total - start > max_len:
            hi = start + max_len
            env, frame = audio_envelope(
                audio[start:hi], frame=0.05, attack=0.4, release=0.05,
            )
            lo = start + min_len
            hi_cap = start + max_len - overlap
            i_lo = int((lo - start) / frame)
            i_hi = max(i_lo + 1, int((hi_cap - start) / frame))
            cut = start + int(np.argmin(env[i_lo:i_hi]) + i_lo) * frame
            cut = max(lo, min(hi_cap, cut))
            cuts.append(cut)
            start = cut - overlap
        # ultimo chunk pequeno demais? move o ultimo corte para tras
        if cuts and total - start < min_last:
            need = min_last - (total - start)
            last_cut = cuts[-1]
            new_cut = max(last_cut - need, int(20.0 * sr))
            if new_cut < last_cut:
                cuts[-1] = new_cut
                start = new_cut - overlap
        chunks = []
        prev_cut = 0
        for c in cuts:
            chunks.append(audio[prev_cut:c + overlap])
            prev_cut = c - overlap
        chunks.append(audio[max(0, prev_cut):])
        return chunks

    def _join_chunk_texts(self, texts):
        out = ""
        for raw in texts:
            t = raw.strip()
            if not t:
                continue
            if out:
                ow = out.split()
                tw = t.split()
                on_last = ow[-1].strip(".,!?;:'\"")
                tw_first = tw[0].strip(".,!?;:'\"")
                # palavra truncada na costura: "proje-" + "projeto" -> "projeto"
                if on_last.endswith("-") and len(on_last) > 1:
                    core = on_last[:-1]
                    if len(core) >= 3 and tw_first.startswith(core):
                        out = " ".join(ow[:-1])
                elif tw_first.startswith("-"):
                    core = tw_first.lstrip("-")
                    if len(core) >= 3 and on_last.endswith(core):
                        t = " ".join(tw[1:])
                norm = lambda w: w.strip(".,!?;:\"'-").lower()
                wp = out.split()
                wt = t.split()
                k = 0
                for n in range(min(len(wp), len(wt), 5), 0, -1):
                    if [norm(w) for w in wp[-n:]] == [norm(w) for w in wt[:n]]:
                        k = n
                        break
                if k:
                    t = " ".join(wt[k:])
                if not t:
                    continue
                if out.endswith(".") and not out.endswith(".."):
                    out = out[:-1] + ", " + (t[:1].lower() + t[1:] if t[0].isupper() else t)
                else:
                    out = f"{out} {t}"
            else:
                out = t
        if out and out[-1] not in ".!?":
            out += "."
        return out

    def _process_job(self, audio):
        if self.cfg.get("denoise", True):
            audio = self._denoise(audio)
        try:
            audio = audio_fx.normalize_audio(
                audio, SAMPLE_RATE,
                sensitivity_db=self._gate_sensitivity_db(),
                strength="suave",
                logger=log,
            )
        except Exception as exc:
            log(f"normalizacao falhou; seguindo com audio sem normalizar: {exc}")
        total = len(audio)
        audio, had_voice = self._vad_trim(audio)
        if not had_voice:
            log("sem voz detectada (nivel abaixo de 'voz')")
            self._save_audio(audio)
            self._ui(self._set_state, STATE_READY, "sem voz")
            return
        log(f"trecho util: {len(audio) / SAMPLE_RATE:.1f}s "
            f"(de {total / SAMPLE_RATE:.1f}s)")
        if len(audio) < SAMPLE_RATE * 0.3:
            log("audio muito curto, ignorado")
            self._ui(self._set_state, STATE_READY)
            return
        # aguarda o modelo terminar de carregar, caso a gravacao tenha
        # comecado durante o load (agora o ctrl+y ja funciona nesse periodo)
        t_wait = time.time()
        while self.model is None and self.state != STATE_ERROR:
            if time.time() - t_wait > 600:
                self._ui(self._set_state, STATE_READY, "sem modelo")
                return
            time.sleep(0.5)
        if self.model is None:
            self._ui(self._set_state, STATE_READY, "sem modelo")
            return
        chunks = self._chunk_audio(audio)
        texts = []
        try:
            self._progress_start = time.time()
            self._progress_dur = max(
                1.0, len(audio) / SAMPLE_RATE * self.rtf
                + 1.2 + 1.5 * (len(chunks) - 1),
            )
            self._ui(self._tick_progress)
            for i, chunk in enumerate(chunks, 1):
                peak = float(np.abs(chunk).max()) if chunk.size else 0.0
                boosted = chunk
                if chunk.size and 0 < peak < 0.5:
                    gain = min(6.0, 0.5 / peak)
                    boosted = (chunk * gain).astype(np.float32)
                    log(f"ganho aplicado: x{gain:.2f} (peak={peak:.3f})")
                with self.gpu_lock:
                    result = self.model.transcribe(
                        boosted, language=self._language(), mode="intended",
                        sr=SAMPLE_RATE,
                    )
                texts.append(result.text.strip())
                self._trim_gpu_cache()
                if len(chunks) > 1:
                    frac = i / len(chunks)
                    el = time.time() - self._progress_start
                    if frac > 0:
                        self._progress_dur = el / frac
                    log(f"chunk {i}/{len(chunks)} ok "
                        f"({len(boosted) / SAMPLE_RATE:.1f}s, "
                        f"{len(texts[-1])} chars)")
            proc = time.time() - self._progress_start
            if proc > 0.5 and len(audio) > SAMPLE_RATE * 2:
                cur = proc / (len(audio) / SAMPLE_RATE)
                self.rtf = self.rtf * 0.7 + cur * 0.3
                log(f"rtf atual: {cur:.3f}")
        except Exception as exc:
            self.error_msg = f"transcrever: {str(exc)[:200]}"
            log(f"erro transcrever: {exc}")
            self._ui(self._set_state, STATE_ERROR)
            return
        finally:
            self._trim_gpu_cache()
        text = self._join_chunk_texts(texts)
        log(f"transcricao: {text!r}")
        if not text:
            self._save_audio(audio)
            if self.last_rms < 0.02:
                self._ui(self._set_state, STATE_READY, "mic baixo?")
            else:
                self._ui(self._set_state, STATE_READY, "nada entendido")
            return
        self.last_text = text
        self._paste(text)

    def _rpc_cfg(self):
        try:
            with open(RPC_CFG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("token"):
                return int(data.get("port", RPC_DEFAULT_PORT)), str(data["token"])
        except Exception:
            pass
        import secrets
        data = {"port": RPC_DEFAULT_PORT, "token": secrets.token_hex(16)}
        try:
            with open(RPC_CFG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            log(f"falha salvar dito_rpc.json: {exc}")
        return int(data["port"]), data["token"]

    def _transcribe_audio(self, audio, idioma=None):
        # nucleo da transcricao para uso externo (LoreStudio): mesmo pipeline
        # do ditado (denoise, vad, chunks, ganho), sem colar em janela
        lang = (idioma or self._language())
        if self.cfg.get("denoise", True):
            audio = self._denoise(audio)
        audio, had_voice = self._vad_trim(audio)
        if not had_voice:
            return None
        if len(audio) < SAMPLE_RATE * 0.3:
            return None
        t_wait = time.time()
        while self.model is None and self.state != STATE_ERROR:
            if time.time() - t_wait > 600:
                return None
            time.sleep(0.5)
        if self.model is None:
            return None
        chunks = self._chunk_audio(audio)
        texts = []
        for chunk in chunks:
            peak = float(np.abs(chunk).max()) if chunk.size else 0.0
            boosted = chunk
            if chunk.size and 0 < peak < 0.5:
                gain = min(6.0, 0.5 / peak)
                boosted = (chunk * gain).astype(np.float32)
            with self.gpu_lock:
                result = self.model.transcribe(
                    boosted, language=lang, mode="intended", sr=SAMPLE_RATE,
                )
            texts.append(result.text.strip())
            self._trim_gpu_cache()
        return self._join_chunk_texts(texts)

    def _transcribe_audio_ts(self, audio, idioma=None):
        # Variante para o APEXEDIT (roteiro de dublagem): mesma preprocessagem
        # do _transcribe_audio (denoise/vad/ganho), mas com word_timestamps.
        # Divide em blocos de ~5min SEM overlap (limita VRAM; offsets triviais
        # somando o inicio do bloco). Dentro do bloco o modelo faz o longform.
        # Retorna (texto, palavras[{w,s,e}]).
        lang = (idioma or self._language())
        if self.cfg.get("denoise", True):
            audio = self._denoise(audio)
        audio, had_voice, trim_off = self._vad_trim(audio, want_offset=True)
        if not had_voice:
            return None
        if len(audio) < SAMPLE_RATE * 0.3:
            return None
        t_wait = time.time()
        while self.model is None and self.state != STATE_ERROR:
            if time.time() - t_wait > 600:
                return None
            time.sleep(0.5)
        if self.model is None:
            return None
        block = 90 * SAMPLE_RATE  # 90s: progresso mais fino (25% p/ 6min) e
        # o editor CEDE A VEZ entre blocos — o ditado do usuário nunca fica
        # preso atrás da rodada inteira, só atrás do bloco atual.
        textos = []
        palavras = []
        offset = 0
        n_blocks = max(1, (len(audio) + block - 1) // block)
        # Progresso vivo p/ o APEXEDIT (lido no /saude enquanto o POST roda).
        self.rpc_progresso = {"done": 0, "total": n_blocks}
        try:
            for i in range(0, len(audio), block):
                # Se outra transcrição (ditado do usuário) estiver com o lock,
                # espera ela terminar antes de pegar o próximo bloco.
                t_yield = time.time()
                while self.gpu_lock.locked() and time.time() - t_yield < 120:
                    time.sleep(0.3)
                chunk = audio[i:i + block]
                peak = float(np.abs(chunk).max()) if chunk.size else 0.0
                boosted = chunk
                if chunk.size and 0 < peak < 0.5:
                    gain = min(6.0, 0.5 / peak)
                    boosted = (chunk * gain).astype(np.float32)
                with self.gpu_lock:
                    result = self.model.transcribe(
                        boosted, language=lang, mode="verbatim", sr=SAMPLE_RATE,
                        word_timestamps=True,
                    )
                self._trim_gpu_cache()
                textos.append(result.text.strip())
                for w in (getattr(result, "words", None) or []):
                    try:
                        palavras.append({
                            "w": str(w.word),
                            "s": float(w.start) + (offset + trim_off) / SAMPLE_RATE,
                            "e": float(w.end) + (offset + trim_off) / SAMPLE_RATE,
                        })
                    except Exception:
                        pass
                offset += len(chunk)
                self.rpc_progresso = {"done": min(i // block + 1, n_blocks), "total": n_blocks}
        finally:
            self.rpc_progresso = None
        return self._join_chunk_texts(textos), palavras

    def _transcribe_audio_fast(self, audio, idioma=None):
        # MODO RÁPIDO (editor): sem word_timestamps — a passada extra de
        # alinhamento (teacher-forced) era o grosso do custo. Fatia o áudio
        # nas PAUSAS (2–12s por frase, corte no silêncio) e transcreve cada
        # fatia com texto LIMPO (intended). Tempos das frases = exatos (as
        # fatias são nossas); sem karaokê por palavra.
        # Retorna (texto, palavras[], segmentos[{s,e,texto}]).
        lang = (idioma or self._language())
        if self.cfg.get("denoise", True):
            audio = self._denoise(audio)
        audio, had_voice, trim_off = self._vad_trim(audio, want_offset=True)
        if not had_voice:
            return None
        if len(audio) < SAMPLE_RATE * 0.3:
            return None
        t_wait = time.time()
        while self.model is None and self.state != STATE_ERROR:
            if time.time() - t_wait > 600:
                return None
            time.sleep(0.5)
        if self.model is None:
            return None

        # Fatias nas pausas (mesma envelope do VAD)
        env, n = audio_envelope(audio, frame=0.02, attack=0.5, release=0.04)
        thr = max(0.004, float(np.percentile(env, 90)) * 0.12)
        active = env > thr
        MIN_S = int(2.0 * SAMPLE_RATE)
        MAX_S = int(12.0 * SAMPLE_RATE)
        gap_frames = max(1, int(0.30 / n))
        slices = []
        cur_start = 0
        i = 0
        N = len(active)
        while i < N:
            if not active[i]:
                j = i
                while j < N and not active[j]:
                    j += 1
                if (j - i) >= gap_frames and (i * n - cur_start) >= MIN_S:
                    slices.append((cur_start, i * n))
                    cur_start = j * n
                i = j
            else:
                if (i * n - cur_start) >= MAX_S:
                    slices.append((cur_start, i * n))
                    cur_start = i * n
                i += 1
        if len(audio) - cur_start > SAMPLE_RATE * 0.2:
            slices.append((cur_start, len(audio)))
        if not slices:
            slices = [(0, len(audio))]

        n_sl = len(slices)
        self.rpc_progresso = {"done": 0, "total": n_sl}
        textos = []
        segmentos = []
        try:
            for k, (a, b) in enumerate(slices):
                # Cede a vez pro ditado do usuário entre fatias (mesma regra
                # do caminho completo).
                t_yield = time.time()
                while self.gpu_lock.locked() and time.time() - t_yield < 120:
                    time.sleep(0.3)
                chunk = audio[a:b]
                peak = float(np.abs(chunk).max()) if chunk.size else 0.0
                boosted = chunk
                if chunk.size and 0 < peak < 0.5:
                    gain = min(6.0, 0.5 / peak)
                    boosted = (chunk * gain).astype(np.float32)
                with self.gpu_lock:
                    result = self.model.transcribe(
                        boosted, language=lang, mode="intended", sr=SAMPLE_RATE,
                    )
                self._trim_gpu_cache()
                txt = (result.text or "").strip()
                if txt:
                    segmentos.append({
                        "s": round((a + trim_off) / SAMPLE_RATE, 3),
                        "e": round((b + trim_off) / SAMPLE_RATE, 3),
                        "texto": txt,
                    })
                    textos.append(txt)
                self.rpc_progresso = {"done": k + 1, "total": n_sl}
        finally:
            self.rpc_progresso = None
        return self._join_chunk_texts(textos), [], segmentos

    def _modelo_cmd(self, acao: str) -> dict:
        """Descarga/recarrega o modelo a pedido do editor (separação UVR
        precisa da VRAM inteira; com o modelo carregado a GPU transborda pra
        memória compartilhada e a separação fica MUITO mais lenta)."""
        acao = (acao or "").strip().lower()
        if acao == "descarregar":
            if self.model is not None:
                try:
                    self.gpu_lock.acquire()
                    self.model = None
                    gc.collect()
                    self._trim_gpu_cache()
                finally:
                    try:
                        self.gpu_lock.release()
                    except Exception:
                        pass
                log("modelo DESCARREGADO a pedido do editor — VRAM liberada")
            return {"ok": True, "pronto": False, "estado": self.state}
        if acao == "carregar":
            if self.model is None and not self._model_loading and self.state != STATE_ERROR:
                log("recarregando modelo (pedido do editor)...")
                self._ui(self._set_state, STATE_LOADING)
                self._start_load_once()
            return {"ok": True, "pronto": self.model is not None, "estado": self.state}
        return {"ok": False, "erro": "acao desconhecida"}

    def _start_rpc(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        port, token = self._rpc_cfg()
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.split("?")[0] != "/saude":
                    return self._send(404, {"erro": "rota desconhecida"})
                self._send(200, {
                    "ok": True,
                    "estado": app.state,
                    "modelo": f"crisperwhisper-{MODEL_SIZE}",
                    "pronto": app.model is not None,
                    "carregando": app._model_loading,
                    "rpc_ts": True,
                    "progresso": getattr(app, "rpc_progresso", None),
                })

            def do_POST(self):
                if self.path.split("?")[0] == "/modelo":
                    if self.headers.get("X-Token") != token:
                        return self._send(401, {"erro": "token invalido"})
                    try:
                        n = int(self.headers.get("Content-Length", "0"))
                        req = json.loads(self.rfile.read(n) or b"{}")
                    except Exception as exc:
                        return self._send(400, {"erro": f"json invalido: {exc}"})
                    return self._send(200, app._modelo_cmd(str(req.get("acao") or "")))
                if self.path.split("?")[0] != "/transcrever":
                    return self._send(404, {"erro": "rota desconhecida"})
                if self.headers.get("X-Token") != token:
                    return self._send(401, {"erro": "token invalido"})
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    req = json.loads(self.rfile.read(n) or b"{}")
                except Exception as exc:
                    return self._send(400, {"erro": f"json invalido: {exc}"})
                caminho = req.get("caminho") or ""
                if not caminho or not os.path.isfile(caminho):
                    return self._send(400, {"erro": "arquivo nao encontrado"})
                if app.model is None:
                    return self._send(503, {"erro": "modelo carregando"})
                try:
                    import soundfile as sf
                    audio, sr = sf.read(caminho, dtype="float32", always_2d=True)
                    audio = np.ascontiguousarray(audio.mean(axis=1), dtype=np.float32)
                    if sr != SAMPLE_RATE:
                        return self._send(400, {"erro": f"wav precisa ser {SAMPLE_RATE}Hz"})
                    idioma = str(req.get("idioma") or "").strip()[:5] or None
                    log(f"rpc: transcrevendo {os.path.basename(caminho)} "
                        f"({len(audio) / SAMPLE_RATE:.1f}s, "
                        f"idioma={idioma or self._language()}"
                        f"{', timestamps' if req.get('timestamps') else ''})")
                    if req.get("timestamps"):
                        if req.get("words") is False:
                            # MODO RÁPIDO: frases por pausa, sem karaokê
                            r = app._transcribe_audio_fast(audio, idioma=idioma)
                            if r is None:
                                return self._send(200, {"texto": "", "aviso": "sem voz detectada"})
                            texto, _, segmentos = r
                            log(f"rpc ok (fast): {len(texto)} chars, {len(segmentos)} frases")
                            return self._send(200, {"texto": texto, "palavras": [], "segmentos": segmentos})
                        r = app._transcribe_audio_ts(audio, idioma=idioma)
                        if r is None:
                            return self._send(200, {"texto": "", "aviso": "sem voz detectada"})
                        texto, palavras = r
                        log(f"rpc ok (ts): {len(texto)} chars, {len(palavras)} palavras")
                        return self._send(200, {"texto": texto, "palavras": palavras})
                    texto = app._transcribe_audio(audio, idioma=idioma)
                    if texto is None:
                        return self._send(200, {"texto": "", "aviso": "sem voz detectada"})
                    log(f"rpc ok: {len(texto)} chars")
                    self._send(200, {"texto": texto})
                except Exception as exc:
                    log(f"rpc erro: {exc}")
                    self._send(500, {"erro": str(exc)[:200]})

        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            server.daemon_threads = True
            log(f"api local de transcricao: http://127.0.0.1:{port} "
                f"(token em dito_rpc.json)")
            server.serve_forever()
        except Exception as exc:
            log(f"falha api local: {exc}")

    def _foreground_target(self):
        user32 = ctypes.windll.user32
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd or self._is_own_hwnd(hwnd):
                return 0
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(int(hwnd), cls, 64)
            if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
                return 0
            return int(hwnd)
        except Exception:
            return 0

    def on_copy(self):
        text = self.last_text or ""
        if text and self._copy_clipboard(text):
            self._show_status("copiado")
        else:
            self._show_status("nada para copiar")

    def _window_title(self, hwnd):
        try:
            title = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(int(hwnd), title, 256)
            return title.value or "(sem titulo)"
        except Exception:
            return "(desconhecida)"

    def _focused_child(self, hwnd):
        try:
            user32 = ctypes.windll.user32
            tid = user32.GetWindowThreadProcessId(int(hwnd), None)
            gui = GUITHREADINFO()
            gui.cbSize = ctypes.sizeof(gui)
            if user32.GetGUIThreadInfo(tid, ctypes.byref(gui)) and gui.hwndFocus:
                return int(gui.hwndFocus)
        except Exception:
            pass
        return int(hwnd)

    def _copy_clipboard(self, text):
        # outro programa pode estar segurando o clipboard (o pyperclip
        # desiste em 0.5s); tenta de novo por alguns segundos
        import pyperclip
        last = None
        for _ in range(4):
            try:
                pyperclip.copy(text)
                return True
            except Exception as exc:
                last = exc
                time.sleep(0.3)
        log(f"falha clipboard: {last}")
        return False

    def _paste(self, text):
        copied = self._copy_clipboard(text)
        hwnd = self._foreground_target()
        if hwnd:
            log(f"colando em: {self._window_title(hwnd)}")
        else:
            log("sem janela externa em foco; texto mantido no clipboard")
        pasted = False
        if copied and hwnd:
            try:
                import keyboard
                keyboard.send("ctrl+v")
                pasted = True
                log("colado (ctrl+v, sem trocar de janela)")
            except Exception as exc:
                log(f"falha colar: {exc}")
        if copied and not pasted and hwnd:
            try:
                focus = self._focused_child(hwnd)
                ctypes.windll.user32.PostMessageW(focus, WM_PASTE, 0, 0)
                pasted = True
                log("colado (WM_PASTE)")
            except Exception as exc:
                log(f"falha WM_PASTE: {exc}")
        if not copied and hwnd:
            # clipboard travado: digita direto no app em foco
            try:
                import keyboard
                keyboard.write(text, delay=0.001)
                pasted = True
                log("digitado (clipboard ocupado)")
            except Exception as exc:
                log(f"falha digitar: {exc}")
        if pasted:
            snippet = " ".join(text.split())
            if len(snippet) > 28:
                snippet = snippet[:28].rstrip() + "..."
            self._ui(self._set_state, STATE_READY, snippet)
        elif copied:
            self._ui(self._set_state, STATE_READY, "copiado")
        else:
            log("NAO conseguiu colar - use o botao copiar")
            self._ui(self._set_state, STATE_READY, "sem colagem")

    def on_close(self):
        log("fechando app")
        self.ui_queue.close()
        try:
            self._stop_splash(show_view=False)
        except Exception:
            pass
        if self._hotkey_stop is not None:
            self._hotkey_stop.set()
        try:
            if self._hotkey_tid:
                ctypes.windll.user32.PostThreadMessageW(
                    self._hotkey_tid, WM_QUIT, 0, 0)
        except Exception:
            pass
        for stream in (self.stream, self.preview_stream):
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
        proc = self.recorder_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.write(b"quit\n")
                proc.stdin.flush()
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.jobs.put(None)
        try:
            if self.settings_win is not None:
                self._close_settings(self.settings_win)
        except Exception:
            pass
        try:
            if self.view is not None:
                self.view.shutdown()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _report_callback_exception(self, exc_type, exc, tb):
        import traceback
        log(f"EXCECAO EM CALLBACK TK: {exc_type.__name__}: {exc}")
        log("".join(traceback.format_exception(exc_type, exc, tb)))

    def _install_error_hooks(self):
        def hook(exc_type, exc, tb):
            import traceback
            log("EXCECAO NAO TRATADA (main): "
                f"{exc_type.__name__}: {exc}")
            log("".join(traceback.format_exception(exc_type, exc, tb)))

        def thook(args):
            import traceback
            log(f"EXCECAO EM THREAD: {args.exc_type.__name__}: {args.exc_value}")
            log("".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback)))

        sys.excepthook = hook
        threading.excepthook = thook


_SINGLE_MUTEX = None


def _other_dito_process():
    """Detecta uma instancia antiga que ainda nao tem o mutex novo.

    Ignora os processos ancestrais. O launcher do venv no Windows aparece
    como pythonw.exe com o mesmo dito.py na linha de comando e seria
    confundido com uma segunda instancia.
    """
    try:
        import psutil
    except Exception:
        return False
    me = os.getpid()
    ancestors = {os.getppid()}
    try:
        ancestors.update(p.pid for p in psutil.Process(me).parents())
    except Exception:
        pass
    nomes = {"python.exe", "pythonw.exe", "py.exe", "pyw.exe", "dito.exe"}
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = proc.info.get("pid")
                if pid == me or pid in ancestors:
                    continue
                nome = str(proc.info.get("name") or "").lower()
                if nome not in nomes:
                    continue
                cmd = proc.info.get("cmdline") or []
                low = [str(part).lower() for part in cmd]
                if any(part.endswith(("dito.py", "dito.exe"))
                       for part in low):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _show_already_open():
    ctypes.windll.user32.MessageBoxW(
        None,
        "O Dito ja esta aberto.\n\n"
        "Procure a pilula no canto da tela.",
        "Dito", 0x40 | 0x40000)


def _single_instance_guard():
    """Impede duas instancias do Dito (duas GPUs/hotkeys iguais)."""
    global _SINGLE_MUTEX
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(
            None, False, "Local\\DitoSingleInstance_v1")
        if not handle:
            return True
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            _show_already_open()
            return False
        if _other_dito_process():
            _show_already_open()
            return False
        _SINGLE_MUTEX = handle
        return True
    except Exception:
        # se o Windows recusar o mutex, nao impede o app de abrir
        return True


def main():
    if not _single_instance_guard():
        return
    try:
        import faulthandler
        faulthandler.enable(
            open(LOG_PATH, "a", encoding="utf-8"))
    except Exception:
        pass
    print("===== DITO =====", flush=True)
    print("Iniciando... carregando modelo (na 1a vez pode demorar/baixar).", flush=True)
    widget_ui.enable_dpi_awareness()
    root = tk.Tk()
    try:
        root.iconbitmap(ICON_PATH)
    except Exception:
        pass
    root.withdraw()
    widget_ui.configure_tk_scaling(root, widget_ui.system_scale())
    app = DitoApp(root)
    app._install_error_hooks()
    root.mainloop()


if __name__ == "__main__":
    main()
