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

"""Integration test proving ARCHER2 /work auto-sync preserves original CLI arguments (T3, B1, S1, S6)."""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest


class BmtoolRelocationTest(unittest.TestCase):
    """Test suite verifying bmtool ARCHER2 relocation, loop protection, and argument preservation."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-bmtool-reloc-test-")
        self.m_fake_bin = os.path.join(self.m_temp_dir, "bin")
        os.makedirs(self.m_fake_bin, exist_ok=True)

        # Mock 'groups' command to return 'e281 archer2 users'
        self.m_fake_groups = os.path.join(self.m_fake_bin, "groups")
        with open(self.m_fake_groups, "w", encoding="utf-8") as f_g:
            f_g.write("#!/bin/sh\necho 'e281 archer2 users'\n")
        os.chmod(self.m_fake_groups, stat.S_IRWXU)

        self.m_fake_work = os.path.join(self.m_temp_dir, "work")
        os.makedirs(self.m_fake_work, exist_ok=True)

        self.m_bmtool_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "bmtool", "bmtool"
            )
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def testArcher2RelocationPreservesCliArgumentsAndDeletesStaleFiles(self) -> None:
        """Asserts bmtool mirrors tools with --delete and passes original $@ arguments to re-exec."""
        # 1. Pre-populate a stale file in target to verify rsync --delete
        f_stale_file = os.path.join(self.m_fake_work, "tools", "stale_file.txt")
        os.makedirs(os.path.dirname(f_stale_file), exist_ok=True)
        with open(f_stale_file, "w", encoding="utf-8") as f_s:
            f_s.write("stale\n")
        self.assertTrue(os.path.isfile(f_stale_file))

        f_env = os.environ.copy()
        f_env["PATH"] = f"{self.m_fake_bin}:{f_env.get('PATH', '')}"
        f_env["ARCHER2_WORK_ROOT"] = self.m_fake_work
        f_env["BM_HOME_PREFIXES"] = os.path.dirname(
            os.path.realpath(self.m_bmtool_path)
        )
        f_env["SB_EMAIL"] = "test@example.com"
        f_env["SB_ACCOUNT"] = "e281"
        f_env.pop("BM_RELOCATED", None)

        # 2. Invoke with arguments that trigger a specific downstream error if arguments are preserved:
        # 'run nonexistent_tool small' should produce:
        #   [bmtool] ARCHER2 notice: compute nodes cannot access /home.
        #   [bmtool] Auto-syncing tools to <work>/tools...
        #   [bmtool] Handing off execution to <work>/tools/bmtool/bmtool...
        # followed by the re-exec'd binary rejecting 'nonexistent_tool':
        #   ERROR: Invalid benchmark tool: nonexistent_tool
        # If arguments were lost (the B1 bug), the re-exec received 0 arguments and printed help instead!
        f_result = subprocess.run(
            ["/bin/sh", self.m_bmtool_path, "run", "nonexistent_tool", "small"],
            env=f_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        f_combined = f_result.stdout + "\n" + f_result.stderr
        self.assertIn("ARCHER2 notice: compute nodes cannot access /home.", f_combined)
        self.assertIn("Auto-syncing tools to", f_combined)
        self.assertIn("Handing off execution to", f_combined)
        # Proof that original arguments were passed to re-exec:
        self.assertIn(
            "ERROR: Please pass either ior, lsmio, or lmp as a first cmd argument.",
            f_combined,
        )
        self.assertEqual(f_result.returncode, 1)

        # 3. Verify target tools directory exists and stale file was removed via --delete
        f_mirrored_bmtool = os.path.join(
            self.m_fake_work, "tools", "bmtool", "bmtool"
        )
        self.assertTrue(os.path.isfile(f_mirrored_bmtool))
        self.assertFalse(
            os.path.isfile(f_stale_file),
            "stale_file.txt should have been deleted by rsync --delete",
        )

    def testLoopGuardPreventsInfiniteReExec(self) -> None:
        """Asserts that BM_RELOCATED=1 suppresses relocation intercept."""
        f_env = os.environ.copy()
        f_env["PATH"] = f"{self.m_fake_bin}:{f_env.get('PATH', '')}"
        f_env["ARCHER2_WORK_ROOT"] = self.m_fake_work
        f_env["BM_HOME_PREFIXES"] = os.path.dirname(
            os.path.realpath(self.m_bmtool_path)
        )
        f_env["BM_RELOCATED"] = "1"

        f_result = subprocess.run(
            ["/bin/sh", self.m_bmtool_path, "run", "--help"],
            env=f_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        f_combined = f_result.stdout + "\n" + f_result.stderr
        self.assertNotIn("Auto-syncing tools to", f_combined)
        self.assertEqual(f_result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
