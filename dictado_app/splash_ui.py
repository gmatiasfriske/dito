"""Pill de carregamento em processo separado.

O modelo do Dictado demora para subir no boot. Nesse periodo, a rodinha
nao depende do processo principal: roda em um processo proprio (Tk) e
continua lisa mesmo quando o carregamento usa todo o CPU/GPU.
O app principal cria este processo, mostra a pílula e fecha com a linha
"quit" no stdin. Se o processo principal morrer, a pílula sai junto.
No modo executavel empacotado, o proprio Dictado.exe roda com --splash.
"""
import os
import sys
import threading
import tkinter as tk

try:
    from . import widget_ui
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import widget_ui


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    factor = widget_ui.DEFAULT_UI_SCALE
    if argv:
        try:
            factor = float(argv[0])
        except Exception:
            pass
    parent_pid = 0
    try:
        parent_pid = int(os.environ.get("DICTADO_PARENT_PID", "0"))
    except Exception:
        pass
    parent_check = None
    if parent_pid:
        try:
            import psutil
            parent_check = psutil.pid_exists
        except Exception:
            parent_check = None

    widget_ui.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    widget_ui.configure_tk_scaling(root, widget_ui.system_scale())
    stop = threading.Event()

    if sys.stdin is not None and not getattr(sys, "frozen", False):
        def watch_stdin():
            try:
                sys.stdin.readline()
            except Exception:
                pass
            stop.set()

        threading.Thread(target=watch_stdin, daemon=True).start()

    try:
        view = widget_ui.create_view(
            root, {"ui": "auto", "ui_scale": factor},
            lambda: None, lambda: None,
            lambda: None, lambda: None, logger=lambda msg: None,
        )
        view.set_state(widget_ui.STATE_LOADING)
        view.show()
    except Exception:
        stop.set()

    def poll():
        alive = True
        if parent_check is not None:
            try:
                alive = parent_check(parent_pid)
            except Exception:
                alive = True
        if stop.is_set() or not alive:
            try:
                view.shutdown()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass
            return
        root.after(120, poll)

    if not stop.is_set():
        root.after(120, poll)
        root.mainloop()


if __name__ == "__main__":
    main()
