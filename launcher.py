"""Ponto de entrada do Dictado empacotado.

O mesmo executavel tambem roda como splash de carregamento:
    Dictado.exe --splash 0.8
Assim a animacao fica em outro processo sem precisar de um segundo exe.
"""
import sys


def main():
    args = sys.argv[1:]
    try:
        if args and args[0] == "--splash":
            from splash_ui import main as splash_main
            splash_main(args[1:])
            return
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
            with open("dictado_falha_inicio.txt", "a",
                      encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
