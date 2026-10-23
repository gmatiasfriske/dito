"""Interface do Dictado.

O widget principal e desenhado com Pillow e exibido numa janela nativa
layered (alpha por pixel), sem depender das limitacoes de desenho do Tk.
O Tk continua sendo usado para o painel de niveis e pelos controles da
interface classica de emergencia.
"""

import ctypes
import ctypes.wintypes as wt
import math
import os
import queue
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import tkinter as tk


DEFAULT_UI_SCALE = 0.80

LOGICAL_W = 224
LOGICAL_H = 112
CONTENT_H = 58
IDLE_W = 58
EXPANDED_W = 178
PAD = 14
TOOLBAR_W = 96
TOOLBAR_H = 24
TOOLBAR_GAP = 6
MARGIN_X = 8
EXTRA_Y = 15

STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_RECORDING = "recording"
STATE_PROCESSING = "processing"
STATE_ERROR = "error"

ACCENTS = {
    STATE_LOADING: (142, 142, 147),
    STATE_READY: (52, 199, 89),
    STATE_RECORDING: (255, 69, 58),
    STATE_PROCESSING: (255, 159, 10),
    STATE_ERROR: (255, 105, 97),
}

TEXTS = {
    STATE_LOADING: "carregando",
    STATE_READY: "pronto",
    STATE_RECORDING: "gravando",
    STATE_PROCESSING: "proc...",
    STATE_ERROR: "erro",
}

COLORS = {
    STATE_LOADING: "#4a4a4a",
    STATE_READY: "#1e8a3c",
    STATE_RECORDING: "#c62828",
    STATE_PROCESSING: "#e07b00",
    STATE_ERROR: "#7a5c10",
}

MAGENTA = "#ff00ff"

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_SETCURSOR = 0x0020
WM_MOUSEACTIVATE = 0x0021
WM_NCHITTEST = 0x0084
WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL = 0x020A
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_CAPTURECHANGED = 0x0215
WM_QUIT = 0x0012
WH_MOUSE_LL = 14

HTTRANSPARENT = -1
HTCLIENT = 1
MA_NOACTIVATE = 3

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
GWL_EXSTYLE = -20

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 2
SPI_GETWORKAREA = 0x0030
SM_CXSCREEN = 0
SM_CYSCREEN = 1
LOGPIXELSX = 88
PM_REMOVE = 0x0001

HWND_TOPMOST = ctypes.c_void_p(-1)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetCursorPos.restype = wt.BOOL
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.ValidateRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.ValidateRect.restype = wt.BOOL
user32.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wt.HANDLE
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SystemParametersInfoW.argtypes = [
    wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT,
]
user32.SystemParametersInfoW.restype = wt.BOOL
user32.SetCapture.argtypes = [wt.HWND]
user32.SetCapture.restype = wt.HWND
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wt.BOOL
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]
gdi32.GetDeviceCaps.restype = ctypes.c_int


def _log_none(msg):
    pass


def enable_dpi_awareness():
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wt.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def system_scale():
    try:
        user32.GetDpiForSystem.restype = wt.UINT
        dpi = int(user32.GetDpiForSystem())
        if dpi > 0:
            return max(1.0, dpi / 96.0)
    except Exception:
        pass
    try:
        hdc = user32.GetDC(None)
        dpi = int(gdi32.GetDeviceCaps(hdc, LOGPIXELSX))
        user32.ReleaseDC(None, hdc)
        if dpi > 0:
            return max(1.0, dpi / 96.0)
    except Exception:
        pass
    return 1.0


def configure_tk_scaling(root, scale):
    try:
        root.tk.call("tk", "scaling", (96.0 / 72.0) * float(scale))
    except Exception:
        pass


def _font_path(weight):
    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if weight == "semibold":
        names = ("seguisb.ttf", "segoeuib.ttf")
    elif weight == "bold":
        names = ("segoeuib.ttf", "seguisb.ttf")
    else:
        names = ("segoeui.ttf", "segoeuisl.ttf")
    for name in names:
        path = os.path.join(fonts, name)
        if os.path.isfile(path):
            return path
    return None


_FONT_CACHE = {}


def _font(size, weight="regular"):
    key = (max(1, int(round(size))), weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = _font_path(weight)
    try:
        if path:
            f = ImageFont.truetype(path, size=key[0])
        else:
            f = ImageFont.load_default(size=key[0])
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _mix(a, b, t):
    t = _clamp(t, 0.0, 1.0)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(4))


def _alpha(img, opacity):
    if opacity >= 0.999:
        return img
    a = img.getchannel("A").point(lambda v: int(v * opacity))
    img.putalpha(a)
    return img


def _truncate(draw, text, font, max_w):
    if max_w <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "..."
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid] + ell, font=font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ell


def _round_line(draw, p1, p2, width, fill):
    draw.line([p1, p2], fill=fill, width=max(1, int(round(width))))
    r = width / 2.0
    for x, y in (p1, p2):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)


class Renderer:
    def __init__(self, scale=1.0, supersample=3):
        self.scale = float(scale)
        if self.scale >= 1.5 and int(supersample) == 3:
            supersample = 2
        self.ss = int(supersample)
        self.u = self.scale * self.ss
        self.W = max(1, int(round(LOGICAL_W * self.scale)))
        self.H = max(1, int(round(LOGICAL_H * self.scale)))

    def _px(self, v):
        return v * self.u

    def render(
        self,
        state=STATE_LOADING,
        width=IDLE_W,
        timer="",
        progress=None,
        status="",
        bars=None,
        hover=0.0,
        hover_btn=None,
        spinner=0.0,
        pulse=0.0,
        sens_level=4,
        sens_levels=7,
        sens_visible=False,
    ):
        u = self.u
        W = int(round(LOGICAL_W * u))
        H = int(round(LOGICAL_H * u))
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        width = _clamp(float(width), IDLE_W, EXPANDED_W)
        cw = width
        ch = CONTENT_H
        cx2 = LOGICAL_W - PAD
        cy2 = LOGICAL_H - PAD
        cx1 = cx2 - cw
        cy1 = cy2 - ch
        accent = ACCENTS.get(state, ACCENTS[STATE_READY])

        x1, y1 = self._px(cx1), self._px(cy1)
        x2, y2 = self._px(cx2), self._px(cy2)
        r = self._px(ch / 2.0)

        grad = Image.new("RGBA", (1, max(1, int(round(ch)))), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        top = (40, 40, 46, 240)
        bottom = (16, 16, 20, 246)
        for yy in range(grad.height):
            t = yy / max(1, grad.height - 1)
            gd.point((0, yy), fill=_mix(top, bottom, t))
        grad = grad.resize((max(1, int(x2 - x1)), max(1, int(y2 - y1))),
                           Image.Resampling.BILINEAR)
        mask = Image.new("L", grad.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, grad.width - 1, grad.height - 1],
            radius=max(1, int(r)), fill=255,
        )
        base.paste(grad, (int(x1), int(y1)), mask)

        d = ImageDraw.Draw(base)
        d.rounded_rectangle(
            [x1 + 0.5, y1 + 0.5, x2 - 0.5, y2 - 0.5],
            radius=r, outline=(255, 255, 255, 30),
            width=max(1, int(round(1.0 * u))),
        )
        d.rounded_rectangle(
            [x1 + 1.5 * u, y1 + 1.5 * u, x2 - 1.5 * u, y2 - 4.0 * u],
            radius=max(1, int(r - 2 * u)),
            outline=(255, 255, 255, 12),
            width=max(1, int(round(1.0 * u))),
        )

        idle = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        expanded = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        idle_a = _clamp((108.0 - width) / 24.0, 0.0, 1.0)
        exp_a = _clamp((width - 84.0) / 24.0, 0.0, 1.0)

        if idle_a > 0.001:
            self._draw_idle(idle, state, accent, cx1, cx2, cy1, cy2,
                            spinner, pulse)
            _alpha(idle, idle_a)
            base.alpha_composite(idle)

        if exp_a > 0.001:
            self._draw_expanded(
                expanded, state, accent, cx1, cx2, cy1, cy2,
                timer, progress, status, bars or [], pulse,
                sens_level, sens_levels, sens_visible,
            )
            _alpha(expanded, exp_a)
            base.alpha_composite(expanded)

        if hover > 0.01 and state != STATE_LOADING:
            tb = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            self._draw_toolbar(tb, state, cx1, cx2, cy1, hover_btn)
            _alpha(tb, hover)
            base.alpha_composite(tb)

        content = base.resize((self.W, self.H), Image.Resampling.LANCZOS)

        out = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        s = self.scale
        s_pad = int(round(PAD * s))
        s_cw = int(round(cw * s))
        s_ch = int(round(ch * s))
        sx2 = self.W - s_pad
        sy2 = self.H - s_pad
        sx1 = sx2 - s_cw
        sy1 = sy2 - s_ch
        shadow = Image.new("L", (self.W, self.H), 0)
        ImageDraw.Draw(shadow).rounded_rectangle(
            [sx1, sy1 + 2 * s, sx2, sy2 + 3 * s],
            radius=max(1, int(s_ch / 2)), fill=120,
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(8.0 * s))
        shade = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 255))
        shade.putalpha(shadow)
        out.alpha_composite(shade)
        out.alpha_composite(content)
        return out

    def _draw_idle(self, img, state, accent, cx1, cx2, cy1, cy2,
                   spinner, pulse):
        u = self.u
        cx = (cx1 + cx2) / 2.0
        cy = (cy1 + cy2) / 2.0
        d = ImageDraw.Draw(img)
        self._mic(d, cx, cy - 1.0, 1.0, (245, 245, 248, 245))

        if state == STATE_LOADING:
            rad = 21.0
            box = [self._px(cx - rad), self._px(cy - rad),
                   self._px(cx + rad), self._px(cy + rad)]
            start = (spinner * 2.0) % 360.0
            d.arc(box, start=start, end=start + 100.0,
                  fill=accent + (190,), width=max(1, int(round(2.0 * u))))
            label_x1 = 14.0
            label_x2 = cx1 - 8.0
            label_y1 = cy - 15.0
            label_y2 = cy + 15.0
            d.rounded_rectangle(
                [self._px(label_x1), self._px(label_y1),
                 self._px(label_x2), self._px(label_y2)],
                radius=self._px(15.0), fill=(24, 24, 29, 238),
                outline=(255, 255, 255, 28),
                width=max(1, int(round(1.0 * u))),
            )
            f = _font(10.5 * u, "regular")
            d.text(
                (self._px((label_x1 + label_x2) / 2.0),
                 self._px(cy + 0.3)),
                "preparando modelo...", font=f,
                fill=(235, 235, 240, 228), anchor="mm",
            )
        elif state == STATE_READY:
            dot = 3.0 + 0.4 * pulse
            gx = cx2 - 11.0
            gy = cy2 - 11.0
            d.ellipse(
                [self._px(gx - dot * 2.1), self._px(gy - dot * 2.1),
                 self._px(gx + dot * 2.1), self._px(gy + dot * 2.1)],
                fill=accent + (38,),
            )
            d.ellipse(
                [self._px(gx - dot), self._px(gy - dot),
                 self._px(gx + dot), self._px(gy + dot)],
                fill=accent + (245,),
            )
        elif state == STATE_ERROR:
            dot = 3.4
            gx = cx2 - 11.0
            gy = cy2 - 11.0
            d.ellipse(
                [self._px(gx - dot), self._px(gy - dot),
                 self._px(gx + dot), self._px(gy + dot)],
                fill=accent + (245,),
            )

    def _draw_expanded(self, img, state, accent, cx1, cx2, cy1, cy2,
                       timer, progress, status, bars, pulse,
                       sens_level=4, sens_levels=7, sens_visible=False):
        u = self.u
        d = ImageDraw.Draw(img)
        cy = (cy1 + cy2) / 2.0

        if state == STATE_RECORDING:
            dot = 3.2 + 0.8 * pulse
            dx = cx1 + 16.0
            d.ellipse(
                [self._px(dx - dot * 2.0), self._px(cy - dot * 2.0),
                 self._px(dx + dot * 2.0), self._px(cy + dot * 2.0)],
                fill=accent + (34,),
            )
            d.ellipse(
                [self._px(dx - dot), self._px(cy - dot),
                 self._px(dx + dot), self._px(cy + dot)],
                fill=accent + (245,),
            )
            area_x1 = cx1 + 30.0
            area_x2 = cx2 - 58.0
            n = max(1, len(bars))
            bw = 1.8
            gap = (area_x2 - area_x1 - n * bw) / max(1, n - 1)
            max_h = 29.0
            for i in range(n):
                h = 2.0 + max_h * _clamp(bars[i] if i < len(bars) else 0.0,
                                         0.0, 1.0)
                bx = area_x1 + i * (bw + gap)
                d.rounded_rectangle(
                    [self._px(bx), self._px(cy - h / 2.0),
                     self._px(bx + bw), self._px(cy + h / 2.0)],
                    radius=self._px(bw / 2.0),
                    fill=(250, 250, 252, 235),
                )
            txt = timer or "0:00"
            f = _font(12.5 * u, "semibold")
            d.text((self._px(cx2 - 14.0), self._px(cy + 0.2)), txt,
                   font=f, fill=(245, 245, 248, 235), anchor="rm")
            if sens_visible:
                self._draw_sensitivity(d, accent, cx1, cx2, cy2,
                                       sens_level, sens_levels)
            return

        if state == STATE_PROCESSING:
            pct = _clamp(float(progress or 0.0), 0.0, 100.0)
            rx = cx1 + 22.0
            rad = 7.5
            box = [self._px(rx - rad), self._px(cy - rad),
                   self._px(rx + rad), self._px(cy + rad)]
            d.ellipse(box, outline=(255, 255, 255, 38),
                      width=max(1, int(round(2.6 * u))))
            if pct > 0.5:
                d.arc(box, start=-90.0, end=-90.0 + 360.0 * pct / 100.0,
                      fill=accent + (245,),
                      width=max(1, int(round(2.6 * u))))
            f = _font(12.5 * u, "semibold")
            d.text((self._px(cx2 - 14.0), self._px(cy + 0.2)),
                   f"{int(round(pct))}%", font=f,
                   fill=(245, 245, 248, 235), anchor="rm")
            bar_x1 = cx1 + 12.0
            bar_x2 = cx2 - 12.0
            by = cy2 - 4.0
            d.rounded_rectangle(
                [self._px(bar_x1), self._px(by - 0.75),
                 self._px(bar_x2), self._px(by + 0.75)],
                radius=self._px(0.75), fill=(255, 255, 255, 24),
            )
            if pct > 0:
                d.rounded_rectangle(
                    [self._px(bar_x1), self._px(by - 0.75),
                     self._px(bar_x1 + (bar_x2 - bar_x1) * pct / 100.0),
                     self._px(by + 0.75)],
                    radius=self._px(0.75), fill=accent + (180,),
                )
            return

        text = status or ("erro" if state == STATE_ERROR else "")
        icon_x = cx1 + 22.0
        ir = 7.5
        if state == STATE_ERROR:
            d.ellipse(
                [self._px(icon_x - ir), self._px(cy - ir),
                 self._px(icon_x + ir), self._px(cy + ir)],
                fill=accent + (52,), outline=accent + (210,),
                width=max(1, int(round(1.2 * u))),
            )
            fw = _font(11.0 * u, "bold")
            d.text((self._px(icon_x), self._px(cy + 0.3)), "!",
                   font=fw, fill=(255, 255, 255, 235), anchor="mm")
        else:
            d.ellipse(
                [self._px(icon_x - ir), self._px(cy - ir),
                 self._px(icon_x + ir), self._px(cy + ir)],
                fill=accent + (48,), outline=accent + (210,),
                width=max(1, int(round(1.2 * u))),
            )
            self._check(d, icon_x, cy, 4.2, accent + (245,))
        max_w = (cx2 - 14.0) - (cx1 + 36.0)
        f = _font(10.3 * u, "regular")
        text = _truncate(d, text, f, self._px(max_w))
        d.text((self._px(cx1 + 36.0), self._px(cy + 0.3)), text,
               font=f, fill=(240, 240, 244, 232), anchor="lm")
        if sens_visible:
            self._draw_sensitivity(d, accent, cx1, cx2, cy2,
                                   sens_level, sens_levels)

    def _draw_sensitivity(self, d, accent, cx1, cx2, cy2, level, levels):
        n = max(1, int(levels))
        level = max(1, min(n, int(level)))
        track_x1 = cx1 + 30.0
        track_x2 = cx2 - 58.0
        track_y = cy2 - 6.0
        d.rounded_rectangle(
            [self._px(track_x1), self._px(track_y - 1.0),
             self._px(track_x2), self._px(track_y + 1.0)],
            radius=self._px(1.0), fill=(255, 255, 255, 40),
        )
        for i in range(n):
            frac = i / max(1, n - 1)
            tx = track_x1 + (track_x2 - track_x1) * frac
            d.ellipse(
                [self._px(tx - 1.1), self._px(track_y - 1.1),
                 self._px(tx + 1.1), self._px(track_y + 1.1)],
                fill=(255, 255, 255, 80),
            )
        knob_frac = (level - 1) / max(1, n - 1)
        knob_x = track_x1 + (track_x2 - track_x1) * knob_frac
        d.ellipse(
            [self._px(knob_x - 2.6), self._px(track_y - 2.6),
             self._px(knob_x + 2.6), self._px(track_y + 2.6)],
            fill=accent + (245,),
        )

    def _draw_toolbar(self, img, state, cx1, cx2, cy1, hover_btn):
        u = self.u
        d = ImageDraw.Draw(img)
        tw = TOOLBAR_W
        th = TOOLBAR_H
        x2 = cx2
        y2 = cy1 - TOOLBAR_GAP
        x1 = x2 - tw
        y1 = y2 - th
        d.rounded_rectangle(
            [self._px(x1), self._px(y1), self._px(x2), self._px(y2)],
            radius=self._px(9.0), fill=(24, 24, 29, 246),
            outline=(255, 255, 255, 28),
            width=max(1, int(round(1.0 * u))),
        )
        split = x1 + 66.0
        if hover_btn == "copy":
            d.rounded_rectangle(
                [self._px(x1 + 3), self._px(y1 + 3),
                 self._px(split - 2), self._px(y2 - 3)],
                radius=self._px(7.0), fill=(53, 53, 60, 246),
            )
        elif hover_btn == "close":
            d.rounded_rectangle(
                [self._px(split + 2), self._px(y1 + 3),
                 self._px(x2 - 3), self._px(y2 - 3)],
                radius=self._px(7.0), fill=(82, 35, 36, 246),
            )
        cy = (y1 + y2) / 2.0
        ix = x1 + 12.0
        d.rounded_rectangle(
            [self._px(ix), self._px(cy - 2.0),
             self._px(ix + 8.0), self._px(cy + 6.0)],
            radius=self._px(1.6), outline=(235, 235, 240, 225),
            width=max(1, int(round(1.0 * u))),
        )
        d.rounded_rectangle(
            [self._px(ix + 3.0), self._px(cy - 6.0),
             self._px(ix + 11.0), self._px(cy + 2.0)],
            radius=self._px(1.6), fill=(24, 24, 29, 246),
            outline=(235, 235, 240, 225),
            width=max(1, int(round(1.0 * u))),
        )
        f = _font(8.8 * u, "regular")
        d.text((self._px(ix + 17.0), self._px(cy + 0.2)), "copiar",
               font=f, fill=(235, 235, 240, 225), anchor="lm")
        d.line(
            [self._px(split), self._px(y1 + 7),
             self._px(split), self._px(y2 - 7)],
            fill=(255, 255, 255, 24), width=max(1, int(round(1.0 * u))),
        )
        ccx = (split + x2) / 2.0
        for dx, dy in ((-3.2, -3.2), (-3.2, 3.2)):
            _round_line(
                d,
                (self._px(ccx + dx), self._px(cy + dy)),
                (self._px(ccx - dx), self._px(cy - dy)),
                1.8 * u, (235, 235, 240, 225),
            )

    def _mic(self, d, cx, cy, scale, fill):
        u = self.u
        w = 10.0 * scale
        head_h = 16.0 * scale
        d.rounded_rectangle(
            [self._px(cx - w / 2.0), self._px(cy - 15.0 * scale),
             self._px(cx + w / 2.0), self._px(cy - 15.0 * scale + head_h)],
            radius=self._px(w / 2.0), fill=fill,
        )
        rad = 9.2 * scale
        d.arc(
            [self._px(cx - rad), self._px(cy - 10.0 * scale),
             self._px(cx + rad), self._px(cy + 8.4 * scale)],
            start=18.0, end=162.0, fill=fill,
            width=max(1, int(round(2.0 * u))),
        )
        _round_line(
            d,
            (self._px(cx), self._px(cy + 8.2 * scale)),
            (self._px(cx), self._px(cy + 13.2 * scale)),
            2.0 * u, fill,
        )
        _round_line(
            d,
            (self._px(cx - 5.0 * scale), self._px(cy + 14.0 * scale)),
            (self._px(cx + 5.0 * scale), self._px(cy + 14.0 * scale)),
            2.0 * u, fill,
        )

    def _check(self, d, cx, cy, size, fill):
        u = self.u
        _round_line(
            d,
            (self._px(cx - size), self._px(cy)),
            (self._px(cx - size * 0.25), self._px(cy + size * 0.75)),
            2.0 * u, fill,
        )
        _round_line(
            d,
            (self._px(cx - size * 0.25), self._px(cy + size * 0.75)),
            (self._px(cx + size), self._px(cy - size * 0.8)),
            2.0 * u, fill,
        )


class _LayeredSurface:
    def __init__(self, width, height):
        self.width = int(width)
        self.height = int(height)
        self.screen_dc = user32.GetDC(None)
        if not self.screen_dc:
            raise RuntimeError("GetDC falhou")
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        if not self.mem_dc:
            raise RuntimeError("CreateCompatibleDC falhou")

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wt.DWORD),
                ("biWidth", wt.LONG),
                ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [
                ("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", wt.DWORD * 3),
            ]

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.width
        bmi.bmiHeader.biHeight = -self.height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        self.bits = ctypes.c_void_p()
        gdi32.CreateDIBSection.argtypes = [
            wt.HDC, ctypes.c_void_p, wt.UINT,
            ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD,
        ]
        gdi32.CreateDIBSection.restype = wt.HANDLE
        self.bitmap = gdi32.CreateDIBSection(
            self.mem_dc, ctypes.byref(bmi), 0,
            ctypes.byref(self.bits), None, 0,
        )
        if not self.bitmap or not self.bits:
            raise RuntimeError("CreateDIBSection falhou")
        self.old = gdi32.SelectObject(self.mem_dc, self.bitmap)

    def update(self, hwnd, image):
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height))
        arr = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        bgra = np.empty_like(arr)
        bgra[:, :, 0] = arr[:, :, 2]
        bgra[:, :, 1] = arr[:, :, 1]
        bgra[:, :, 2] = arr[:, :, 0]
        bgra[:, :, 3] = arr[:, :, 3]
        a = bgra[:, :, 3].astype(np.uint16)
        bgra[:, :, :3] = (
            bgra[:, :, :3].astype(np.uint16) * a[:, :, None] // 255
        ).astype(np.uint8)
        data = bgra.tobytes()
        ctypes.memmove(self.bits, data, len(data))

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [
                ("BlendOp", ctypes.c_ubyte),
                ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte),
            ]

        size = wt.SIZE(self.width, self.height)
        src = wt.POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        user32.UpdateLayeredWindow.argtypes = [
            wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT),
            ctypes.POINTER(wt.SIZE), wt.HDC, ctypes.POINTER(wt.POINT),
            wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD,
        ]
        user32.UpdateLayeredWindow.restype = wt.BOOL
        ok = user32.UpdateLayeredWindow(
            wt.HWND(hwnd), self.screen_dc, None, ctypes.byref(size),
            self.mem_dc, ctypes.byref(src), 0, ctypes.byref(blend),
            ULW_ALPHA,
        )
        return bool(ok)

    def close(self):
        try:
            if self.old:
                gdi32.SelectObject(self.mem_dc, self.old)
        except Exception:
            pass
        try:
            if self.bitmap:
                gdi32.DeleteObject(self.bitmap)
        except Exception:
            pass
        try:
            if self.mem_dc:
                gdi32.DeleteDC(self.mem_dc)
        except Exception:
            pass
        try:
            if self.screen_dc:
                user32.ReleaseDC(None, self.screen_dc)
        except Exception:
            pass
        self.bitmap = None
        self.mem_dc = None
        self.screen_dc = None


_WINDOWS = {}
_CLASS_REGISTERED = False
_WNDPROC_TYPE = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
)


@_WNDPROC_TYPE
def _window_proc(hwnd, msg, wparam, lparam):
    obj = _WINDOWS.get(int(hwnd or 0))
    if obj is not None:
        try:
            return obj._on_message(msg, wparam, lparam)
        except Exception as exc:
            try:
                obj.log(f"widget: erro no WndProc: {exc}")
            except Exception:
                pass
            return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class NativeWidget:
    def __init__(self, root, cfg, scale, on_toggle, on_settings,
                 on_copy, on_close, on_sensitivity=None, logger=None, show=True):
        self.root = root
        self.cfg = cfg
        self.scale = float(scale)
        self.on_toggle = on_toggle
        self.on_settings = on_settings
        self.on_copy = on_copy
        self.on_close = on_close
        self.on_sensitivity = on_sensitivity
        self.log = logger or _log_none
        self.visible = False

        self.W = max(1, int(round(LOGICAL_W * self.scale)))
        self.H = max(1, int(round(LOGICAL_H * self.scale)))
        self.renderer = Renderer(self.scale)

        self.state = STATE_LOADING
        self.status = ""
        self.timer = ""
        self.progress = None
        self.level = 0.0
        self.bars = [0.02] * 36
        self.wave_targets = [0.02] * 36
        self.spinner = 0.0
        self.pulse = 0.0
        self.accent = ACCENTS[STATE_LOADING]
        self.width = float(IDLE_W)
        self.sens_level = 4
        self.sens_levels = 7
        self.sens_visible = False
        self.hover = False
        self.hover_t = 0.0
        self.hover_btn = None
        self._hover_grace = 0.0
        self._dirty = True
        self._dead = False
        self._dragging = False
        self._drag_off = (0, 0)
        self._click_after = None
        self._click_due = None
        self._callbacks = queue.Queue()
        self._mouse_hook = None
        self._mouse_hook_proc = None
        self._mouse_hook_tid = 0
        self._tick_id = None
        self._pump_id = None
        self._last_tick = time.perf_counter()
        self._surface = None
        self._hwnd = 0
        self._fail_count = 0
        self._class_name = f"DictadoWidget_{os.getpid()}"
        self._setup_win32()
        self._hand_cursor = user32.LoadCursorW(None, 32649)
        try:
            self._create_window()
            self._surface = _LayeredSurface(self.W, self.H)
            if not self._render(force=True):
                raise RuntimeError("UpdateLayeredWindow falhou")
            self.place_bottom_right(show=False)
            if show:
                self.show()
            self._pump_id = self.root.after(10, self._pump)
            self._tick_id = self.root.after(16, self._tick)
            self._install_mouse_hook()
        except Exception:
            self.shutdown()
            raise

    @property
    def hwnd(self):
        return self._hwnd

    def _setup_win32(self):
        kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wt.HMODULE
        user32.LoadCursorW.argtypes = [wt.HINSTANCE, wt.LPVOID]
        user32.LoadCursorW.restype = wt.HANDLE
        user32.DefWindowProcW.argtypes = [
            wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
        ]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self._get_long = getattr(
            user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        self._set_long = getattr(
            user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        self._get_long.argtypes = [wt.HWND, ctypes.c_int]
        self._get_long.restype = ctypes.c_ssize_t
        self._set_long.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._set_long.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = [
            wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wt.UINT,
        ]
        user32.SetWindowPos.restype = wt.BOOL
        user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wt.BOOL
        user32.DestroyWindow.argtypes = [wt.HWND]
        user32.DestroyWindow.restype = wt.BOOL
        user32.SetCapture.argtypes = [wt.HWND]
        user32.ReleaseCapture.restype = wt.BOOL
        user32.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
        user32.ScreenToClient.restype = wt.BOOL

    def _create_window(self):
        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.UINT),
                ("style", wt.UINT),
                ("lpfnWndProc", _WNDPROC_TYPE),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR),
                ("hIconSm", wt.HICON),
            ]

        global _CLASS_REGISTERED
        if not _CLASS_REGISTERED:
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 0x0001 | 0x0008
            wc.lpfnWndProc = _window_proc
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.lpszClassName = self._class_name
            user32.RegisterClassExW.argtypes = [
                ctypes.POINTER(WNDCLASSEXW)]
            user32.RegisterClassExW.restype = wt.ATOM
            if not user32.RegisterClassExW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err != 1410:
                    raise RuntimeError(f"RegisterClassExW falhou ({err})")
            _CLASS_REGISTERED = True

        ex_style = (WS_EX_LAYERED | WS_EX_TOOLWINDOW |
                    WS_EX_NOACTIVATE | WS_EX_TOPMOST)
        user32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
        ]
        user32.CreateWindowExW.restype = wt.HWND
        hwnd = user32.CreateWindowExW(
            ex_style, self._class_name, "Dictado", WS_POPUP,
            0, 0, self.W, self.H, None, None,
            kernel32.GetModuleHandleW(None), None,
        )
        if not hwnd:
            raise RuntimeError(
                f"CreateWindowExW falhou ({ctypes.get_last_error()})")
        self._hwnd = int(hwnd)
        _WINDOWS[self._hwnd] = self

    def _call(self, fn):
        # Nao chamar Tk de dentro do WndProc/ctypes: o callback e enfileirado
        # e executado pela thread principal no proximo _pump.
        if self._dead or fn is None:
            return
        self._callbacks.put(fn)

    def _drain_callbacks(self):
        while not self._dead:
            try:
                fn = self._callbacks.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as exc:
                try:
                    self.log(f"widget: erro em callback: {exc!r}")
                except Exception:
                    pass

    def _handle_global_wheel(self, x, y, delta):
        if self._dead or not self._hwnd or not self.on_sensitivity:
            return False
        try:
            rx, ry, rw, rh = self.rect()
        except Exception:
            return False
        if not (rx <= x < rx + rw and ry <= y < ry + rh):
            return False
        try:
            if self._hit_local(x - rx, y - ry) != "content":
                return False
        except Exception:
            return False
        self._call(lambda d=delta: self.on_sensitivity(d))
        return True

    def _install_mouse_hook(self):
        # WM_MOUSEWHEEL vai para a janela com foco; a pilula e NOACTIVATE.
        # Um hook global entrega a roda mesmo sem foco, mas roda numa thread
        # propria e apenas enfileira o callback para o Tk.
        def run():
            try:
                class MSLLHOOKSTRUCT(ctypes.Structure):
                    _fields_ = [
                        ("pt", wt.POINT),
                        ("mouseData", wt.DWORD),
                        ("flags", wt.DWORD),
                        ("time", wt.DWORD),
                        ("dwExtraInfo", ctypes.c_void_p),
                    ]

                hook_type = ctypes.WINFUNCTYPE(
                    ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)

                def proc(n_code, wparam, lparam):
                    try:
                        if n_code >= 0 and int(wparam) == WM_MOUSEWHEEL:
                            data = ctypes.cast(
                                lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                            delta = ctypes.c_short(
                                (data.mouseData >> 16) & 0xFFFF).value
                            if self._handle_global_wheel(
                                    data.pt.x, data.pt.y, delta):
                                return 1
                    except Exception:
                        pass
                    return user32.CallNextHookEx(
                        None, n_code, wparam, lparam)

                self._mouse_hook_proc = hook_type(proc)
                user32.SetWindowsHookExW.argtypes = [
                    ctypes.c_int, hook_type, ctypes.c_void_p, wt.DWORD]
                user32.SetWindowsHookExW.restype = ctypes.c_void_p
                user32.CallNextHookEx.argtypes = [
                    ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
                user32.CallNextHookEx.restype = ctypes.c_ssize_t
                user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
                user32.UnhookWindowsHookEx.restype = wt.BOOL
                user32.GetMessageW.argtypes = [
                    ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
                user32.GetMessageW.restype = wt.BOOL
                user32.PostThreadMessageW.argtypes = [
                    wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
                user32.PostThreadMessageW.restype = wt.BOOL
                kernel32.GetCurrentThreadId.restype = wt.DWORD
                self._mouse_hook_tid = kernel32.GetCurrentThreadId()
                self._mouse_hook = user32.SetWindowsHookExW(
                    WH_MOUSE_LL, self._mouse_hook_proc,
                    kernel32.GetModuleHandleW(None), 0)
                if not self._mouse_hook:
                    self.log(f"hook da roda falhou "
                             f"({ctypes.get_last_error()})")
                    return
                self.log("hook da roda: ativo")
                msg = wt.MSG()
                while not self._dead:
                    ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if ret <= 0:
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            except Exception as exc:
                try:
                    self.log(f"hook da roda: {exc!r}")
                except Exception:
                    pass
            finally:
                if self._mouse_hook:
                    try:
                        user32.UnhookWindowsHookEx(self._mouse_hook)
                    except Exception:
                        pass
                    self._mouse_hook = None

        threading.Thread(
            target=run, name="dictado-mouse-hook", daemon=True).start()

    def show(self):
        if self._hwnd:
            self.visible = True
            self._dirty = True
            user32.ShowWindow(wt.HWND(self._hwnd), SW_SHOWNOACTIVATE)

    def hide(self):
        if self._hwnd:
            self.visible = False
            user32.ShowWindow(wt.HWND(self._hwnd), SW_HIDE)

    def set_visible(self, visible):
        if visible:
            self.show()
        else:
            self.hide()

    def place_bottom_right(self, show=None):
        rect = wt.RECT()
        ok = user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        if not ok:
            rect.left = 0
            rect.top = 0
            rect.right = user32.GetSystemMetrics(SM_CXSCREEN)
            rect.bottom = user32.GetSystemMetrics(SM_CYSCREEN)
        s = self.scale
        pad = int(round(PAD * s))
        margin = int(round(MARGIN_X * s))
        extra = int(round(EXTRA_Y * s))
        content_right = rect.right - margin
        content_bottom = rect.bottom - margin - extra
        x = content_right - (self.W - pad)
        y = content_bottom - (self.H - pad)
        self._move(x, y, show=show)
        self._dirty = True

    def _move(self, x, y, show=None):
        if not self._hwnd:
            return
        if show is None:
            show = self.visible
        flags = SWP_NOSIZE | SWP_NOACTIVATE
        if show:
            flags |= SWP_SHOWWINDOW
        user32.SetWindowPos(
            wt.HWND(self._hwnd), HWND_TOPMOST, int(x), int(y), 0, 0, flags,
        )

    def rect(self):
        if not self._hwnd:
            return (0, 0, 0, 0)
        r = wt.RECT()
        user32.GetWindowRect(wt.HWND(self._hwnd), ctypes.byref(r))
        return (int(r.left), int(r.top), int(r.right - r.left),
                int(r.bottom - r.top))

    def visible_center(self):
        x, y, w, h = self.rect()
        pad = int(round(PAD * self.scale))
        ch = int(round(CONTENT_H * self.scale))
        cw = int(round(self.width * self.scale))
        return (x + w - pad - cw // 2, y + h - pad - ch // 2)

    def _content_local(self):
        pad = int(round(PAD * self.scale))
        cw = int(round(self.width * self.scale))
        ch = int(round(CONTENT_H * self.scale))
        x2 = self.W - pad
        y2 = self.H - pad
        return (x2 - cw, y2 - ch, x2, y2)

    def _toolbar_local(self):
        cx1, cy1, cx2, _ = self._content_local()
        tw = int(round(TOOLBAR_W * self.scale))
        th = int(round(TOOLBAR_H * self.scale))
        gap = int(round(TOOLBAR_GAP * self.scale))
        x2 = cx2
        y2 = cy1 - gap
        return (x2 - tw, y2 - th, x2, y2)

    def _hit_local(self, x, y):
        if self.state != STATE_LOADING and self.hover_t > 0.02:
            tx1, ty1, tx2, ty2 = self._toolbar_local()
            if tx1 <= x <= tx2 and ty1 <= y <= ty2:
                split = tx1 + int(round(66 * self.scale))
                return "copy" if x < split else "close"
        cx1, cy1, cx2, cy2 = self._content_local()
        if cx1 <= x <= cx2 and cy1 <= y <= cy2:
            return "content"
        return None

    def _hit_from_lparam(self, lparam):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        return self._hit_local(x, y)

    def _target_width(self):
        if self.state in (STATE_RECORDING, STATE_PROCESSING):
            return float(EXPANDED_W)
        if self.state == STATE_ERROR:
            return float(EXPANDED_W)
        if self.state == STATE_READY and self.hover > 0.01:
            return float(EXPANDED_W)
        if self.status:
            return float(EXPANDED_W)
        return float(IDLE_W)

    def set_state(self, state, extra=None):
        self.state = state
        self.status = extra or ""
        if state != STATE_RECORDING:
            self.timer = ""
        if state != STATE_PROCESSING:
            self.progress = None
        self._dirty = True

    def set_status(self, text):
        text = text or ""
        if text != self.status:
            self.status = text
            self._dirty = True

    def clear_status(self):
        if self.status:
            self.status = ""
            self._dirty = True

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

    def set_timer(self, text):
        if text != self.timer:
            self.timer = text
            self._dirty = True

    def set_progress(self, pct):
        self.progress = pct
        self._dirty = True

    def set_level(self, level):
        self.level = float(level)
        if self.state == STATE_RECORDING:
            self._dirty = True

    def set_waveform(self, bars):
        bars = [ _clamp(float(v), 0.0, 1.0) for v in (bars or []) ]
        if not bars:
            return
        if len(bars) != len(self.wave_targets):
            self.wave_targets = bars
            self.bars = list(bars)
        else:
            self.wave_targets = bars
        if self.state == STATE_RECORDING:
            self._dirty = True

    def set_thresholds(self, silence, voice):
        self.cfg["silence"] = silence
        self.cfg["voice"] = voice

    def refresh_thresholds(self):
        pass

    def reassert(self):
        if not self._hwnd:
            return
        try:
            style = int(self._get_long(wt.HWND(self._hwnd), GWL_EXSTYLE))
            new_style = style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | \
                WS_EX_NOACTIVATE | WS_EX_TOPMOST
            if new_style != style:
                self._set_long(wt.HWND(self._hwnd), GWL_EXSTYLE, new_style)
            user32.SetWindowPos(
                wt.HWND(self._hwnd), HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
            self._dirty = True
        except Exception as exc:
            self.log(f"widget: reassert falhou: {exc}")

    def _poll_hover(self):
        if not self._hwnd:
            return
        if not self.visible:
            self.hover = False
            self.hover_btn = None
            self.hover_t = 0.0
            return
        pt = wt.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return
        x, y, w, h = self.rect()
        if not (x <= pt.x < x + w and y <= pt.y < y + h):
            hit = None
        else:
            hit = self._hit_local(pt.x - x, pt.y - y)
        now = time.perf_counter()
        if hit:
            self._hover_grace = now + 0.35
            if not self.hover:
                self.hover = True
                self._dirty = True
            btn = hit if hit in ("copy", "close") else None
            if btn != self.hover_btn:
                self.hover_btn = btn
                self._dirty = True
        else:
            if self.hover and now > self._hover_grace:
                self.hover = False
                self.hover_btn = None
                self._dirty = True

    def _tick(self):
        if self._dead:
            return
        now = time.perf_counter()
        if self._click_due is not None and now >= self._click_due:
            self._fire_toggle()
        dt = _clamp(now - self._last_tick, 0.001, 0.12)
        self._last_tick = now
        self._poll_hover()

        target = self._target_width()
        if abs(target - self.width) > 0.04:
            self.width += (target - self.width) * min(1.0, dt * 13.0)
            if abs(target - self.width) < 0.15:
                self.width = target
            self._dirty = True

        target_accent = ACCENTS.get(self.state, ACCENTS[STATE_READY])
        if self.accent != target_accent:
            self.accent = _mix(self.accent + (255,),
                               target_accent + (255,),
                               min(1.0, dt * 9.0))[:3]
            self._dirty = True

        target_hover = 1.0 if self.hover else 0.0
        if abs(target_hover - self.hover_t) > 0.01:
            self.hover_t += (target_hover - self.hover_t) * min(1.0, dt * 14.0)
            self._dirty = True

        if self.state == STATE_RECORDING:
            n = min(len(self.bars), len(self.wave_targets))
            for i in range(n):
                tgt = self.wave_targets[i]
                speed = 30.0 if tgt > self.bars[i] else 15.0
                self.bars[i] += (tgt - self.bars[i]) * min(1.0, dt * speed)
            if n != len(self.bars):
                self.bars = list(self.wave_targets)
            self._dirty = True
            silence = self.cfg.get("silence", 0.006)
            self.pulse = (0.5 + 0.5 * math.sin(now * 4.6)
                          if self.level >= silence else 0.0)
        elif self.state == STATE_PROCESSING:
            self.spinner += dt * 400.0
            self.pulse = 0.5 + 0.5 * math.sin(now * 4.0)
            self._dirty = True
        elif self.state == STATE_LOADING:
            self.spinner += dt * 400.0
            self._dirty = True
        else:
            self.pulse = 0.0

        if self._dirty and self.visible:
            self._render()

        moving = (abs(target - self.width) > 0.05
                  or abs(target_hover - self.hover_t) > 0.02)
        if self.state == STATE_RECORDING or moving:
            interval = 16
        elif not self.visible:
            interval = 100
        elif self.state in (STATE_PROCESSING, STATE_LOADING):
            interval = 33
        else:
            interval = 45
        self._tick_id = self.root.after(interval, self._tick)

    def _render(self, force=False):
        if self._dead or not self._hwnd or self._surface is None:
            return False
        if not force and not self._dirty:
            return True
        img = self.renderer.render(
            state=self.state,
            width=self.width,
            timer=self.timer,
            progress=self.progress,
            status=self.status,
            bars=self.bars,
            hover=self.hover_t,
            hover_btn=self.hover_btn,
            spinner=self.spinner,
            pulse=self.pulse,
            sens_level=self.sens_level,
            sens_levels=self.sens_levels,
            sens_visible=self.sens_visible or (
                self.state == STATE_READY and self.hover),
        )
        ok = self._surface.update(self._hwnd, img)
        if not ok:
            self._fail_count += 1
            if self._fail_count in (1, 20, 100):
                self.log(
                    f"widget: UpdateLayeredWindow falhou "
                    f"({ctypes.get_last_error()})")
        else:
            self._fail_count = 0
        self._dirty = False
        return ok

    def _pump(self):
        if self._dead or not self._hwnd:
            return
        msg = wt.MSG()
        while user32.PeekMessageW(
                ctypes.byref(msg), wt.HWND(self._hwnd), 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._drain_callbacks()
        self._pump_id = self.root.after(10, self._pump)

    def _on_message(self, msg, wparam, lparam):
        if msg == WM_DESTROY:
            _WINDOWS.pop(self._hwnd, None)
            self._hwnd = 0
            return 0
        if msg == WM_PAINT:
            user32.ValidateRect(wt.HWND(self._hwnd), None)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_NCHITTEST:
            if self._dragging:
                return HTCLIENT
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            rx, ry, _, _ = self.rect()
            if self._hit_local(x - rx, y - ry):
                return HTCLIENT
            return HTTRANSPARENT
        if msg == WM_SETCURSOR:
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            rx, ry, _, _ = self.rect()
            if self._hit_local(pt.x - rx, pt.y - ry):
                user32.SetCursor(self._hand_cursor)
                return 1
            return user32.DefWindowProcW(
                wt.HWND(self._hwnd), msg, wparam, lparam)
        if msg == WM_MOUSEWHEEL:
            delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
            pt = wt.POINT(
                ctypes.c_short(lparam & 0xFFFF).value,
                ctypes.c_short((lparam >> 16) & 0xFFFF).value,
            )
            user32.ScreenToClient(wt.HWND(self._hwnd), ctypes.byref(pt))
            if self._hit_local(pt.x, pt.y) == "content" and self.on_sensitivity:
                self._call(lambda d=delta: self.on_sensitivity(d))
                return 0
            return user32.DefWindowProcW(
                wt.HWND(self._hwnd), msg, wparam, lparam)
        if msg == WM_LBUTTONDOWN:
            hit = self._hit_from_lparam(lparam)
            if hit == "copy":
                self._call(self.on_copy)
            elif hit == "close":
                self._call(self.on_close)
            elif hit == "content":
                self._cancel_click()
                self._click_due = time.monotonic() + 0.26
            return 0
        if msg == WM_LBUTTONDBLCLK:
            hit = self._hit_from_lparam(lparam)
            if hit == "content":
                self._cancel_click()
                self._call(self.on_settings)
            return 0
        if msg == WM_RBUTTONDOWN:
            hit = self._hit_from_lparam(lparam)
            if hit in ("content", "copy", "close"):
                self._begin_drag()
            return 0
        if msg == WM_MOUSEMOVE:
            if self._dragging:
                self._move_drag()
            return 0
        if msg == WM_RBUTTONUP:
            self._end_drag()
            return 0
        if msg == WM_CAPTURECHANGED:
            self._dragging = False
            return 0
        return user32.DefWindowProcW(
            wt.HWND(self._hwnd), msg, wparam, lparam)

    def _cancel_click(self):
        self._click_due = None

    def _fire_toggle(self):
        self._click_due = None
        self._call(self.on_toggle)

    def _begin_drag(self):
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        x, y, _, _ = self.rect()
        self._drag_off = (pt.x - x, pt.y - y)
        self._dragging = True
        user32.SetCapture(wt.HWND(self._hwnd))

    def _move_drag(self):
        if not self._dragging:
            return
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        self._move(pt.x - self._drag_off[0], pt.y - self._drag_off[1])

    def _end_drag(self):
        if self._dragging:
            self._dragging = False
            try:
                user32.ReleaseCapture()
            except Exception:
                pass

    def shutdown(self):
        if self._dead:
            return
        self._dead = True
        self._cancel_click()
        if self._mouse_hook_tid:
            try:
                user32.PostThreadMessageW(
                    self._mouse_hook_tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        for attr in ("_tick_id", "_pump_id"):
            ident = getattr(self, attr, None)
            if ident is not None:
                try:
                    self.root.after_cancel(ident)
                except Exception:
                    pass
                setattr(self, attr, None)
        self._end_drag()
        if self._hwnd:
            _WINDOWS.pop(self._hwnd, None)
            try:
                user32.DestroyWindow(wt.HWND(self._hwnd))
            except Exception:
                pass
            self._hwnd = 0
        if self._surface is not None:
            self._surface.close()
            self._surface = None


class ClassicWidget:
    def __init__(self, root, cfg, scale, on_toggle, on_settings,
                 on_copy, on_close, on_sensitivity=None, logger=None, show=True):
        self.root = root
        self.cfg = cfg
        self.scale = float(scale)
        self.on_toggle = on_toggle
        self.on_settings = on_settings
        self.on_copy = on_copy
        self.on_close = on_close
        self.on_sensitivity = on_sensitivity
        self.log = logger or _log_none
        self.visible = bool(show)
        self.state = STATE_LOADING
        self.size = max(24, int(round(54 * self.scale)))
        self.margin = int(round(MARGIN_X * self.scale))
        self.extra_y = int(round(EXTRA_Y * self.scale))
        self.drag_offset = None
        self._click_after = None
        self._glass_ok = False
        self._glass_first = True
        self._watch_ticks = 0
        self._settings_open = False
        self.preview_stream = None

        self.root.title("Dictado")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-toolwindow", True)
        self.root.configure(bg="#222222")
        if self.visible:
            self.root.deiconify()
        else:
            self.root.withdraw()

        self.canvas = tk.Canvas(
            root, width=self.size, height=self.size,
            highlightthickness=0, bd=0, bg="#222222",
        )
        self.canvas.pack(fill="both", expand=True)
        self._draw_mic()
        self._draw_meter()

        s = self.scale
        self.label = tk.Label(
            root, text=TEXTS[STATE_LOADING], fg="white", bg="#202020",
            font=("Segoe UI", 6), anchor="w",
        )
        self.label.place(
            x=int(round(21 * s)), y=int(round(15 * s)),
            width=max(1, self.size - int(round(23 * s))),
        )
        self.close_btn = tk.Button(
            root, text="x", fg="white", bg="#333333",
            activebackground="#555555", activeforeground="white",
            bd=0, relief="flat", cursor="hand2",
            font=("Segoe UI", 6), command=self.on_close,
            width=2, height=1,
        )
        self.close_btn.place(
            x=self.size - int(round(15 * s)), y=1,
            width=int(round(13 * s)), height=int(round(11 * s)),
        )
        self.copy_btn = tk.Button(
            root, text="copiar", fg="white", bg="#333333",
            activebackground="#555555", activeforeground="white",
            bd=0, relief="flat", cursor="hand2",
            font=("Segoe UI", 6), command=self.on_copy,
        )
        self.copy_btn.place(
            x=int(round(3 * s)), y=self.size - int(round(15 * s)),
            width=self.size - int(round(6 * s)), height=int(round(13 * s)),
        )

        for widget in (self.canvas, self.label, self.close_btn, self.copy_btn):
            widget.bind("<Button-3>", self.start_drag)
            widget.bind("<B3-Motion>", self.do_drag)
        for widget in (self.canvas, self.label):
            widget.bind("<Button-1>", self._on_single_click)
            widget.bind("<Double-Button-1>", self._on_double_click)

        self.place_bottom_right()
        self.root.update_idletasks()
        self._apply_glass()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    @property
    def hwnd(self):
        try:
            return int(user32.GetAncestor(
                int(self.root.winfo_id()), 2) or 0)
        except Exception:
            return 0

    def _draw_mic(self):
        s = self.scale
        cx, cy, r = int(round(10 * s)), int(round(21 * s)), int(round(7 * s))
        self.circle = self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=COLORS[STATE_LOADING], outline="#000000", width=1,
        )

    def _draw_meter(self):
        s = self.scale
        self._meter_x1 = int(round(3 * s))
        self._meter_y1 = int(round(3 * s))
        self._meter_x2 = self.size - int(round(18 * s))
        self._meter_y2 = int(round(8 * s))
        self.meter_fill = self.canvas.create_rectangle(
            self._meter_x1, self._meter_y1, self._meter_x1, self._meter_y2,
            fill="#555555", outline="",
        )
        self._meter_w = self._meter_x2 - self._meter_x1
        self._draw_markers()

    def _meter_pos(self, level):
        if level <= 0:
            return 0.0
        pos = math.log10(level / 0.0005) / 3.0
        return max(0.0, min(1.0, pos))

    def _draw_markers(self):
        try:
            for item in self._marker_ids:
                self.canvas.delete(item)
        except AttributeError:
            pass
        self._marker_ids = []
        for level, color in (
            (self.cfg["voice"], "#ff5555"),
            (self.cfg["silence"], "#777777"),
        ):
            x = self._meter_x1 + self._meter_w * self._meter_pos(level)
            self._marker_ids.append(self.canvas.create_line(
                x, self._meter_y1, x, self._meter_y2, fill=color, width=1,
            ))

    def _apply_glass(self):
        ok = False
        try:
            hwnd = ctypes.c_void_p(
                user32.GetAncestor(int(self.root.winfo_id()), 2))

            class ACCENT_POLICY(ctypes.Structure):
                _fields_ = [
                    ("AccentState", ctypes.c_int),
                    ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint),
                    ("AnimationId", ctypes.c_int),
                ]

            class WCAD(ctypes.Structure):
                _fields_ = [
                    ("Attrib", ctypes.c_int),
                    ("pvData", ctypes.c_void_p),
                    ("cbData", ctypes.c_size_t),
                ]

            accent = ACCENT_POLICY()
            import sys
            win11 = sys.getwindowsversion().build >= 22000
            accent.AccentState = 4 if win11 else 3
            accent.AccentFlags = 2
            accent.GradientColor = 0x66000000
            data = WCAD(19, ctypes.addressof(accent), ctypes.sizeof(accent))
            user32.SetWindowCompositionAttribute.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(WCAD),
            ]
            user32.SetWindowCompositionAttribute.restype = ctypes.c_int
            ok = bool(user32.SetWindowCompositionAttribute(
                hwnd, ctypes.byref(data)))
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4,
                )
            except Exception:
                pass
        except Exception:
            ok = False
        if ok:
            try:
                if str(self.root.attributes("-transparentcolor")) != MAGENTA:
                    self.root.attributes("-transparentcolor", MAGENTA)
                self.canvas.configure(bg=MAGENTA)
            except Exception:
                ok = False
        if not ok:
            try:
                if str(self.root.attributes("-transparentcolor")):
                    self.root.attributes("-transparentcolor", "")
            except Exception:
                pass
            try:
                self.canvas.configure(bg="#222222")
            except Exception:
                pass
        if self._glass_first or ok != self._glass_ok:
            self.log(f"efeito glass: {'ativo' if ok else 'indisponivel'}")
        self._glass_first = False
        self._glass_ok = ok

    def place_bottom_right(self):
        try:
            rect = wt.RECT()
            user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
            x = rect.right - self.size - self.margin
            y = rect.bottom - self.size - self.margin - self.extra_y
        except Exception:
            self.root.update_idletasks()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = sw - self.size - self.margin
            y = sh - self.size - self.margin - self.extra_y
        self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")

    def _reassert_topmost(self):
        try:
            hwnd = ctypes.c_void_p(
                user32.GetAncestor(int(self.root.winfo_id()), 2))
            user32.SetWindowPos.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = ctypes.c_bool
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
            self.root.attributes("-topmost", True)
        except Exception as exc:
            self.log(f"watchdog: falha ao reafirmar topmost: {exc}")

    def reassert(self):
        self._watch_ticks += 1
        self._reassert_topmost()
        if self._glass_ok and self._watch_ticks % 15 == 0:
            self._apply_glass()

    def show(self):
        self.visible = True
        try:
            self.root.deiconify()
        except Exception:
            pass
        self._reassert_topmost()

    def hide(self):
        self.visible = False
        try:
            self.root.withdraw()
        except Exception:
            pass

    def set_visible(self, visible):
        if visible:
            self.show()
        else:
            self.hide()

    def rect(self):
        try:
            return (self.root.winfo_x(), self.root.winfo_y(),
                    self.size, self.size)
        except Exception:
            return (0, 0, self.size, self.size)

    def visible_center(self):
        x, y, w, h = self.rect()
        return (x + w // 2, y + h // 2)

    def set_sensitivity(self, level, levels=7, visible=True):
        return None

    def set_state(self, state, extra=None):
        self.state = state
        try:
            self.canvas.itemconfig(self.circle, fill=COLORS[state])
            self.label.configure(
                text=extra if extra is not None else TEXTS.get(state, ""))
        except Exception:
            pass

    def set_status(self, text):
        try:
            self.label.configure(text=text)
        except Exception:
            pass

    def clear_status(self):
        try:
            self.label.configure(text=TEXTS.get(self.state, ""))
        except Exception:
            pass

    def set_timer(self, text):
        try:
            if self.label.cget("text") != text:
                self.label.configure(text=text)
        except Exception:
            pass

    def set_progress(self, pct):
        try:
            self.label.configure(text=f"{pct}%")
        except Exception:
            pass

    def set_level(self, level):
        if level < self.cfg["silence"]:
            color = "#555555"
        elif level < self.cfg["voice"]:
            color = "#d8a000"
        elif level < 0.35:
            color = "#2ecc71"
        else:
            color = "#c62828"
        try:
            self.canvas.itemconfig(self.meter_fill, fill=color)
            self.canvas.coords(
                self.meter_fill, self._meter_x1, self._meter_y1,
                self._meter_x1 + max(
                    1.0, self._meter_w * self._meter_pos(level)),
                self._meter_y2,
            )
        except Exception:
            pass

    def set_waveform(self, bars):
        pass

    def set_thresholds(self, silence, voice):
        self.cfg["silence"] = silence
        self.cfg["voice"] = voice
        self._draw_markers()

    def refresh_thresholds(self):
        self._draw_markers()

    def _on_single_click(self, event=None):
        if self._click_after is not None:
            self.root.after_cancel(self._click_after)
        self._click_after = self.root.after(260, self._do_toggle)

    def _on_double_click(self, event=None):
        if self._click_after is not None:
            self.root.after_cancel(self._click_after)
            self._click_after = None
        if self.on_settings:
            self.on_settings(event)

    def _do_toggle(self):
        self._click_after = None
        if self.on_toggle:
            self.on_toggle()

    def start_drag(self, event):
        self.drag_offset = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def do_drag(self, event):
        if self.drag_offset:
            dx, dy = self.drag_offset
            self.root.geometry(
                f"+{event.x_root - dx}+{event.y_root - dy}")

    def shutdown(self):
        if self._click_after is not None:
            try:
                self.root.after_cancel(self._click_after)
            except Exception:
                pass
            self._click_after = None


class ModernSlider(tk.Canvas):
    def __init__(self, master, variable, length=230, from_=0, to=100,
                 command=None, bg="#141416", scale=1.0):
        self.scale = float(scale)
        self._length = int(round(length * self.scale))
        self._sh = int(round(26 * self.scale))
        super().__init__(
            master, width=self._length, height=self._sh,
            bg=bg, highlightthickness=0, bd=0,
        )
        self.var = variable
        self.from_ = float(from_)
        self.to = float(to)
        self.command = command
        self._pad = int(round(8 * self.scale))
        self._shover = False
        self.bind("<Button-1>", self._click)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Configure>", lambda e: self._draw())
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _frac(self):
        try:
            v = float(self.var.get())
        except Exception:
            v = self.from_
        return _clamp((v - self.from_) / (self.to - self.from_), 0.0, 1.0)

    def _x(self):
        x1 = self._pad
        x2 = self._length - self._pad
        return x1, x2

    def _draw(self):
        self.delete("all")
        h = self._sh
        y = h // 2
        x1, x2 = self._x()
        vx = x1 + (x2 - x1) * self._frac()
        w = max(3, int(round(4 * self.scale)))
        self.create_line(
            x1, y, x2, y, width=w, fill="#34343a", capstyle="round")
        if vx > x1:
            self.create_line(
                x1, y, vx, y, width=w, fill="#0a84ff", capstyle="round")
        r = int(round((7 if self._shover else 6) * self.scale))
        self.create_oval(
            vx - r, y - r, vx + r, y + r,
            fill="#ffffff", outline="#0a84ff",
            width=max(1, int(round(1.2 * self.scale))),
        )

    def _set(self, x):
        x1, x2 = self._x()
        frac = _clamp((x - x1) / max(1, x2 - x1), 0.0, 1.0)
        v = self.from_ + frac * (self.to - self.from_)
        self.var.set(v)
        if self.command:
            self.command(v)

    def _click(self, event):
        self._set(event.x)

    def _drag(self, event):
        self._set(event.x)

    def _enter(self, event):
        self._shover = True
        self._draw()

    def _leave(self, event):
        self._shover = False
        self._draw()


def _round_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
        x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class PillButton(tk.Canvas):
    def __init__(self, master, text, command, width=88, height=30,
                 fill="#0a84ff", hover="#2f9bff", bg="#141416",
                 fg="#ffffff", scale=1.0):
        self.scale = float(scale)
        self._bw = int(round(width * self.scale))
        self._bh = int(round(height * self.scale))
        super().__init__(
            master, width=self._bw, height=self._bh,
            bg=bg, highlightthickness=0, bd=0, cursor="hand2",
        )
        self.text = text
        self.command = command
        self.fill = fill
        self.hover = hover
        self.fg = fg
        self._bhovering = False
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._draw()

    def _draw(self):
        self.delete("all")
        r = int(round(9 * self.scale))
        color = self.hover if self._bhovering else self.fill
        self.create_polygon(
            _round_points(1, 1, self._bw - 1, self._bh - 1, r),
            smooth=True, splinesteps=16, fill=color, outline="",
        )
        self.create_text(
            self._bw // 2, self._bh // 2, text=self.text,
            fill=self.fg, font=("Segoe UI", 9),
        )

    def _enter(self, event):
        self._bhovering = True
        self._draw()

    def _leave(self, event):
        self._bhovering = False
        self._draw()


class ModernToggle(tk.Canvas):
    def __init__(self, master, variable, bg="#141416", scale=1.0):
        self.scale = float(scale)
        self._tw = int(round(42 * self.scale))
        self._th = int(round(24 * self.scale))
        super().__init__(
            master, width=self._tw, height=self._th,
            bg=bg, highlightthickness=0, bd=0, cursor="hand2",
        )
        self.var = variable
        self.var.trace_add("write", lambda *a: self._draw())
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        track = "#0a84ff" if on else "#3a3a42"
        r = self._th // 2
        self.create_polygon(
            _round_points(1, 1, self._tw - 1, self._th - 1, r),
            smooth=True, splinesteps=16, fill=track, outline="",
        )
        kr = r - int(round(4 * self.scale))
        cy = self._th // 2
        if on:
            cx = self._tw - r
        else:
            cx = r
        self.create_oval(
            cx - kr, cy - kr, cx + kr, cy + kr, fill="#ffffff", outline="",
        )

    def _toggle(self, event=None):
        self.var.set(not bool(self.var.get()))


def create_view(root, cfg, on_toggle, on_settings, on_copy, on_close,
                on_sensitivity=None, logger=None, show=True):
    log = logger or _log_none
    base_scale = system_scale()
    mode = str(cfg.get("ui", "auto")).lower()
    if mode != "classico":
        try:
            try:
                factor = float(cfg.get("ui_scale", DEFAULT_UI_SCALE))
            except Exception:
                factor = DEFAULT_UI_SCALE
            factor = _clamp(factor, 0.5, 1.0)
            view = NativeWidget(
                root, cfg, base_scale * factor, on_toggle, on_settings,
                on_copy, on_close, on_sensitivity=on_sensitivity,
                logger=log, show=show,
            )
            view.settings_scale = base_scale
            log("interface moderna ativa (widget em camada nativa)")
            return view
        except Exception as exc:
            log(f"interface moderna indisponivel ({exc}); "
                f"usando a interface classica")
    try:
        view = ClassicWidget(
            root, cfg, base_scale, on_toggle, on_settings,
            on_copy, on_close, on_sensitivity=on_sensitivity,
            logger=log, show=show,
        )
        log("interface classica ativa")
        return view
    except Exception as exc:
        raise RuntimeError(f"nao foi possivel criar a interface: {exc}")
