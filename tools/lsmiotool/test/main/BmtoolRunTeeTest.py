#
# Copyright 2026 Serdar Bulut
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

"""Tests bmtool's run_tee: the benchmark's exit status reaches srun, not tee's."""

import os
import shutil
import subprocess
import tempfile
import unittest


class BmtoolRunTeeTest(unittest.TestCase):
    """run_tee LOG CMD... logs CMD's output like `| tee LOG` but returns CMD's status."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp()
        self.m_helper = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "bmtool",
                "include",
                "run-tee.in.sh",
            )
        )
        self.m_log = os.path.join(self.m_temp_dir, "out-native-4-1M.txt")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _runTee(
        self, f_cmd: str, f_shell_flags: str = ""
    ) -> subprocess.CompletedProcess:
        """Source the helper in POSIX sh and run `run_tee LOG sh -c f_cmd`; print its status."""
        f_script = '. "$1"; run_tee "$2" sh -c "$3"; echo "rc=$?"'
        f_argv = ["sh"]
        if f_shell_flags:
            f_argv.append(f_shell_flags)
        f_argv += ["-c", f_script, "sh", self.m_helper, self.m_log, f_cmd]
        return subprocess.run(f_argv, capture_output=True, text=True, timeout=30)

    def _assertStatus(self, f_res: subprocess.CompletedProcess, f_status: int) -> None:
        """The whole `rc=N` line must match, so rc=1 does not also accept rc=127."""
        self.assertRegex(f_res.stdout, rf"(?m)^rc={f_status}$")

    def testFailureStatusPropagatesAndOutputIsLogged(self) -> None:
        f_res = self._runTee("echo to-stdout; echo to-stderr >&2; exit 7")
        self._assertStatus(f_res, 7)
        with open(self.m_log, encoding="utf-8") as f_log:
            f_logged = f_log.read()
        self.assertIn("to-stdout", f_logged)
        self.assertIn("to-stderr", f_logged)

    def testSuccessReturnsZeroAndLeavesNoStatusFile(self) -> None:
        f_res = self._runTee("echo ok")
        self._assertStatus(f_res, 0)
        self.assertEqual(os.listdir(self.m_temp_dir), [os.path.basename(self.m_log)])

    def testSignalStatusPropagates(self) -> None:
        f_res = self._runTee("kill -TERM $$")
        self._assertStatus(f_res, 143)

    def testShellTraceStaysOutOfLog(self) -> None:
        f_res = self._runTee("echo traced", f_shell_flags="-x")
        self._assertStatus(f_res, 0)
        with open(self.m_log, encoding="utf-8") as f_log:
            f_logged = f_log.read()
        self.assertEqual(f_logged, "traced\n")
        self.assertIn("run_tee", f_res.stderr)

    def testUnwritableLogDirectoryFails(self) -> None:
        """A missing log directory also blocks the status file; no status file counts as failure."""
        self.m_log = os.path.join(self.m_temp_dir, "missing", "out.txt")
        f_res = self._runTee("echo lost")
        self._assertStatus(f_res, 1)


if __name__ == "__main__":
    unittest.main()
