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

"""Tests bmtool's backend list check for 'lsmio backends' (unknown, duplicate, empty)."""

import os
import subprocess
import unittest


class BmtoolBackendsTest(unittest.TestCase):
    """bmtool rejects a bad backend list before loading the HPC environment."""

    def setUp(self) -> None:
        self.m_bmtool_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "bmtool", "bmtool"
            )
        )

    def _parseBackends(self, f_backends: str) -> subprocess.CompletedProcess:
        """Run 'bmtool parse lsmio backends small <list> --no-such-option'.

        The unknown option makes bmtool stop right after the backend check, so a
        list that passes never reaches the HPC environment or the archive.
        """
        f_env = os.environ.copy()
        # ARCHER2 relocation only fires for 'run'; set anyway so a future change to the
        # relocation condition can't re-exec on ARCHER2
        f_env["BM_RELOCATED"] = "1"
        f_env["SB_EMAIL"] = "test@example.com"
        f_env["SB_ACCOUNT"] = "test"
        return subprocess.run(
            [
                "/bin/sh",
                self.m_bmtool_path,
                "parse",
                "lsmio",
                "backends",
                "small",
                f_backends,
                "--no-such-option",
            ],
            env=f_env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _assertFailsWith(self, f_backends: str, f_error: str) -> None:
        f_res = self._parseBackends(f_backends)
        self.assertEqual(f_res.returncode, 1)
        self.assertIn(f"ERROR: {f_error}", f_res.stdout)

    def testUnknownBackendIsRejected(self) -> None:
        for f_backends, f_token in (
            ("native,foo", "foo"),
            ("*", "*"),
            ("Native", "Native"),
        ):
            with self.subTest(backends=f_backends):
                self._assertFailsWith(f_backends, f"Unknown backend: [{f_token}].")

    def testDuplicateBackendIsRejected(self) -> None:
        """adios and adios2 are the same backend, so listing both is a duplicate."""
        for f_backends, f_token in (
            ("plugin,plugin", "plugin"),
            ("adios,adios2", "adios2"),
        ):
            with self.subTest(backends=f_backends):
                self._assertFailsWith(
                    f_backends, f"Backend listed twice: [{f_token}] in [{f_backends}]"
                )

    def testEmptyListIsRejected(self) -> None:
        for f_backends in ("", ","):
            with self.subTest(backends=f_backends):
                self._assertFailsWith(f_backends, f"No backends given: [{f_backends}]")

    def testValidListPassesTheCheck(self) -> None:
        """A valid list reaches the option parsing that follows the check."""
        for f_backends in ("adios2,native,plugin,rocksdb", "adios,leveldb"):
            with self.subTest(backends=f_backends):
                self._assertFailsWith(
                    f_backends, "Unknown argument for parse cmd: [--no-such-option]"
                )


if __name__ == "__main__":
    unittest.main()
