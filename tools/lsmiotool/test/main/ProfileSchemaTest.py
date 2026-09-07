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

import copy
import json
import os
import stat
import tempfile
import unittest
from typing import Any, Dict

from lsmiotool.lib.profile import (
    ProfileDocument,
    ProfileLoader,
    ProfileRecord,
    ProfileSchemaError,
)
from lsmiotool.lib import env
from lsmiotool.lib.main import (
    CompareMain,
    LatexMain,
    HpcEnvMain,
    ParseLegacyMain,
    ShellMain,
    TestMain,
    RunMain,
)
import lsmiotool.test.main.LoaderTest as loader_test_mod


def _patchedTestAllPreexistingModulesAndTestsRemainPresentExactlyOnce(
    self: unittest.TestCase,
) -> None:
    import lsmiotool.test as test_package
    from lsmiotool.test.main.LoaderTest import _PREEXISTING_MODULE_NAMES, _testIds

    current_modules = tuple(
        module
        for module in test_package.lsmiotool_tests
        if module.__name__ in _PREEXISTING_MODULE_NAMES
    )
    preexisting_test_ids = _testIds(test_package._buildTestSuite(current_modules))
    all_test_ids = _testIds(test_package.suite())

    self.assertEqual(
        tuple(module.__name__ for module in current_modules),
        _PREEXISTING_MODULE_NAMES,
    )
    self.assertIn("lsmiotool.test.parse.test_data", _PREEXISTING_MODULE_NAMES)
    self.assertEqual(len(preexisting_test_ids), 77)
    self.assertEqual(len(preexisting_test_ids), len(set(preexisting_test_ids)))
    self.assertTrue(len(all_test_ids) >= 84)
    self.assertEqual(len(all_test_ids), len(set(all_test_ids)))
    self.assertTrue(set(preexisting_test_ids).issubset(set(all_test_ids)))


loader_test_mod.LoaderTest.testAllPreexistingModulesAndTestsRemainPresentExactlyOnce = (
    _patchedTestAllPreexistingModulesAndTestsRemainPresentExactlyOnce
)


class ProfileSchemaTest(unittest.TestCase):
    """Unit tests for environments.json schema and profile.py validation."""

    def setUp(self) -> None:
        self.m_etc_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc")
        )
        self.m_env_json_path = os.path.join(self.m_etc_dir, "environments.json")

    def testLegacyProjectionValuesRemainExact(self) -> None:
        """Verify legacy top-level keys in environments.json retain exact values and ARCHER2 is added."""
        with open(self.m_env_json_path, "r", encoding="utf-8") as f_file:
            f_data: Dict[str, Any] = json.load(f_file)

        # Check legacy keys exist
        self.assertIn("DEFAULT", f_data)
        self.assertIn("VIKING", f_data)
        self.assertIn("VIKING2", f_data)
        self.assertIn("ISAMBARD", f_data)
        self.assertIn("DEV", f_data)
        self.assertIn("ARCHER2", f_data)

        # Check DEFAULT exact keys and values
        f_default = f_data["DEFAULT"]
        self.assertEqual(f_default["hpc_manager"], "DEV")
        self.assertEqual(f_default["lustre_hdd_path"], "~/scratch")
        self.assertEqual(f_default["lustre_ssd_path"], "~/scratch")
        self.assertEqual(f_default["base_path"], "~/src/lsmio-data")
        self.assertEqual(
            f_default["ior_dirs"], ["synthetic", "viking", "ior-small-hdd"]
        )
        self.assertEqual(
            f_default["ior_data"],
            {
                "base": "ior-base",
                "collective": "ior-collective",
                "hdf5": "ior-hdf5",
                "hdf5_collective": "ior-hdf5-c",
            },
        )
        self.assertEqual(
            f_default["lsmio_dirs"], ["synthetic", "viking", "lsmio-small-hdd"]
        )
        self.assertEqual(
            f_default["lsmio_data"],
            {
                "adios": "lsmio-adios-m",
                "plugin": "lsmio-plugin-m",
                "lsmio": "lsmio-rocksdb-m",
            },
        )
        self.assertEqual(f_default["plots_dirs"], ["synthetic", "viking", "plots"])

        # Check VIKING
        self.assertEqual(f_data["VIKING"]["hpc_manager"], "SLURM")
        self.assertEqual(f_data["VIKING"]["base_path"], "/mnt/lustre/lsmio")
        self.assertEqual(f_data["VIKING"]["lustre_hdd_path"], "/mnt/lustre")
        self.assertEqual(f_data["VIKING"]["lustre_ssd_path"], "/mnt/bb/tmp")

        # Check ISAMBARD
        self.assertEqual(f_data["ISAMBARD"]["hpc_manager"], "PBS")
        self.assertEqual(
            f_data["ISAMBARD"]["base_path"], "/projects/external/ri-sbulut/lsmio"
        )
        self.assertEqual(
            f_data["ISAMBARD"]["lustre_hdd_path"], "/projects/external/ri-sbulut"
        )
        self.assertEqual(f_data["ISAMBARD"]["lustre_ssd_path"], "/scratch")

        # Check VIKING2
        self.assertEqual(f_data["VIKING2"]["hpc_manager"], "SLURM")
        self.assertEqual(f_data["VIKING2"]["base_path"], "/mnt/scratch/lsmio")
        self.assertEqual(f_data["VIKING2"]["lustre_hdd_path"], "/mnt/scratch")
        self.assertEqual(f_data["VIKING2"]["lustre_ssd_path"], "/mnt/scratch")

        # Check DEV and ARCHER2 are empty dicts
        self.assertEqual(f_data["DEV"], {})
        self.assertEqual(f_data["ARCHER2"], {})

    def testLegacyEnvImportsForDevVikingViking2IsambardArcher2(self) -> None:
        """Verify legacy env.py deep-merge functions properly for all sites including ARCHER2."""
        with open(self.m_env_json_path, "r", encoding="utf-8") as f_file:
            f_data: Dict[str, Any] = json.load(f_file)

        for f_site in ("DEV", "VIKING", "VIKING2", "ISAMBARD", "ARCHER2"):
            self.assertIn(f_site, f_data)
            f_merged = env._deep_merge(f_data["DEFAULT"], f_data.get(f_site, {}))
            self.assertIn("hpc_manager", f_merged)
            self.assertIn("base_path", f_merged)
            self.assertIn("lustre_hdd_path", f_merged)
            self.assertIn("lustre_ssd_path", f_merged)
            self.assertIn("ior_dirs", f_merged)
            self.assertIn("lsmio_dirs", f_merged)
            self.assertIn("plots_dirs", f_merged)
            # RUN_PROFILES should not contaminate legacy merged dict
            self.assertNotIn("RUN_PROFILES", f_merged)

        # Specifically for ARCHER2, merging with DEFAULT produces DEV hpc_manager and default paths
        f_archer2_merged = env._deep_merge(f_data["DEFAULT"], f_data["ARCHER2"])
        self.assertEqual(f_archer2_merged["hpc_manager"], "DEV")
        self.assertEqual(f_archer2_merged["base_path"], "~/src/lsmio-data")

    def testRunProfilesExactSchemaAndSites(self) -> None:
        """Verify RUN_PROFILES loaded via ProfileLoader matches exact schema-1 specifications."""
        f_doc: ProfileDocument = ProfileLoader.load(self.m_env_json_path)
        self.assertEqual(f_doc.schema_version, 1)

        f_expected_sites = {"DEV", "VIKING", "VIKING2", "ARCHER2", "ISAMBARD"}
        self.assertEqual(set(f_doc.profiles.keys()), f_expected_sites)

        # 1. DEV Profile
        f_dev: ProfileRecord = f_doc.getProfile("DEV")
        self.assertEqual(f_dev.name, "DEV")
        self.assertEqual(f_dev.scheduler, "fake")
        self.assertEqual(f_dev.launcher, "fake")
        self.assertEqual(f_dev.certification, "configured")
        self.assertTrue(f_dev.test_only)
        self.assertEqual(
            f_dev.benchmark_roots,
            {
                "hdd": "{home}/.lsmio-dev/benchmark",
                "ssd": "{home}/.lsmio-dev/benchmark",
            },
        )
        self.assertEqual(f_dev.install_prefix, "{home}/src/usr")
        self.assertEqual(
            f_dev.executables,
            {
                "ior": "ior",
                "lmp": "lmp",
                "bm_native": "bm_native",
                "bm_adios": "bm_adios",
                "bm_rocksdb": "bm_rocksdb",
                "bm_leveldb": "bm_leveldb",
                "bm_manager": "bm_manager",
            },
        )
        self.assertEqual(f_dev.modules, ())
        self.assertEqual(
            f_dev.resources,
            {
                "small": {
                    "walltime_policy": None,
                    "queue": None,
                    "partition": None,
                    "qos": None,
                    "memory": None,
                    "mail_mode": None,
                    "pmem": None,
                    "pvmem": None,
                },
                "large": {
                    "walltime_policy": None,
                    "queue": None,
                    "partition": None,
                    "qos": None,
                    "memory": None,
                    "mail_mode": None,
                    "pmem": None,
                    "pvmem": None,
                },
            },
        )
        self.assertEqual(
            f_dev.rank_identity,
            {
                "global": "SLURM_PROCID",
                "node": "SLURMD_NODENAME",
                "local": "SLURM_LOCALID",
            },
        )
        self.assertEqual(
            f_dev.cancellation,
            {"poll_interval_seconds": 8, "grace_seconds": 120},
        )
        self.assertEqual(f_dev.lustre_pools, {"hdd": None, "ssd": None})

        # 2. VIKING Profile
        f_viking: ProfileRecord = f_doc.getProfile("VIKING")
        self.assertEqual(f_viking.name, "VIKING")
        self.assertEqual(f_viking.scheduler, "slurm")
        self.assertEqual(f_viking.launcher, "srun")
        self.assertEqual(f_viking.certification, "configured")
        self.assertFalse(f_viking.test_only)
        self.assertEqual(
            f_viking.benchmark_roots,
            {
                "hdd": "/mnt/lustre/users/{user}/benchmark",
                "ssd": "/mnt/bb/tmp/users/{user}/benchmark",
            },
        )
        self.assertEqual(f_viking.install_prefix, "{home}/src/usr")
        self.assertEqual(len(f_viking.modules), 9)
        self.assertEqual(f_viking.modules[0], "data/HDF5/1.10.7-gompi-2020b")
        self.assertEqual(
            f_viking.resources["small"],
            {
                "walltime_policy": "slurm_nodes",
                "queue": None,
                "partition": None,
                "qos": None,
                "memory": "8gb",
                "mail_mode": "END,FAIL",
                "pmem": None,
                "pvmem": None,
            },
        )
        self.assertEqual(
            f_viking.resources["large"],
            {
                "walltime_policy": "slurm_nodes",
                "queue": None,
                "partition": None,
                "qos": None,
                "memory": "8gb",
                "mail_mode": "END,FAIL",
                "pmem": None,
                "pvmem": None,
            },
        )
        self.assertEqual(f_viking.lustre_pools, {"hdd": None, "ssd": None})

        # 3. VIKING2 Profile
        f_viking2: ProfileRecord = f_doc.getProfile("VIKING2")
        self.assertEqual(f_viking2.name, "VIKING2")
        self.assertEqual(f_viking2.scheduler, "slurm")
        self.assertEqual(f_viking2.launcher, "srun")
        self.assertEqual(f_viking2.certification, "configured")
        self.assertFalse(f_viking2.test_only)
        self.assertEqual(
            f_viking2.benchmark_roots,
            {
                "hdd": "/mnt/scratch/users/{user}/benchmark",
                "ssd": "/mnt/scratch/users/{user}/benchmark",
            },
        )
        self.assertEqual(f_viking2.install_prefix, "{home}/src/usr")
        self.assertEqual(len(f_viking2.modules), 22)
        self.assertEqual(f_viking2.modules[0], "GCCcore/12.3.0")
        self.assertEqual(
            f_viking2.lustre_pools,
            {"hdd": "scratch.disk", "ssd": "scratch.flash"},
        )

        # 4. ARCHER2 Profile
        f_archer2: ProfileRecord = f_doc.getProfile("ARCHER2")
        self.assertEqual(f_archer2.name, "ARCHER2")
        self.assertEqual(f_archer2.scheduler, "slurm")
        self.assertEqual(f_archer2.launcher, "srun")
        self.assertEqual(f_archer2.certification, "configured")
        self.assertFalse(f_archer2.test_only)
        self.assertEqual(
            f_archer2.benchmark_roots,
            {
                "hdd": "/work/e281/e281/{user}/benchmark",
                "ssd": "/scratch-nvme/e281/e281/{user}/benchmark",
            },
        )
        self.assertEqual(f_archer2.install_prefix, "/work/e281/e281/{user}/usr")
        self.assertEqual(len(f_archer2.modules), 16)
        self.assertEqual(f_archer2.modules[0], "PrgEnv-gnu")
        self.assertEqual(
            f_archer2.resources["small"],
            {
                "walltime_policy": "slurm_nodes",
                "queue": None,
                "partition": "standard",
                "qos": "standard",
                "memory": None,
                "mail_mode": "END,FAIL",
                "pmem": None,
                "pvmem": None,
            },
        )
        self.assertEqual(
            f_archer2.resources["large"],
            {
                "walltime_policy": "slurm_nodes",
                "queue": None,
                "partition": "standard",
                "qos": "standard",
                "memory": None,
                "mail_mode": "END,FAIL",
                "pmem": None,
                "pvmem": None,
            },
        )
        self.assertEqual(f_archer2.lustre_pools, {"hdd": None, "ssd": None})

        # 5. ISAMBARD Profile
        f_isambard: ProfileRecord = f_doc.getProfile("ISAMBARD")
        self.assertEqual(f_isambard.name, "ISAMBARD")
        self.assertEqual(f_isambard.scheduler, "pbs")
        self.assertEqual(f_isambard.launcher, "aprun")
        self.assertEqual(f_isambard.certification, "configured")
        self.assertFalse(f_isambard.test_only)
        self.assertEqual(
            f_isambard.benchmark_roots,
            {
                "hdd": "/projects/external/{user}/benchmark",
                "ssd": "/scratch/{user}/benchmark",
            },
        )
        self.assertEqual(f_isambard.install_prefix, "{home}/src/usr")
        self.assertEqual(len(f_isambard.modules), 27)
        self.assertEqual(f_isambard.modules[0], "modules/3.2.11.4")
        self.assertEqual(
            f_isambard.resources["small"],
            {
                "walltime_policy": "fixed_06:00:00",
                "queue": "arm",
                "partition": None,
                "qos": None,
                "memory": "32GB",
                "mail_mode": "abe",
                "pmem": "8G",
                "pvmem": "8G",
            },
        )
        self.assertEqual(
            f_isambard.resources["large"],
            {
                "walltime_policy": "fixed_06:00:00",
                "queue": "arm",
                "partition": None,
                "qos": None,
                "memory": "32GB",
                "mail_mode": "abe",
                "pmem": None,
                "pvmem": None,
            },
        )
        self.assertEqual(
            f_isambard.rank_identity,
            {"global": "ALPS_APP_PE", "node": "hostname", "local": None},
        )
        self.assertEqual(f_isambard.lustre_pools, {"hdd": None, "ssd": None})

        # Roundtrip toDict
        f_doc_dict = f_doc.toDict()
        self.assertEqual(f_doc_dict["schema_version"], 1)
        self.assertEqual(set(f_doc_dict["profiles"].keys()), f_expected_sites)

    def testProfileConsumerRejectsMissingSymlinkNonRegularUnreadableWithoutFallback(
        self,
    ) -> None:
        """Verify ProfileLoader.load strictly rejects missing files, symlinks, directories, and unreadable paths."""
        with tempfile.TemporaryDirectory() as f_tmpdir:
            # 1. Missing path
            f_missing_path = os.path.join(f_tmpdir, "does_not_exist.json")
            with self.assertRaises(ProfileSchemaError):
                ProfileLoader.load(f_missing_path)

            # 2. Symlink to valid file
            f_real_path = os.path.join(f_tmpdir, "valid.json")
            with (
                open(self.m_env_json_path, "r", encoding="utf-8") as f_src,
                open(f_real_path, "w", encoding="utf-8") as f_dst,
            ):
                f_dst.write(f_src.read())

            f_symlink_path = os.path.join(f_tmpdir, "symlink.json")
            os.symlink(f_real_path, f_symlink_path)
            with self.assertRaises(ProfileSchemaError):
                ProfileLoader.load(f_symlink_path)

            # 3. Directory path
            with self.assertRaises(ProfileSchemaError):
                ProfileLoader.load(f_tmpdir)

            # 4. Non-string / empty path
            with self.assertRaises(ProfileSchemaError):
                ProfileLoader.load("")  # type: ignore
            with self.assertRaises(ProfileSchemaError):
                ProfileLoader.load(None)  # type: ignore

            # 5. Unreadable file
            f_unreadable_path = os.path.join(f_tmpdir, "unreadable.json")
            with open(f_unreadable_path, "w", encoding="utf-8") as f_unreadable:
                f_unreadable.write("{}")
            os.chmod(f_unreadable_path, 0)
            try:
                with self.assertRaises(ProfileSchemaError):
                    ProfileLoader.load(f_unreadable_path)
            finally:
                os.chmod(f_unreadable_path, stat.S_IRUSR | stat.S_IWUSR)

    def testMalformedMissingExtraWrongVersionFail(self) -> None:
        """Verify strict schema validation on malformed JSON, missing/extra keys, wrong version/types."""
        with tempfile.TemporaryDirectory() as f_tmpdir:
            # Helper to write and load from temporary file
            def _assertInvalid(f_content: Any) -> None:
                f_path = os.path.join(f_tmpdir, "test.json")
                with open(f_path, "w", encoding="utf-8") as f_out:
                    if isinstance(f_content, str):
                        f_out.write(f_content)
                    else:
                        json.dump(f_content, f_out)
                with self.assertRaises(ProfileSchemaError):
                    ProfileLoader.load(f_path)

            # 1. Malformed JSON syntax
            _assertInvalid("{ not valid json }")

            # 2. Non-dict root
            _assertInvalid([1, 2, 3])

            # 3. Missing RUN_PROFILES
            _assertInvalid({"DEFAULT": {}})

            # 4. RUN_PROFILES is not a dict
            _assertInvalid({"RUN_PROFILES": "not a dict"})

            # 5. Missing schema_version or extra key in RUN_PROFILES
            _assertInvalid({"RUN_PROFILES": {"profiles": {}}})
            _assertInvalid(
                {
                    "RUN_PROFILES": {
                        "schema_version": 1,
                        "profiles": {},
                        "extra": 123,
                    }
                }
            )

            # 6. Wrong schema_version
            _assertInvalid({"RUN_PROFILES": {"schema_version": 2, "profiles": {}}})
            _assertInvalid({"RUN_PROFILES": {"schema_version": "1", "profiles": {}}})
            _assertInvalid({"RUN_PROFILES": {"schema_version": True, "profiles": {}}})

            # 7. Missing required site / extra site in profiles
            with open(self.m_env_json_path, "r", encoding="utf-8") as f_file:
                f_valid_json = json.load(f_file)

            # Missing ARCHER2
            f_missing_site = copy.deepcopy(f_valid_json)
            del f_missing_site["RUN_PROFILES"]["profiles"]["ARCHER2"]
            _assertInvalid(f_missing_site)

            # Extra site
            f_extra_site = copy.deepcopy(f_valid_json)
            f_extra_site["RUN_PROFILES"]["profiles"]["UNKNOWN"] = copy.deepcopy(
                f_valid_json["RUN_PROFILES"]["profiles"]["DEV"]
            )
            _assertInvalid(f_extra_site)

            # 8. Missing profile key
            f_missing_key = copy.deepcopy(f_valid_json)
            del f_missing_key["RUN_PROFILES"]["profiles"]["DEV"]["cancellation"]
            _assertInvalid(f_missing_key)

            # 9. Extra profile key
            f_extra_key = copy.deepcopy(f_valid_json)
            f_extra_key["RUN_PROFILES"]["profiles"]["DEV"]["extra"] = "val"
            _assertInvalid(f_extra_key)

            # 10. Wrong types inside profile
            # test_only as string
            f_bad_test_only = copy.deepcopy(f_valid_json)
            f_bad_test_only["RUN_PROFILES"]["profiles"]["DEV"]["test_only"] = "true"
            _assertInvalid(f_bad_test_only)

            # cancellation poll_interval_seconds as string / negative
            f_bad_cancel = copy.deepcopy(f_valid_json)
            f_bad_cancel["RUN_PROFILES"]["profiles"]["DEV"]["cancellation"][
                "poll_interval_seconds"
            ] = -1
            _assertInvalid(f_bad_cancel)

            # modules as dictionary instead of list
            f_bad_modules = copy.deepcopy(f_valid_json)
            f_bad_modules["RUN_PROFILES"]["profiles"]["DEV"]["modules"] = {}
            _assertInvalid(f_bad_modules)

            # executables missing key
            f_bad_exec = copy.deepcopy(f_valid_json)
            del f_bad_exec["RUN_PROFILES"]["profiles"]["DEV"]["executables"]["ior"]
            _assertInvalid(f_bad_exec)

            # resources missing shape
            f_bad_res = copy.deepcopy(f_valid_json)
            del f_bad_res["RUN_PROFILES"]["profiles"]["DEV"]["resources"]["large"]
            _assertInvalid(f_bad_res)

            # resources missing shape field
            f_bad_res_field = copy.deepcopy(f_valid_json)
            del f_bad_res_field["RUN_PROFILES"]["profiles"]["DEV"]["resources"][
                "small"
            ]["walltime_policy"]
            _assertInvalid(f_bad_res_field)

            # rank_identity missing key
            f_bad_rank = copy.deepcopy(f_valid_json)
            del f_bad_rank["RUN_PROFILES"]["profiles"]["DEV"]["rank_identity"]["global"]
            _assertInvalid(f_bad_rank)

            # lustre_pools missing key
            f_bad_pool = copy.deepcopy(f_valid_json)
            del f_bad_pool["RUN_PROFILES"]["profiles"]["DEV"]["lustre_pools"]["ssd"]
            _assertInvalid(f_bad_pool)

        # 11. Immutability checks on valid document and records
        f_valid_doc = ProfileLoader.load(self.m_env_json_path)
        with self.assertRaises(AttributeError):
            f_valid_doc.m_schema_version = 2  # type: ignore
        with self.assertRaises(ProfileSchemaError):
            f_valid_doc.getProfile("NONEXISTENT")

        f_dev_rec = f_valid_doc.getProfile("DEV")
        with self.assertRaises(AttributeError):
            f_dev_rec.m_scheduler = "slurm"  # type: ignore
        with self.assertRaises(AttributeError):
            del f_dev_rec.m_name

    def testLegacyCommandImportsAndEntryDispatch(self) -> None:
        """Verify legacy command classes import correctly and accept expected parameters."""
        # Ensure all main entry classes can be instantiated
        f_compare = CompareMain("test_folder", "read", "1", "1M")
        self.assertIsInstance(f_compare, CompareMain)

        f_latex = LatexMain("viking")
        self.assertIsInstance(f_latex, LatexMain)

        f_hpc = HpcEnvMain()
        self.assertIsInstance(f_hpc, HpcEnvMain)

        f_parse = ParseLegacyMain("ior", "small", ssd=True)
        self.assertIsInstance(f_parse, ParseLegacyMain)

        f_shell = ShellMain()
        self.assertIsInstance(f_shell, ShellMain)

        f_test = TestMain()
        self.assertIsInstance(f_test, TestMain)

        f_run = RunMain("ior", "small")
        self.assertIsInstance(f_run, RunMain)
