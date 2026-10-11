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

"""Unit tests for ARCHER2 relocation of the worker tree off /home (H11, bmtool:112-142)."""

import os
import shutil
import stat
import tempfile
import unittest
from typing import Any, List

from lsmiotool.lib.relocate import (
    RelocationError,
    buildRsyncArgv,
    homePrefixes,
    isUnderHomePrefix,
    planRelocation,
    relocateForSite,
)
from lsmiotool.lib.resources import ResourceLocator
from lsmiotool.lib.site import EnvironmentResolver


_INSTALLED_WORKER = """#!/usr/bin/env python3
REL_LIBEXEC_TO_PYTHON = "../../share/lsmio/python"
REL_LIBEXEC_TO_PROFILE = "../../share/lsmio/etc/environments.json"
REL_LIBEXEC_TO_ETC = "../../share/lsmio/etc/environments.json"
REL_LIBEXEC_TO_ASSETS = "../../share/lsmio/lmp-reaxff"
REL_LIBEXEC_TO_WORKER = "lsmiotool-worker"
REL_LIBEXEC_TO_VERSION = "../../share/lsmio/python/lsmiotool/VERSION"
"""


class _RecordingRunner:
    """Records rsync argv and mirrors the trees with shutil (no rsync dependency)."""

    def __init__(self, f_returncode: int = 0) -> None:
        self.m_calls: List[List[str]] = []
        self.m_returncode = f_returncode

    def __call__(self, f_argv: List[str]) -> Any:
        self.m_calls.append(list(f_argv))
        if self.m_returncode == 0:
            shutil.copytree(f_argv[-2], f_argv[-1], symlinks=True, dirs_exist_ok=True)
        return self.m_returncode


def _writeExecutable(f_path: str, f_text: str) -> None:
    os.makedirs(os.path.dirname(f_path), exist_ok=True)
    with open(f_path, "w", encoding="utf-8") as f_f:
        f_f.write(f_text)
    os.chmod(f_path, stat.S_IRWXU)


def _writeFile(f_path: str, f_text: str = "x\n") -> None:
    os.makedirs(os.path.dirname(f_path), exist_ok=True)
    with open(f_path, "w", encoding="utf-8") as f_f:
        f_f.write(f_text)


class RelocateTest(unittest.TestCase):
    """Tests relocateForSite source/installed layouts, gating, and failure handling."""

    def setUp(self) -> None:
        self.m_temp = os.path.realpath(tempfile.mkdtemp(prefix="lsmiotool-reloc-"))
        self.m_home = os.path.join(self.m_temp, "home", "alice")
        self.m_work = os.path.join(self.m_temp, "work", "alice")
        os.makedirs(self.m_work)
        self.m_env = {
            "USER": "alice",
            "ARCHER2_WORK_ROOT": self.m_work,
            "BM_HOME_PREFIXES": os.path.join(self.m_temp, "home"),
        }
        self.m_archer2 = EnvironmentResolver.resolveProfile(
            "ARCHER2", f_user="alice", f_home=self.m_home
        )
        self.m_viking2 = EnvironmentResolver.resolveProfile(
            "VIKING2", f_user="alice", f_home=self.m_home
        )

        # Source checkout below the fake home
        self.m_repo = os.path.join(self.m_home, "src", "lsmio")
        self.m_pkg = os.path.join(self.m_repo, "tools", "lsmiotool")
        self.m_src_worker = os.path.join(self.m_pkg, "lsmiotool-worker")
        _writeExecutable(self.m_src_worker, "#!/usr/bin/env python3\n")
        _writeFile(os.path.join(self.m_pkg, "__init__.py"))
        _writeFile(os.path.join(self.m_pkg, "lib", "__init__.py"))
        _writeFile(os.path.join(self.m_pkg, "VERSION"), "0.3.0\n")
        _writeFile(os.path.join(self.m_pkg, "run.log"))
        self.m_assets = os.path.join(self.m_pkg, "share", "lmp-reaxff")
        _writeFile(os.path.join(self.m_assets, "in.reaxc"))

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp, ignore_errors=True)

    def testHomePrefixesAndRsyncArgv(self) -> None:
        """/home is always a prefix (string match like bmtool's /home*); BM_HOME_PREFIXES adds more."""
        self.assertEqual(homePrefixes({}), ("/home",))
        self.assertEqual(
            homePrefixes({"BM_HOME_PREFIXES": "/a::/b"}), ("/home", "/a", "/b")
        )
        self.assertTrue(isUnderHomePrefix("/home2/u/x", {}))
        self.assertTrue(isUnderHomePrefix("/a/x", {"BM_HOME_PREFIXES": "/a"}))
        self.assertFalse(isUnderHomePrefix("/work/e281/x", {}))
        self.assertEqual(
            buildRsyncArgv("/home/u/tools/lsmiotool", "/work/u/tools/lsmiotool/"),
            [
                "rsync",
                "-a",
                "--delete",
                "--exclude=*.log",
                "--exclude=*.err",
                "/home/u/tools/lsmiotool/",
                "/work/u/tools/lsmiotool/",
            ],
        )
        with self.assertRaises(RelocationError):
            buildRsyncArgv("relative", "/work")

    def testNonArcher2OrNonHomeWorkerIsUnchanged(self) -> None:
        """Only ARCHER2 workers under a home prefix relocate; nothing runs otherwise."""
        f_runner = _RecordingRunner()
        self.assertEqual(
            relocateForSite(self.m_viking2, self.m_src_worker, self.m_env, f_runner),
            self.m_src_worker,
        )
        f_work_worker = os.path.join(
            self.m_work, "tools", "lsmiotool", "lsmiotool-worker"
        )
        self.assertEqual(
            relocateForSite(self.m_archer2, f_work_worker, self.m_env, f_runner),
            f_work_worker,
        )
        f_no_prefix_env = {"USER": "alice", "ARCHER2_WORK_ROOT": self.m_work}
        self.assertEqual(
            relocateForSite(
                self.m_archer2, self.m_src_worker, f_no_prefix_env, f_runner
            ),
            self.m_src_worker,
        )
        self.assertEqual(f_runner.m_calls, [])

    def testSourceLayoutRelocatesPackageAndAssets(self) -> None:
        """Source worker mirrors tools/lsmiotool, its share/lmp-reaxff assets included, under <work>/tools."""
        f_runner = _RecordingRunner()
        f_new = relocateForSite(self.m_archer2, self.m_src_worker, self.m_env, f_runner)

        f_tools = os.path.join(self.m_work, "tools")
        self.assertEqual(f_new, os.path.join(f_tools, "lsmiotool", "lsmiotool-worker"))
        self.assertEqual(
            f_runner.m_calls,
            [
                buildRsyncArgv(self.m_pkg, os.path.join(f_tools, "lsmiotool")),
            ],
        )
        self.assertTrue(os.access(f_new, os.X_OK))
        # The relocated worker resolves the same relative layout via ResourceLocator
        f_layout = ResourceLocator.forSource(f_new)
        self.assertTrue(os.path.isfile(os.path.join(f_layout.asset_root, "in.reaxc")))
        self.assertTrue(os.path.isfile(os.path.join(f_layout.package_root, "VERSION")))

        # Site name strings are accepted as well
        self.assertEqual(
            relocateForSite(
                "archer2", self.m_src_worker, self.m_env, _RecordingRunner()
            ),
            f_new,
        )

    @unittest.skipIf(shutil.which("rsync") is None, "rsync not available")
    def testSourceLayoutWithRealRsyncDeletesStaleAndExcludesLogs(self) -> None:
        """Default runner: rsync --delete removes stale files and skips *.log/*.err like bmtool."""
        f_stale = os.path.join(self.m_work, "tools", "lsmiotool", "stale.txt")
        _writeFile(f_stale)
        f_new = relocateForSite(self.m_archer2, self.m_src_worker, self.m_env)
        f_dest = os.path.dirname(f_new)
        self.assertTrue(os.access(f_new, os.X_OK))
        self.assertFalse(os.path.exists(f_stale))
        self.assertFalse(os.path.exists(os.path.join(f_dest, "run.log")))
        self.assertTrue(os.path.isfile(os.path.join(f_dest, "lib", "__init__.py")))

    def testInstalledLayoutPreservesRelativeLinks(self) -> None:
        """Installed worker mirrors libexec/lsmio and share/lsmio/* below <work>/tools/lsmiotool."""
        f_prefix = os.path.join(self.m_home, "usr")
        f_worker = os.path.join(f_prefix, "libexec", "lsmio", "lsmiotool-worker")
        _writeExecutable(f_worker, _INSTALLED_WORKER)
        f_share = os.path.join(f_prefix, "share", "lsmio")
        _writeFile(os.path.join(f_share, "python", "lsmiotool", "VERSION"), "0.3.0\n")
        _writeFile(os.path.join(f_share, "etc", "environments.json"), "{}\n")
        _writeFile(os.path.join(f_share, "lmp-reaxff", "in.reaxc"))

        f_runner = _RecordingRunner()
        f_new = relocateForSite(self.m_archer2, f_worker, self.m_env, f_runner)

        f_dest = os.path.join(self.m_work, "tools", "lsmiotool")
        self.assertEqual(
            f_new, os.path.join(f_dest, "libexec", "lsmio", "lsmiotool-worker")
        )
        f_sources = sorted(f_call[-2] for f_call in f_runner.m_calls)
        self.assertEqual(
            f_sources,
            sorted(
                [
                    os.path.join(f_prefix, "libexec", "lsmio") + "/",
                    os.path.join(f_share, "python") + "/",
                    os.path.join(f_share, "etc") + "/",
                    os.path.join(f_share, "lmp-reaxff") + "/",
                ]
            ),
        )
        f_anchor = os.path.dirname(f_new)
        for f_rel in (
            "../../share/lsmio/python/lsmiotool/VERSION",
            "../../share/lsmio/etc/environments.json",
            "../../share/lsmio/lmp-reaxff/in.reaxc",
        ):
            self.assertTrue(
                os.path.isfile(os.path.normpath(os.path.join(f_anchor, f_rel)))
            )

    def testPlanSkipsMissingAssets(self) -> None:
        """Without its assets the source package is still the only mirrored directory."""
        shutil.rmtree(self.m_assets)
        f_pairs, f_new = planRelocation(
            self.m_src_worker, os.path.join(self.m_work, "tools")
        )
        self.assertEqual(
            f_pairs, [(self.m_pkg, os.path.join(self.m_work, "tools", "lsmiotool"))]
        )
        self.assertEqual(
            f_new,
            os.path.join(self.m_work, "tools", "lsmiotool", "lsmiotool-worker"),
        )

    def testFailuresRaiseRelocationError(self) -> None:
        """A failing rsync, a missing relocated worker, or a work root under /home fail closed."""
        with self.assertRaises(RelocationError):
            relocateForSite(
                self.m_archer2, self.m_src_worker, self.m_env, _RecordingRunner(23)
            )
        with self.assertRaises(RelocationError):
            relocateForSite(
                self.m_archer2, self.m_src_worker, self.m_env, lambda f_argv: 0
            )
        f_env = dict(self.m_env)
        f_env["ARCHER2_WORK_ROOT"] = os.path.join(self.m_temp, "home", "alice", "w")
        f_runner = _RecordingRunner()
        with self.assertRaises(RelocationError):
            relocateForSite(self.m_archer2, self.m_src_worker, f_env, f_runner)
        self.assertEqual(f_runner.m_calls, [])
        with self.assertRaises(RelocationError):
            relocateForSite(self.m_archer2, "relative/worker", self.m_env, f_runner)


if __name__ == "__main__":
    unittest.main()
