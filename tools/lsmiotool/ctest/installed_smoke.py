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

"""Isolated smoke test for staged lsmiotool installation.

This script is invoked exclusively by CTest fixture 'lsmiotool_installed_smoke'.
It is placed outside lsmiotool.test, has no __init__.py in its directory, and
does not match test discovery patterns ('test*.py', '*Test.py', 'Test*.py').
"""

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Sequence
import unittest


class InstalledSmoke(unittest.TestCase):
    """Smoke test suite exercising installed layout, wrappers, profiles, assets, and validators."""

    m_stage_dir: str = ""
    m_work_dir: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.m_stage_dir:
            raise ValueError("InstalledSmoke.m_stage_dir must be configured before running tests.")
        if not cls.m_work_dir:
            raise ValueError("InstalledSmoke.m_work_dir must be configured before running tests.")

        # Ensure staged python directory is inserted at the front of sys.path
        f_staged_python = os.path.normpath(os.path.join(cls.m_stage_dir, "share", "lsmio", "python"))
        if f_staged_python not in sys.path:
            sys.path.insert(0, f_staged_python)

    def testOnlyStagedPathsLoaded(self) -> None:
        """Verify that importing lsmiotool loads exclusively from the staged installation layout."""
        f_staged_python = os.path.normpath(os.path.join(self.m_stage_dir, "share", "lsmio", "python"))
        
        # Test in a separate subprocess with clean environment
        f_script = (
            "import sys\n"
            f"sys.path.insert(0, {f_staged_python!r})\n"
            "import lsmiotool\n"
            "import lsmiotool.lib.benchmarks\n"
            "import lsmiotool.lib.cli\n"
            "import lsmiotool.lib.hpc\n"
            "import lsmiotool.lib.log\n"
            "import lsmiotool.lib.main\n"
            "import lsmiotool.lib.profile\n"
            "import lsmiotool.lib.resources\n"
            "import lsmiotool.lib.run\n"
            "import lsmiotool.lib.scheduler\n"
            "import lsmiotool.lib.site\n"
            "import lsmiotool.lib.version\n"
            "import lsmiotool.lib.worker\n"
            "loaded_files = {\n"
            "    k: getattr(v, '__file__', None)\n"
            "    for k, v in sys.modules.items()\n"
            "    if k.startswith('lsmiotool') and getattr(v, '__file__', None)\n"
            "}\n"
            f"staged_prefix = os.path.normpath({f_staged_python!r})\n"
            "for mod_name, mod_file in loaded_files.items():\n"
            "    norm_file = os.path.normpath(mod_file)\n"
            "    if not norm_file.startswith(staged_prefix):\n"
            "        sys.stderr.write(f'Module {mod_name} loaded from {norm_file}, outside staged prefix {staged_prefix}\\n')\n"
            "        sys.exit(1)\n"
            "print(f'Successfully validated {len(loaded_files)} staged modules')\n"
        )
        f_env = os.environ.copy()
        f_env.pop("PYTHONPATH", None)

        f_proc = subprocess.run(
            [sys.executable, "-c", f"import os\n{f_script}"],
            capture_output=True,
            text=True,
            env=f_env,
        )
        self.assertEqual(
            f_proc.returncode,
            0,
            f"Subprocess verification of staged modules failed:\n{f_proc.stdout}\n{f_proc.stderr}",
        )
        self.assertIn("Successfully validated", f_proc.stdout)

    def testHelpVersionAndWorkerArity(self) -> None:
        """Verify execution of staged public and private binaries, help, version, and worker arity."""
        f_public_bin = os.path.join(self.m_stage_dir, "bin", "lsmiotool")
        f_worker_bin = os.path.join(self.m_stage_dir, "libexec", "lsmio", "lsmiotool-worker")

        self.assertTrue(os.path.isfile(f_public_bin), f"Public binary missing: {f_public_bin}")
        self.assertTrue(os.path.isfile(f_worker_bin), f"Worker binary missing: {f_worker_bin}")

        # Test --version and -v
        f_proc_ver = subprocess.run(
            [f_public_bin, "--version"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_ver.returncode, 0)
        self.assertIn("0.2.0", f_proc_ver.stdout)

        f_proc_v = subprocess.run(
            [f_public_bin, "-v"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_v.returncode, 0)
        self.assertIn("0.2.0", f_proc_v.stdout)

        # Test --help and -h
        f_proc_help = subprocess.run(
            [f_public_bin, "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_help.returncode, 0)
        self.assertIn("How to run", f_proc_help.stdout)

        f_proc_h = subprocess.run(
            [f_public_bin, "-h"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_h.returncode, 0)
        self.assertIn("How to run", f_proc_h.stdout)

        # Test worker arity: 0 arguments
        f_proc_w_empty = subprocess.run(
            [f_worker_bin],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_w_empty.returncode, 1)
        self.assertIn("Usage: lsmiotool-worker", f_proc_w_empty.stderr)

        # Test worker arity: allocation with wrong arity (1 token instead of 3)
        f_proc_w_alloc_bad = subprocess.run(
            [f_worker_bin, "allocation"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_w_alloc_bad.returncode, 2)
        self.assertIn("Usage: lsmiotool-worker allocation", f_proc_w_alloc_bad.stderr)

        # Test worker arity: rank with wrong arity (1 token instead of 4)
        f_proc_w_rank_bad = subprocess.run(
            [f_worker_bin, "rank"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_w_rank_bad.returncode, 2)
        self.assertIn("Usage: lsmiotool-worker rank", f_proc_w_rank_bad.stderr)

        # Test worker with unknown mode
        f_proc_w_unknown = subprocess.run(
            [f_worker_bin, "unsupported_mode"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(f_proc_w_unknown.returncode, 1)
        self.assertIn("Unknown worker mode", f_proc_w_unknown.stderr)

    def testProfilesAssetsHashes(self) -> None:
        """Verify profile parsing, asset validation, and asset hashing from staged layout."""
        from lsmiotool.lib.benchmarks import LmpAdapter
        from lsmiotool.lib.cli import InstalledPackageValidator, WorkerExecutableValidator
        from lsmiotool.lib.profile import ProfileLoader
        from lsmiotool.lib.version import getVersion

        # 1. Verify installed package validation
        f_pkg_root = os.path.join(self.m_stage_dir, "share", "lsmio", "python", "lsmiotool")
        f_validated_pkg = InstalledPackageValidator.validate(f_pkg_root)
        self.assertEqual(f_validated_pkg, os.path.normpath(f_pkg_root))

        # 2. Verify worker executable validation
        f_worker_bin = os.path.join(self.m_stage_dir, "libexec", "lsmio", "lsmiotool-worker")
        f_validated_worker = WorkerExecutableValidator.validate(f_worker_bin)
        self.assertEqual(f_validated_worker, os.path.normpath(f_worker_bin))

        # 3. Verify version file reading and format
        f_version_file = os.path.join(f_pkg_root, "VERSION")
        self.assertEqual(getVersion(f_version_file), "0.2.0")

        # 4. Verify profile loading
        f_profile_file = os.path.join(self.m_stage_dir, "share", "lsmio", "etc", "environments.json")
        f_doc = ProfileLoader.load(f_profile_file)
        self.assertEqual(f_doc.schema_version, 1)
        self.assertTrue({"DEV", "VIKING", "VIKING2", "ARCHER2", "ISAMBARD"}.issubset(f_doc.profiles.keys()))

        # 5. Verify LMP assets validation and hashing
        f_asset_root = os.path.join(self.m_stage_dir, "share", "lsmio", "lmp-reaxff")
        f_adapter = LmpAdapter()
        f_hashes = f_adapter.validateAssets(f_asset_root)
        self.assertEqual(set(f_hashes.keys()), {"in.reaxff.hns", "data.hns", "ffield.reax.hns"})
        for f_name, f_hash in f_hashes.items():
            self.assertEqual(len(f_hash), 64, f"Hash for {f_name} is not 64 hex characters: {f_hash}")

        # 6. Verify staging assets into a destination directory
        f_test_staging = os.path.join(self.m_work_dir, "test_lmp_staging")
        f_staged_hashes = f_adapter.stageAssets(f_asset_root, f_test_staging)
        self.assertEqual(f_staged_hashes, f_hashes)
        for f_name in ("in.reaxff.hns", "data.hns", "ffield.reax.hns"):
            f_dest_file = os.path.join(f_test_staging, f_name)
            self.assertTrue(os.path.isfile(f_dest_file), f"Staged file missing: {f_dest_file}")

    def testMissingCopiedStageResourceCannotFallback(self) -> None:
        """Verify that a damaged copied stage fails strictly without falling back to source, cwd, or home."""
        from lsmiotool.lib.benchmarks import BenchmarkConfigurationError, LmpAdapter
        from lsmiotool.lib.cli import (
            InstalledPackageValidator,
            PackageValidationError,
            WorkerExecutableValidationError,
            WorkerExecutableValidator,
        )
        from lsmiotool.lib.profile import ProfileSchemaError, ProfileLoader
        from lsmiotool.lib.version import VersionError, getVersion

        f_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-stage-copy-")
        try:
            f_copy_stage = os.path.join(f_temp_dir, "stage")
            shutil.copytree(self.m_stage_dir, f_copy_stage, symlinks=False)

            # Plant decoy files in CWD and fake HOME
            f_decoy_cwd_file = os.path.join(self.m_work_dir, "in.reaxff.hns")
            with open(f_decoy_cwd_file, "w", encoding="utf-8") as f_f:
                f_f.write("# decoy lmp asset in cwd\n")

            f_home_dir = os.environ.get("HOME", self.m_work_dir)
            f_decoy_home_file = os.path.join(f_home_dir, "VERSION")
            with open(f_decoy_home_file, "w", encoding="utf-8") as f_f:
                f_f.write("0.2.0\n")

            # Case A1: Missing required module (worker.py) -> InstalledPackageValidator raises and wrapper prints error
            f_target_worker = os.path.join(f_copy_stage, "share", "lsmio", "python", "lsmiotool", "lib", "worker.py")
            os.remove(f_target_worker)
            f_pkg_a = os.path.join(f_copy_stage, "share", "lsmio", "python", "lsmiotool")
            with self.assertRaises(PackageValidationError):
                InstalledPackageValidator.validate(f_pkg_a)
            f_proc_a = subprocess.run(
                [os.path.join(f_copy_stage, "bin", "lsmiotool"), "--help"],
                capture_output=True,
                text=True,
                cwd=self.m_work_dir,
            )
            self.assertNotEqual(f_proc_a.returncode, 0)
            self.assertIn("Package validation error", f_proc_a.stderr)

            # Case A2: Missing top-level imported module (cli.py) -> wrapper fails without falling back to source/cwd
            f_target_cli = os.path.join(f_copy_stage, "share", "lsmio", "python", "lsmiotool", "lib", "cli.py")
            os.remove(f_target_cli)
            f_proc_cli = subprocess.run(
                [os.path.join(f_copy_stage, "bin", "lsmiotool"), "--help"],
                capture_output=True,
                text=True,
                cwd=self.m_work_dir,
            )
            self.assertNotEqual(f_proc_cli.returncode, 0)

            # Case B: Missing VERSION file in copied stage -> getVersion must raise VersionError
            f_copy_b = os.path.join(f_temp_dir, "stage_b")
            shutil.copytree(self.m_stage_dir, f_copy_b, symlinks=False)
            f_ver_b = os.path.join(f_copy_b, "share", "lsmio", "python", "lsmiotool", "VERSION")
            os.remove(f_ver_b)
            with self.assertRaises(VersionError):
                getVersion(f_ver_b)
            f_proc_b = subprocess.run(
                [os.path.join(f_copy_b, "bin", "lsmiotool"), "--version"],
                capture_output=True,
                text=True,
                cwd=self.m_work_dir,
            )
            self.assertNotEqual(f_proc_b.returncode, 0)

            # Case C: Missing asset in copied stage -> validateAssets must fail
            f_copy_c = os.path.join(f_temp_dir, "stage_c")
            shutil.copytree(self.m_stage_dir, f_copy_c, symlinks=False)
            f_asset_c = os.path.join(f_copy_c, "share", "lsmio", "lmp-reaxff", "in.reaxff.hns")
            os.remove(f_asset_c)
            with self.assertRaises(BenchmarkConfigurationError):
                LmpAdapter().validateAssets(os.path.join(f_copy_c, "share", "lsmio", "lmp-reaxff"))

            # Case D: Missing profile in copied stage -> ProfileLoader must fail
            f_copy_d = os.path.join(f_temp_dir, "stage_d")
            shutil.copytree(self.m_stage_dir, f_copy_d, symlinks=False)
            f_prof_d = os.path.join(f_copy_d, "share", "lsmio", "etc", "environments.json")
            os.remove(f_prof_d)
            with self.assertRaises((ProfileSchemaError, FileNotFoundError, OSError)):
                ProfileLoader.load(f_prof_d)

            # Case E: Missing worker binary in copied stage -> WorkerExecutableValidator must fail
            f_copy_e = os.path.join(f_temp_dir, "stage_e")
            shutil.copytree(self.m_stage_dir, f_copy_e, symlinks=False)
            f_worker_e = os.path.join(f_copy_e, "libexec", "lsmio", "lsmiotool-worker")
            os.remove(f_worker_e)
            with self.assertRaises(WorkerExecutableValidationError):
                WorkerExecutableValidator.validate(f_worker_e)

        finally:
            shutil.rmtree(f_temp_dir, ignore_errors=True)

    def testLmpLargeRejectsBeforeResource(self) -> None:
        """Verify that 'lsmiotool run lmp large' is strictly rejected before any resource access."""
        f_public_bin = os.path.join(self.m_stage_dir, "bin", "lsmiotool")
        
        # Snapshot directory contents before execution
        f_before_contents = set(os.listdir(self.m_work_dir))

        f_proc = subprocess.run(
            [f_public_bin, "run", "lmp", "large"],
            capture_output=True,
            text=True,
            cwd=self.m_work_dir,
        )
        self.assertNotEqual(f_proc.returncode, 0)
        self.assertIn("LMP large scale is unsupported", f_proc.stderr)

        # Verify no benchmark runs directory or manifest was created
        f_after_contents = set(os.listdir(self.m_work_dir))
        self.assertEqual(
            f_before_contents,
            f_after_contents,
            f"Execution created unexpected files/directories in work dir: {f_after_contents - f_before_contents}",
        )


def main(f_argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for installed smoke test."""
    f_parser = argparse.ArgumentParser(description="Isolated smoke test for staged lsmiotool installation")
    f_parser.add_argument("--stage", required=True, help="Path to staged installation prefix directory")
    f_parser.add_argument("--work", required=True, help="Path to smoke working directory")
    f_args = f_parser.parse_args(f_argv)

    f_stage_abs = os.path.abspath(f_args.stage)
    f_work_abs = os.path.abspath(f_args.work)

    if not os.path.isdir(f_stage_abs):
        sys.stderr.write(f"Error: Stage directory '{f_stage_abs}' does not exist or is not a directory.\n")
        return 1

    os.makedirs(f_work_abs, exist_ok=True)

    InstalledSmoke.m_stage_dir = f_stage_abs
    InstalledSmoke.m_work_dir = f_work_abs

    f_suite = unittest.defaultTestLoader.loadTestsFromTestCase(InstalledSmoke)
    f_runner = unittest.TextTestRunner(verbosity=2)
    f_result = f_runner.run(f_suite)

    return 0 if f_result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
