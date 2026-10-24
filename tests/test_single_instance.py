import unittest
from unittest import mock

from dictado_app import dictado


class FakeProc:
    def __init__(self, pid, name, cmdline):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline}


class FakePsutilProcess:
    def __init__(self, pid, parents=()):
        self.pid = pid
        self._parents = list(parents)

    def parents(self):
        return [FakePsutilProcess(pid) for pid in self._parents]


class SingleInstanceTest(unittest.TestCase):
    def _run(self, procs, me=100, ppid=50, parents=(50,)):
        with mock.patch.object(dictado.os, "getpid", return_value=me), \
             mock.patch.object(dictado.os, "getppid", return_value=ppid), \
             mock.patch("psutil.process_iter", return_value=procs), \
             mock.patch(
                 "psutil.Process",
                 return_value=FakePsutilProcess(me, parents),
             ):
            return dictado._other_dictado_process()

    def test_ignores_venv_launcher_parent(self):
        procs = [
            FakeProc(
                100, "pythonw.exe",
                ["pythonw.exe", r"E:\APP\MIC\dictado.py"],
            ),
            FakeProc(
                50, "pythonw.exe",
                [
                    r"E:\APP\MIC\.venv\Scripts\pythonw.exe",
                    r"E:\APP\MIC\dictado.py",
                ],
            ),
        ]
        self.assertFalse(self._run(procs))

    def test_detects_real_second_instance(self):
        procs = [
            FakeProc(
                100, "pythonw.exe",
                ["pythonw.exe", r"E:\APP\MIC\dictado.py"],
            ),
            FakeProc(
                60, "python.exe",
                ["python.exe", r"E:\APP\MIC\dictado.py"],
            ),
        ]
        self.assertTrue(self._run(procs))

    def test_ignores_unrelated_process_with_text_in_command(self):
        procs = [
            FakeProc(
                100, "pythonw.exe",
                ["pythonw.exe", r"E:\APP\MIC\dictado.py"],
            ),
            FakeProc(
                70, "powershell.exe",
                ["powershell.exe", "-Command", "Get-Content dictado.py"],
            ),
        ]
        self.assertFalse(self._run(procs))


if __name__ == "__main__":
    unittest.main()

