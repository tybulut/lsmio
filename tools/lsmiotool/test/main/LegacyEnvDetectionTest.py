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

"""Legacy env.py site detection and library prefix."""

import copy
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import types
import unittest
from typing import Any, Dict, List, NamedTuple, Optional, Sequence
from unittest.mock import MagicMock, patch

from lsmiotool.lib import env
from lsmiotool.lib.log import Console
from lsmiotool.lib.site import EnvironmentResolver


_PROBE = """
import json, os, platform, sys
platform.node = lambda: sys.argv[1]
from lsmiotool.lib.site import EnvironmentResolver
_groups = json.loads(sys.argv[2])
EnvironmentResolver._getSystemGroups = classmethod(lambda cls: list(_groups))
from lsmiotool.lib import env
print(json.dumps({
    "hpc_env": env.HPC_ENV.value,
    "project_dir": env.PROJECT_DIR,
    "bin_dir": env.BIN_DIR,
    "lib_dir": env.LIB_DIR,
    "ld_library_path": os.environ.get("LD_LIBRARY_PATH"),
    "adios2_plugin_path": os.environ.get("ADIOS2_PLUGIN_PATH"),
}))
"""


class LegacyEnvDetectionTest(unittest.TestCase):
    """Imports lsmiotool.lib.env in a subprocess with a patched hostname and group list."""

    def setUp(self) -> None:
        self.m_tools_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )

    def _probe(
        self,
        f_hostname: str,
        f_groups: List[str],
        f_extra_env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        f_env = {
            f_k: f_v
            for f_k, f_v in os.environ.items()
            if f_k not in ("LSMIO_ENV", "ARCHER2_WORK_ROOT", "LD_LIBRARY_PATH")
        }
        f_env.update(
            {"PYTHONPATH": self.m_tools_dir, "USER": "alice", "HOME": "/home/alice"}
        )
        f_env.update(f_extra_env or {})
        f_proc = subprocess.run(
            [sys.executable, "-c", _PROBE, f_hostname, json.dumps(f_groups)],
            env=f_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(f_proc.returncode, 0, f_proc.stderr)
        return json.loads(f_proc.stdout.strip().splitlines()[-1])

    def testArcher2LoginAndComputeNodesDetectedByGroup(self) -> None:
        """ln01 and nid* in group archer2 are ARCHER2 (previously DEV / ISAMBARD)."""
        for f_host in ("ln01", "nid001234"):
            f_res = self._probe(f_host, ["e281", "archer2"])
            self.assertEqual(f_res["hpc_env"], "ARCHER2", f_host)
            self.assertEqual(f_res["project_dir"], "/work/e281/e281/alice/usr")
            self.assertEqual(f_res["bin_dir"], "/work/e281/e281/alice/usr/bin")
            self.assertEqual(f_res["lib_dir"], "/work/e281/e281/alice/usr/lib")
            self.assertEqual(
                f_res["ld_library_path"],
                "/work/e281/e281/alice/usr/lib:/work/e281/e281/alice/usr/lib64",
            )
            self.assertEqual(
                f_res["adios2_plugin_path"], "/work/e281/e281/alice/usr/lib"
            )

    def testArcher2WorkRootOverrideHonoured(self) -> None:
        """ARCHER2_WORK_ROOT overrides the default /work/e281/e281/$USER prefix."""
        f_res = self._probe(
            "ln02",
            ["archer2"],
            {"ARCHER2_WORK_ROOT": "/work/z01/z01/alice", "LD_LIBRARY_PATH": "/x/lib"},
        )
        self.assertEqual(f_res["lib_dir"], "/work/z01/z01/alice/usr/lib")
        self.assertEqual(
            f_res["ld_library_path"],
            "/work/z01/z01/alice/usr/lib:/work/z01/z01/alice/usr/lib64:/x/lib",
        )

    def testOtherSitesUseHomePrefix(self) -> None:
        """Non-ARCHER2 sites keep $HOME/src/usr; nid* without archer2 group is ISAMBARD."""
        f_res = self._probe("nid001234", ["users"])
        self.assertEqual(f_res["hpc_env"], "ISAMBARD")
        self.assertEqual(f_res["project_dir"], "/home/alice/src/usr")
        self.assertEqual(f_res["lib_dir"], "/home/alice/src/usr/lib")
        self.assertEqual(f_res["adios2_plugin_path"], "/home/alice/src/usr/lib")

        self.assertEqual(
            self._probe("login1.viking2.york.ac.uk", ["archer2"])["hpc_env"],
            "VIKING2",
        )
        self.assertEqual(self._probe("laptop", [])["hpc_env"], "DEV")


_CLEARED_VARS = (
    "LSMIO_ENV",
    "ARCHER2_WORK_ROOT",
    "LD_LIBRARY_PATH",
    "SLURMD_NODENAME",
    "SLURM_LOCALID",
    "SLURM_JOB_NUM_NODES",
    "ALPS_APP_PE",
)
_HOME_PREFIX = "/home/alice/src/usr"
_ARCHER2_PREFIX = "/work/e281/e281/alice/usr"


class _EnvExec(NamedTuple):
    """Result of one private load of lib/env.py."""

    module: types.ModuleType
    exit_code: Optional[int]
    errors: List[str]
    environ: Dict[str, str]
    stdin_closed: bool
    groups_mock: Optional[MagicMock]
    load_mock: Optional[MagicMock]


class LegacyEnvModuleTest(unittest.TestCase):
    """Executes a private copy of lib/env.py in-process with patched inputs."""

    def _execEnv(
        self,
        f_vars: Dict[str, Optional[str]],
        f_hostname: Optional[str] = None,
        f_groups: Sequence[str] = (),
        f_json: Optional[Dict[str, Any]] = None,
        f_gethostname: str = "testhost",
    ) -> _EnvExec:
        """Load env.py as a throwaway module; patches environment, hostname, groups, JSON."""
        f_spec = importlib.util.spec_from_file_location(
            "lsmiotool_env_probe", env.__file__
        )
        self.assertIsNotNone(f_spec)
        self.assertIsNotNone(f_spec.loader)
        f_mod = importlib.util.module_from_spec(f_spec)
        f_groups_mock: Optional[MagicMock] = None
        f_load_mock: Optional[MagicMock] = None
        with patch.dict(os.environ, {"USER": "alice", "HOME": "/home/alice"}):
            for f_key in _CLEARED_VARS:
                os.environ.pop(f_key, None)
            for f_key, f_value in f_vars.items():
                if f_value is not None:
                    os.environ[f_key] = f_value
            with patch("socket.gethostname", return_value=f_gethostname), patch.object(
                Console, "error"
            ) as f_error, patch("sys.stdin", io.StringIO()) as f_stdin:
                f_patches = []
                if f_hostname is not None:
                    f_patches.append(patch("platform.node", return_value=f_hostname))
                    f_patches.append(
                        patch.object(
                            EnvironmentResolver,
                            "_getSystemGroups",
                            return_value=list(f_groups),
                        )
                    )
                if f_json is not None:
                    f_patches.append(
                        patch("json.load", return_value=copy.deepcopy(f_json))
                    )
                f_mocks = [f_patch.start() for f_patch in f_patches]
                try:
                    try:
                        f_spec.loader.exec_module(f_mod)
                        f_code: Optional[int] = None
                    except SystemExit as f_exc:
                        f_code = f_exc.code
                finally:
                    for f_patch in reversed(f_patches):
                        f_patch.stop()
                f_errors = [f_call.args[0] for f_call in f_error.call_args_list]
                f_environ = dict(os.environ)
                f_closed = f_stdin.closed
        if f_hostname is not None:
            f_groups_mock = f_mocks[1]
        if f_json is not None:
            f_load_mock = f_mocks[-1]
        if f_code is not None:
            self.assertTrue(f_closed)
        return _EnvExec(
            f_mod, f_code, f_errors, f_environ, f_closed, f_groups_mock, f_load_mock
        )

    def _realDoc(self) -> Dict[str, Any]:
        """The checked-in environments.json."""
        with open(EnvironmentResolver.getDefaultProfilePath(), "r") as f_file:
            return json.load(f_file)

    def testLsmioEnvValueSelectsSiteCaseInsensitively(self) -> None:
        """LSMIO_ENV selects the site regardless of case."""
        f_rows = (
            ("isambard", "ISAMBARD", "PBS", _HOME_PREFIX),
            ("VIKING2", "VIKING2", "SLURM", _HOME_PREFIX),
            ("Viking", "VIKING", "SLURM", _HOME_PREFIX),
            ("archer2", "ARCHER2", "DEV", _ARCHER2_PREFIX),
            ("dev", "DEV", "DEV", _HOME_PREFIX),
        )
        for f_value, f_site, f_manager, f_prefix in f_rows:
            with self.subTest(f_value=f_value):
                f_run = self._execEnv({"LSMIO_ENV": f_value})
                self.assertIsNone(f_run.exit_code)
                self.assertEqual(f_run.errors, [])
                self.assertEqual(f_run.module.HPC_ENV.value, f_site)
                self.assertEqual(f_run.module.hpc_manager.value, f_manager)
                self.assertEqual(f_run.module.PROJECT_DIR, f_prefix)
                self.assertEqual(f_run.module.lsmio_env, f_value.upper())
                self.assertEqual(
                    f_run.environ["ADIOS2_PLUGIN_PATH"], f_run.module.LIB_DIR
                )

    def testUnknownLsmioEnvValueExits(self) -> None:
        """An unknown LSMIO_ENV logs two errors and exits 1 before configuration."""
        for f_value in ("SAWTOOTH", "viking3"):
            with self.subTest(f_value=f_value):
                f_plugin_before = os.environ.get("ADIOS2_PLUGIN_PATH")
                f_run = self._execEnv({"LSMIO_ENV": f_value})
                self.assertEqual(f_run.exit_code, 1)
                self.assertEqual(
                    f_run.errors,
                    [
                        f"Unknown LSMIO_ENV value: {f_value.upper()}",
                        "Unknown HPC Environment",
                    ],
                )
                self.assertFalse(hasattr(f_run.module, "HPC_ENV"))
                self.assertFalse(hasattr(f_run.module, "_env_configs"))
                self.assertEqual(
                    f_run.environ.get("ADIOS2_PLUGIN_PATH"), f_plugin_before
                )

    def testBlankOrPaddedLsmioEnvMatchesDetect(self) -> None:
        """Blank LSMIO_ENV is unset and padded LSMIO_ENV is stripped, as in EnvironmentResolver.detect."""
        f_rows = (("", "DEV"), ("   ", "DEV"), (" viking ", "VIKING"))
        for f_value, f_detected in f_rows:
            with self.subTest(f_value=f_value):
                f_run = self._execEnv(
                    {"LSMIO_ENV": f_value}, f_hostname="laptop", f_groups=[]
                )
                self.assertIsNone(f_run.exit_code)
                self.assertEqual(f_run.errors, [])
                self.assertEqual(f_run.module.HPC_ENV.value, f_detected)
                self.assertEqual(
                    f_run.module.lsmio_env, f_value.strip().upper() or None
                )
                self.assertEqual(
                    EnvironmentResolver.detect(
                        f_hostname="laptop",
                        f_groups=[],
                        f_env={"LSMIO_ENV": f_value},
                        f_test_mode=True,
                    ),
                    f_detected,
                )

    def testHostnameDetectionWhenLsmioEnvUnset(self) -> None:
        """Without LSMIO_ENV the site comes from hostname and group detection."""
        f_rows = (
            ("laptop", [], "DEV", _HOME_PREFIX),
            ("login1.viking2.york.ac.uk", [], "VIKING2", _HOME_PREFIX),
            ("nid001234", ["users"], "ISAMBARD", _HOME_PREFIX),
            ("ln01", ["archer2"], "ARCHER2", _ARCHER2_PREFIX),
        )
        for f_host, f_groups, f_site, f_prefix in f_rows:
            with self.subTest(f_host=f_host):
                f_run = self._execEnv({}, f_hostname=f_host, f_groups=f_groups)
                self.assertIsNone(f_run.exit_code)
                self.assertEqual(f_run.module.HPC_ENV.value, f_site)
                self.assertEqual(f_run.module.HOSTNAME, f_host)
                self.assertEqual(f_run.module.PROJECT_DIR, f_prefix)
                f_run.groups_mock.assert_called_once_with()
                self.assertNotIn("LSMIO_ENV", f_run.environ)

    def testMissingDefaultSectionExits(self) -> None:
        """environments.json without DEFAULT logs an error and exits 1."""
        f_doc = self._realDoc()
        del f_doc["DEFAULT"]
        f_run = self._execEnv({"LSMIO_ENV": "DEV"}, f_json=f_doc)
        self.assertEqual(f_run.exit_code, 1)
        self.assertEqual(f_run.errors, ["DEFAULT section missing in environments.json"])
        self.assertEqual(f_run.load_mock.call_count, 1)
        self.assertEqual(f_run.module._env_configs, f_doc)
        self.assertNotIn("DEFAULT", f_run.module._env_configs)
        self.assertFalse(hasattr(f_run.module, "_env"))

    def testSiteSectionMissingFromConfigExits(self) -> None:
        """A site section absent from the JSON exits 1 after DEFAULT was applied."""
        for f_env, f_removed in (("DEV", "DEV"), ("VIKING", "VIKING")):
            with self.subTest(f_env=f_env):
                f_doc = self._realDoc()
                del f_doc[f_removed]
                f_run = self._execEnv({"LSMIO_ENV": f_env}, f_json=f_doc)
                self.assertEqual(f_run.exit_code, 1)
                self.assertEqual(
                    f_run.errors,
                    [f"Unknown _env_configs value: {f_env}", "Unknown HPC Environment"],
                )
                self.assertEqual(f_run.module.hpc_manager.value, "DEV")
                self.assertEqual(f_run.module.base_path, "~/src/lsmio-data")
                self.assertEqual(f_run.module.lustre_ssd_path, "~/scratch")
                self.assertFalse(hasattr(f_run.module, "PROJECT_DIR"))

    def testDeepMergeRecursesIntoNestedDicts(self) -> None:
        """_deep_merge merges nested dicts, replaces other values, and copies its inputs."""
        f_rows = (
            (
                {"a": {"x": 1, "y": {"p": 1}}, "b": 2},
                {"a": {"y": {"q": 2}, "z": 3}, "b": {"n": 1}, "c": 4},
                {"a": {"x": 1, "y": {"p": 1, "q": 2}, "z": 3}, "b": {"n": 1}, "c": 4},
            ),
            ({"a": {"x": 1}}, {"a": 5}, {"a": 5}),
            ({"a": {"x": 1}}, {}, {"a": {"x": 1}}),
            ({}, {"a": {"x": 1}}, {"a": {"x": 1}}),
            ({"": {"x": 1}}, {"": {"y": 2}}, {"": {"x": 1, "y": 2}}),
        )
        for f_index, (f_base, f_over, f_expected) in enumerate(f_rows):
            with self.subTest(f_index=f_index):
                f_base_before = copy.deepcopy(f_base)
                f_over_before = copy.deepcopy(f_over)
                f_result = env._deep_merge(f_base, f_over)
                self.assertEqual(f_result, f_expected)
                self.assertEqual(f_base, f_base_before)
                self.assertEqual(f_over, f_over_before)
                self.assertIsNot(f_result, f_base)
                if f_index == 2:
                    self.assertIsNot(f_result["a"], f_base["a"])

    def testArcher2ProjectPrefixUsesWorkRoot(self) -> None:
        """ARCHER2 puts the prefix under the work root and prepends its libraries."""
        f_rows = (
            (None, "/work/e281/e281/alice"),
            ("/work/z01/z01/alice", "/work/z01/z01/alice"),
        )
        for f_var, f_root in f_rows:
            with self.subTest(f_var=f_var):
                f_run = self._execEnv(
                    {
                        "LSMIO_ENV": "ARCHER2",
                        "ARCHER2_WORK_ROOT": f_var,
                        "LD_LIBRARY_PATH": "/x/lib",
                    }
                )
                f_mod = f_run.module
                self.assertEqual(f_mod.PROJECT_DIR, f_root + "/usr")
                self.assertEqual(f_mod.BIN_DIR, f_mod.PROJECT_DIR + "/bin")
                self.assertEqual(f_mod.LIB_DIR, f_mod.PROJECT_DIR + "/lib")
                self.assertEqual(f_mod.LIB64_DIR, f_mod.PROJECT_DIR + "/lib64")
                self.assertEqual(
                    f_run.environ["LD_LIBRARY_PATH"],
                    f"{f_root}/usr/lib:{f_root}/usr/lib64:/x/lib",
                )
                self.assertEqual(
                    f_run.environ["ADIOS2_PLUGIN_PATH"], f_root + "/usr/lib"
                )
                self.assertTrue(f_run.environ["PATH"].endswith(":" + f_root + "/usr/bin"))

    def testSchedulerNodeIdentity(self) -> None:
        """Node name, unique id and task count come from the scheduler variables."""
        f_slurm = {
            "LSMIO_ENV": "VIKING",
            "SLURMD_NODENAME": "node042",
            "SLURM_LOCALID": "3",
            "SLURM_JOB_NUM_NODES": "4",
        }
        f_rows = (
            (f_slurm, "testhost", "node042", "node042-3", 4),
            # Observation O1: unset Slurm variables leave None and a literal ${...}.
            ({"LSMIO_ENV": "VIKING"}, "testhost", None, "${SLURMD_NODENAME}-${SLURM_LOCALID}", 1),
            ({"LSMIO_ENV": "ISAMBARD", "ALPS_APP_PE": "7"}, "nid001", "nid001", "nid001-7", 1),
            ({"LSMIO_ENV": "ISAMBARD"}, "nid001", "nid001", "nid001-${ALPS_APP_PE}", 1),
            ({"LSMIO_ENV": "DEV"}, "testhost", "testhost", None, 1),
        )
        for f_vars, f_host, f_node, f_uid, f_tasks in f_rows:
            with self.subTest(f_vars=f_vars):
                f_mod = self._execEnv(f_vars, f_gethostname=f_host).module
                if f_node is None:
                    self.assertIsNone(f_mod.BM_NODENAME)
                else:
                    self.assertEqual(f_mod.BM_NODENAME, f_node)
                if f_uid is None:
                    self.assertRegex(f_mod.BM_UNIQUE_UID, r"testhost-\d{8}-\d{4}")
                else:
                    self.assertEqual(f_mod.BM_UNIQUE_UID, f_uid)
                self.assertEqual(f_mod.BM_NUM_TASKS, f_tasks)
                self.assertRegex(f_mod.DATE_STAMP, r"\d{4}-\d{2}-\d{2}")
                self.assertEqual(
                    f_mod.BM_DIR,
                    os.path.join(f_mod.lustre_ssd_path, "users", "alice", "benchmark"),
                )
                if f_vars["LSMIO_ENV"] == "VIKING":
                    self.assertEqual(f_mod.BM_DIR, "/mnt/bb/tmp/users/alice/benchmark")
                if f_vars["LSMIO_ENV"] == "ISAMBARD":
                    self.assertEqual(f_mod.BM_DIR, "/scratch/users/alice/benchmark")

    def testLibraryPathPrependedUnlessPresent(self) -> None:
        """The prefix libraries are prepended to LD_LIBRARY_PATH unless already there."""
        f_lib = _HOME_PREFIX + "/lib"
        f_both = f_lib + ":" + _HOME_PREFIX + "/lib64"
        f_rows = (
            (None, f_both),
            ("", f_both),
            ("/x/lib", f_both + ":/x/lib"),
            ("/x:" + f_lib, "/x:" + f_lib),
        )
        for f_value, f_expected in f_rows:
            with self.subTest(f_value=f_value):
                f_run = self._execEnv({"LSMIO_ENV": "DEV", "LD_LIBRARY_PATH": f_value})
                self.assertEqual(f_run.module.LIB_DIR, f_lib)
                self.assertEqual(f_run.environ["LD_LIBRARY_PATH"], f_expected)
                self.assertEqual(f_run.environ["ADIOS2_PLUGIN_PATH"], f_lib)

    def testPrivateLoadLeavesProcessStateIntact(self) -> None:
        """Private loads, including an exiting one, restore environ, stdin and modules."""
        f_environ_before = dict(os.environ)
        f_stdin_before = sys.stdin
        self._execEnv({"LSMIO_ENV": "VIKING"})
        f_run = self._execEnv({"LSMIO_ENV": "SAWTOOTH"})
        self.assertEqual(f_run.exit_code, 1)
        self.assertEqual(dict(os.environ), f_environ_before)
        self.assertIs(sys.stdin, f_stdin_before)
        self.assertFalse(sys.stdin.closed)
        self.assertNotIn("lsmiotool_env_probe", sys.modules)
        self.assertIs(sys.modules["lsmiotool.lib.env"], env)
        # The suite runs with LSMIO_ENV=DEV (build.sh), so the real module is DEV.
        self.assertIs(env.HPC_ENV, env.HpcEnv.DEV)

    def testLdLibraryPathConstantHoldsVariable(self) -> None:
        """env.LD_LIBRARY_PATH is the variable's value, or "" when unset."""
        f_run = self._execEnv({"LSMIO_ENV": "DEV", "LD_LIBRARY_PATH": "/x/lib"})
        self.assertEqual(f_run.module.LD_LIBRARY_PATH, "/x/lib")
        self.assertNotEqual(f_run.module.LD_LIBRARY_PATH, f_run.module.HOME)
        f_run = self._execEnv({"LSMIO_ENV": "DEV"})
        self.assertEqual(f_run.module.LD_LIBRARY_PATH, "")


if __name__ == "__main__":
    unittest.main()
