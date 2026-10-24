"""Ponto de entrada do Dictado empacotado.

O mesmo executavel tambem roda como splash de carregamento:
    Dictado.exe --splash 0.8
Assim a animacao fica em outro processo sem precisar de um segundo exe.
"""
import os
import sys


def main():
    args = sys.argv[1:]
    try:
        if args and args[0] == "--splash":
            try:
                from .splash_ui import main as splash_main
            except ImportError:
                from splash_ui import main as splash_main
            splash_main(args[1:])
            return
        try:
            from .dictado import main as app_main
        except ImportError:
            from dictado import main as app_main
        app_main()
    except Exception as exc:
        import traceback
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "Nao foi possivel iniciar o Dictado.\n\n"
                f"{exc}\n\n"
                "Veja dictado.log para mais detalhes.",
                "Dictado", 0x10 | 0x40000,
            )
        except Exception:
            pass
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            if getattr(sys, "frozen", False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(base)
            with open(os.path.join(base, "dictado_falha_inicio.txt"), "a",
                      encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
