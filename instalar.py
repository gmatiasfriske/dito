"""Instalador do Dictado para Windows.

Execute pelo arquivo 1-INSTALAR-PRIMEIRO.bat. Ele cria o ambiente
isolado .venv, escolhe o PyTorch CUDA ou CPU, instala as dependencias e
cria um atalho na Area de Trabalho.
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
VENV_PYW = VENV / "Scripts" / "pythonw.exe"
REQ = ROOT / "requirements.txt"

TORCH_VERSION = "2.9.1"
TORCHAUDIO_VERSION = "2.9.1"
TORCH_GPU_INDEX = "https://download.pytorch.org/whl/cu128"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def out(msg=""):
    print(msg, flush=True)


def fail(msg):
    out()
    out("ERRO: " + msg)
    return 1


def run(cmd):
    out()
    out("> " + subprocess.list2cmdline([str(c) for c in cmd]))
    try:
        return subprocess.call(
            [str(c) for c in cmd],
            cwd=str(ROOT),
            env=child_env(),
        )
    except Exception as exc:
        out(f"Falha ao executar: {exc}")
        return 1


def child_env():
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return env


def capture(cmd):
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            cwd=str(ROOT),
            env=child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout or ""
    except Exception as exc:
        return 1, str(exc)


def detect_nvidia():
    candidates = []
    found = shutil.which("nvidia-smi")
    if found:
        candidates.append(Path(found))
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates.append(
        Path(program_files) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"
    )
    for exe in candidates:
        if not exe.is_file():
            continue
        code, text = capture([
            exe, "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader",
        ])
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if code == 0 and lines:
            return lines
    return []


def torch_cuda_ready(python_exe):
    code, text = capture([
        python_exe, "-c",
        "import torch; print(torch.__version__); "
        "print(1 if torch.cuda.is_available() else 0)",
    ])
    if code != 0:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    return lines[-2], lines[-1] == "1"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    check_only = "--check" in sys.argv
    force_cpu = "--cpu" in sys.argv
    no_shortcut = "--no-shortcut" in sys.argv

    out("=" * 62)
    out(" DICTADO - INSTALADOR")
    out("=" * 62)
    out()

    if platform.system() != "Windows":
        return fail("este aplicativo foi feito para Windows 10/11.")
    if platform.architecture()[0] != "64bit":
        return fail("e necessario um Python 64 bits.")

    version = sys.version_info[:2]
    out(f"Python encontrado: {platform.python_version()} ({sys.executable})")
    if version < (3, 11) or version >= (3, 13):
        return fail(
            "use Python 3.11 ou 3.12. O instalador 1-INSTALAR-PRIMEIRO.bat "
            "pode instalar o 3.11 automaticamente."
        )
    if not REQ.is_file():
        return fail("arquivo requirements.txt nao encontrado.")

    free = shutil.disk_usage(ROOT).free
    out(f"Espaco livre na pasta: {free / (1024 ** 3):.1f} GB")
    if free < 8 * 1024 ** 3:
        out("AVISO: recomendado pelo menos 8 GB livres para PyTorch + modelo.")

    gpu_lines = [] if force_cpu else detect_nvidia()
    if gpu_lines:
        out("Placa NVIDIA encontrada:")
        for line in gpu_lines:
            out("  " + line)
    elif force_cpu:
        out("Modo CPU forcado (--cpu). A transcricao sera bem mais lenta.")
    else:
        out("Nenhuma NVIDIA encontrada via nvidia-smi.")
        out("O Dictado sera instalado em modo CPU (bem mais lento).")

    if check_only:
        out()
        out("Verificacao concluida. Nada foi instalado (--check).")
        return 0

    if not VENV_PY.is_file():
        if VENV.exists():
            return fail(
                "a pasta .venv existe mas esta incompleta. "
                "Apague a pasta .venv e execute este instalador de novo."
            )
        out()
        out("Criando ambiente isolado em .venv ...")
        rc = run([sys.executable, "-m", "venv", str(VENV)])
        if rc != 0 or not VENV_PY.is_file():
            return fail("nao foi possivel criar o .venv.")
    else:
        out()
        out("Ambiente .venv existente; atualizando a instalacao.")

    out()
    out("Atualizando pip/setuptools/wheel ...")
    rc = run([
        VENV_PY, "-m", "pip", "install", "--upgrade",
        "pip", "setuptools", "wheel",
    ])
    if rc != 0:
        return fail("falha ao atualizar o pip.")

    state = torch_cuda_ready(VENV_PY)
    need_torch = state is None
    if state is not None and gpu_lines and not state[1]:
        out()
        out("PyTorch sem CUDA encontrado; reinstalando a versao NVIDIA...")
        run([VENV_PY, "-m", "pip", "uninstall", "-y", "torch", "torchaudio"])
        need_torch = True
    elif state is not None:
        out(f"PyTorch ja instalado: {state[0]} "
            f"(cuda={state[1]})")

    if need_torch:
        if gpu_lines:
            out()
            out("Instalando PyTorch com CUDA 12.8 (pode demorar varios minutos)...")
            rc = run([
                VENV_PY, "-m", "pip", "install",
                f"torch=={TORCH_VERSION}",
                f"torchaudio=={TORCHAUDIO_VERSION}",
                "--index-url", TORCH_GPU_INDEX,
            ])
            if rc != 0:
                out()
                out("Falhou o PyTorch CUDA. Tentando a versao CPU como reserva...")
                rc = run([
                    VENV_PY, "-m", "pip", "install",
                    f"torch=={TORCH_VERSION}",
                    f"torchaudio=={TORCHAUDIO_VERSION}",
                    "--index-url", TORCH_CPU_INDEX,
                ])
                if rc == 0:
                    gpu_lines = []
        else:
            out()
            out("Instalando PyTorch CPU (pode demorar alguns minutos)...")
            rc = run([
                VENV_PY, "-m", "pip", "install",
                f"torch=={TORCH_VERSION}",
                f"torchaudio=={TORCHAUDIO_VERSION}",
                "--index-url", TORCH_CPU_INDEX,
            ])
        if rc != 0:
            return fail(
                "nao foi possivel instalar o PyTorch. "
                "Verifique a internet e tente de novo."
            )

    out()
    out("Instalando dependencias do Dictado ...")
    rc = run([VENV_PY, "-m", "pip", "install", "-r", str(REQ)])
    if rc != 0:
        return fail("falha ao instalar requirements.txt.")

    out()
    out("Verificando a instalacao ...")
    verify_code = (
        "import sys, torch, transformers, crisperwhisper, numpy, PIL, "
        "sounddevice, keyboard, pyperclip, noisereduce, soundfile\n"
        "print('python', sys.version.split()[0])\n"
        "print('torch', torch.__version__)\n"
        "print('cuda', torch.cuda.is_available())\n"
        "print('transformers', transformers.__version__)\n"
        "print('crisperwhisper ok')\n"
        "print('interface ok')\n"
    )
    rc, text = capture([VENV_PY, "-c", verify_code])
    if text.strip():
        out(text.strip())
    if rc != 0:
        return fail("a verificacao dos imports falhou.")

    cuda_ok = "cuda True" in text
    if gpu_lines and not cuda_ok:
        out()
        out("AVISO: a NVIDIA foi encontrada, mas o PyTorch nao conseguiu")
        out("usar a CUDA. Atualize o driver da placa e tente de novo.")
    elif not gpu_lines:
        out()
        out("AVISO: instalacao em CPU. Transcrever audios sera bem lento.")

    if not no_shortcut:
        out()
        out("Criando atalho 'Dictado' na Area de Trabalho ...")
        if create_shortcut():
            out("Atalho criado.")
        else:
            out("Nao consegui criar o atalho; use 2-ABRIR-DICTADO.bat.")

    out()
    out("=" * 62)
    out(" INSTALACAO CONCLUIDA!")
    out("=" * 62)
    out("Abra pelo atalho 'Dictado' ou pelo arquivo 2-ABRIR-DICTADO.bat.")
    out("Na primeira abertura, o modelo (~2 GB) sera baixado.")
    out("A pilula fica cinza carregando e fica verde quando estiver pronta.")
    return 0


def create_shortcut():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False

    def q(value):
        return "'" + str(value).replace("'", "''") + "'"

    script = "\n".join([
        "$ws = New-Object -ComObject WScript.Shell",
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        "$lnk = $ws.CreateShortcut((Join-Path $desktop 'Dictado.lnk'))",
        f"$lnk.TargetPath = {q(VENV_PYW)}",
        f"$lnk.Arguments = {q(chr(34) + str(ROOT / 'dictado.py') + chr(34))}",
        f"$lnk.WorkingDirectory = {q(ROOT)}",
        f"$lnk.IconLocation = {q(ROOT / 'dictado.ico')}",
        "$lnk.Description = 'Dictado - ditado por voz'",
        "$lnk.Save()",
    ])
    rc = run([
        powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-Command", script,
    ])
    return rc == 0


if __name__ == "__main__":
    sys.exit(main())
