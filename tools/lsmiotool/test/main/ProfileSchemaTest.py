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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lsmiotool.lib.profile import (
    ProfileDocument,
    ProfileLoader,
    ProfileRecord,
    ProfileSchemaError,
)
from lsmiotool.lib import env
from lsmiotool.lib.cli import CompareRequest, LatexRequest
from lsmiotool.lib.main import (
    CompareMain,
    LatexMain,
    HpcEnvMain,
    ShellMain,
    TestMain,
    RunMain,
)

# Sentinel for _mutated: remove the key instead of setting it.
_DELETE = object()


class ProfileSchemaTest(unittest.TestCase):
    """Unit tests for environments.json schema and profile.py validation."""

    def setUp(self) -> None:
        self.m_etc_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc")
        )
        self.m_env_json_path = os.path.join(self.m_etc_dir, "environments.json")

    def _assertModuleInventory(self, f_record: ProfileRecord) -> None:
        """Assert a site's modules are loaded as listed in environments.json.

        Module names change whenever a site is re-tooled, so only the shape is
        checked: a non-empty tuple of unique non-empty strings, in file order.
        """
        with open(self.m_env_json_path, "r", encoding="utf-8") as f_file:
            f_raw = json.load(f_file)
        f_raw_modules = f_raw["RUN_PROFILES"]["profiles"][f_record.name]["modules"]

        self.assertIsInstance(f_record.modules, tuple)
        self.assertTrue(f_record.modules, f"{f_record.name} has no modules")
        self.assertTrue(
            all(isinstance(f_mod, str) and f_mod for f_mod in f_record.modules)
        )
        self.assertEqual(len(set(f_record.modules)), len(f_record.modules))
        self.assertEqual(f_record.modules, tuple(f_raw_modules))

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

        # srun --mpi: only VIKING2 (its Open MPI 5 module sets SLURM_MPI_TYPE=none)
        self.assertEqual(
            {f_n: f_doc.getProfile(f_n).srun_mpi for f_n in f_expected_sites},
            {
                "DEV": None,
                "VIKING": None,
                "VIKING2": "pmix",
                "ARCHER2": None,
                "ISAMBARD": None,
            },
        )
        self.assertEqual(f_doc.getProfile("VIKING2").toDict()["srun_mpi"], "pmix")
        self.assertNotIn("srun_mpi", f_doc.getProfile("VIKING").toDict())

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
                "epocpp": "epocpp",
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
        self._assertModuleInventory(f_viking)
        self.assertEqual(
            f_viking.resources["small"],
            {
                "walltime_policy": "slurm_nodes",
                "queue": None,
                "partition": None,
                "qos": None,
                "memory": "16gb",
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
                "memory": "16gb",
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
        self._assertModuleInventory(f_viking2)
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
        self._assertModuleInventory(f_archer2)
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
        self._assertModuleInventory(f_isambard)
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

            # 9b. srun_mpi: optional, only for srun, and an srun --mpi type
            for f_site, f_val in (
                ("DEV", "pmix"),
                ("VIKING", "pmix --x"),
                ("VIKING", 5),
            ):
                f_bad_mpi = copy.deepcopy(f_valid_json)
                f_bad_mpi["RUN_PROFILES"]["profiles"][f_site]["srun_mpi"] = f_val
                _assertInvalid(f_bad_mpi)

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

    def _validDocument(self) -> Dict[str, Any]:
        """A fresh parse of the checked-in environments.json."""
        with open(self.m_env_json_path, "r", encoding="utf-8") as f_file:
            return json.load(f_file)

    def _mutated(
        self,
        f_site: str,
        f_path: Tuple[str, ...],
        f_value: Any,
        f_doc: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Set (or, for _DELETE, remove) one value inside a site record."""
        f_result = f_doc if f_doc is not None else self._validDocument()
        f_profiles = f_result["RUN_PROFILES"]["profiles"]
        if not f_path:
            f_profiles[f_site] = f_value
            return f_result
        f_node = f_profiles[f_site]
        for f_key in f_path[:-1]:
            f_node = f_node[f_key]
        if f_value is _DELETE:
            del f_node[f_path[-1]]
        else:
            f_node[f_path[-1]] = f_value
        return f_result

    def _assertRejected(self, f_doc: Any, f_message: str) -> None:
        """Assert ProfileLoader.load rejects the document with exactly f_message."""
        f_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(f_tmp.cleanup)
        f_path = os.path.join(f_tmp.name, "profile.json")
        with open(f_path, "w", encoding="utf-8") as f_file:
            json.dump(f_doc, f_file)
        with self.assertRaises(ProfileSchemaError) as f_ctx:
            ProfileLoader.load(f_path)
        self.assertEqual(str(f_ctx.exception), f_message)

    def _assertCanonicalStillLoads(self) -> None:
        """No cached or partial document leaks from a rejected load."""
        self.assertEqual(len(ProfileLoader.load(self.m_env_json_path).profiles), 5)

    def _assertMutationRows(
        self, f_rows: Sequence[Tuple[str, Tuple[str, ...], Any, str]]
    ) -> None:
        for f_site, f_path, f_value, f_message in f_rows:
            with self.subTest(f_site=f_site, f_path=f_path, f_value=repr(f_value)):
                self._assertRejected(self._mutated(f_site, f_path, f_value), f_message)
        self._assertCanonicalStillLoads()

    def testRecordAndDocumentAssignableOnlyUntilFrozen(self) -> None:
        """Before _frozen is set writes and deletes work; afterwards both are rejected."""
        for f_cls, f_slot, f_value in (
            (ProfileRecord, "m_name", "X"),
            (ProfileDocument, "m_schema_version", 1),
        ):
            with self.subTest(f_cls=f_cls.__name__):
                f_obj = f_cls.__new__(f_cls)
                setattr(f_obj, f_slot, f_value)
                self.assertEqual(getattr(f_obj, f_slot), f_value)
                delattr(f_obj, f_slot)
                self.assertFalse(hasattr(f_obj, f_slot))
                f_obj._frozen = True
                with self.assertRaises(AttributeError) as f_ctx:
                    setattr(f_obj, f_slot, f_value)
                self.assertEqual(
                    str(f_ctx.exception), f"Cannot modify immutable {f_cls.__name__}"
                )
                with self.assertRaises(AttributeError) as f_ctx:
                    del f_obj._frozen
                self.assertEqual(
                    str(f_ctx.exception),
                    f"Cannot delete attribute from immutable {f_cls.__name__}",
                )
                self.assertFalse(hasattr(f_obj, f_slot))
                self.assertIs(f_obj._frozen, True)

    def testLoadedDocumentRejectsDelete(self) -> None:
        """A loaded ProfileDocument refuses attribute deletion and keeps its content."""
        f_doc = ProfileLoader.load(self.m_env_json_path)
        with self.assertRaises(AttributeError) as f_ctx:
            del f_doc.m_profiles
        self.assertEqual(
            str(f_ctx.exception),
            "Cannot delete attribute from immutable ProfileDocument",
        )
        self.assertEqual(f_doc.schema_version, 1)
        self.assertEqual(
            sorted(f_doc.profiles), ["ARCHER2", "DEV", "ISAMBARD", "VIKING", "VIKING2"]
        )

    def testProfilesMemberMustBeDictionary(self) -> None:
        """A non-dictionary 'profiles' member is rejected."""
        for f_value in ([], "x", "", None, 1):
            with self.subTest(f_value=repr(f_value)):
                f_doc = self._validDocument()
                f_doc["RUN_PROFILES"]["profiles"] = f_value
                self._assertRejected(f_doc, "'profiles' member must be a dictionary")
        self._assertCanonicalStillLoads()

    def testSiteRecordMustBeDictionary(self) -> None:
        """A site record that is not a dictionary is rejected and named."""
        for f_site, f_value in (
            ("DEV", []),
            ("DEV", ""),
            ("DEV", None),
            ("VIKING", "x"),
        ):
            with self.subTest(f_site=f_site, f_value=repr(f_value)):
                self._assertRejected(
                    self._mutated(f_site, (), f_value),
                    f"Profile '{f_site}' must be a dictionary",
                )
        self._assertCanonicalStillLoads()

    def testSiteScalarFieldsMustBeNonEmptyStrings(self) -> None:
        """scheduler, launcher, certification and install_prefix need non-empty strings."""
        f_rows = []
        for f_field in ("scheduler", "launcher", "certification", "install_prefix"):
            for f_value in ("", None, 5):
                f_rows.append(
                    (
                        "DEV",
                        (f_field,),
                        f_value,
                        f"Profile 'DEV'.{f_field} must be a non-empty string",
                    )
                )
        f_rows.append(
            (
                "DEV",
                ("launcher",),
                ["srun"],
                "Profile 'DEV'.launcher must be a non-empty string",
            )
        )
        f_rows.append(
            (
                "VIKING",
                ("scheduler",),
                "",
                "Profile 'VIKING'.scheduler must be a non-empty string",
            )
        )
        self._assertMutationRows(f_rows)

    def testBenchmarkRootsAndExecutablesShape(self) -> None:
        """benchmark_roots and executables must have the exact shape and string values."""
        f_prefix = "Profile 'DEV'.benchmark_roots"
        f_rows: List[Tuple[str, Tuple[str, ...], Any, str]] = []
        for f_value in ([], None, "x"):
            f_rows.append(
                (
                    "DEV",
                    ("benchmark_roots",),
                    f_value,
                    f"{f_prefix} must be a dictionary",
                )
            )
        f_rows += [
            (
                "DEV",
                ("benchmark_roots",),
                {},
                f"{f_prefix} keys mismatch: missing=['hdd', 'ssd'], extra=[]",
            ),
            (
                "DEV",
                ("benchmark_roots", "ssd"),
                _DELETE,
                f"{f_prefix} keys mismatch: missing=['ssd'], extra=[]",
            ),
            (
                "DEV",
                ("benchmark_roots", "scratch"),
                "/s",
                f"{f_prefix} keys mismatch: missing=[], extra=['scratch']",
            ),
            (
                "DEV",
                ("benchmark_roots", "hdd"),
                "",
                f"{f_prefix}['hdd'] must be a non-empty string",
            ),
            (
                "DEV",
                ("benchmark_roots", "ssd"),
                None,
                f"{f_prefix}['ssd'] must be a non-empty string",
            ),
            (
                "DEV",
                ("benchmark_roots", "hdd"),
                3,
                f"{f_prefix}['hdd'] must be a non-empty string",
            ),
        ]
        for f_value in ([], None):
            f_rows.append(
                (
                    "DEV",
                    ("executables",),
                    f_value,
                    "Profile 'DEV'.executables must be a dictionary",
                )
            )
        for f_key, f_value in (("ior", ""), ("lmp", None), ("epocpp", 1)):
            f_rows.append(
                (
                    "DEV",
                    ("executables", f_key),
                    f_value,
                    f"Profile 'DEV'.executables['{f_key}'] must be a non-empty string",
                )
            )
        self._assertMutationRows(f_rows)

        # Missing and extra keys together: the lists are sorted.
        f_doc = self._mutated("DEV", ("benchmark_roots", "ssd"), _DELETE)
        self._mutated("DEV", ("benchmark_roots", "zz"), "/z", f_doc)
        self._mutated("DEV", ("benchmark_roots", "aa"), "/a", f_doc)
        self._assertRejected(
            f_doc, f"{f_prefix} keys mismatch: missing=['ssd'], extra=['aa', 'zz']"
        )
        self._assertCanonicalStillLoads()

    def testModulesAndResourcesShape(self) -> None:
        """modules entries and resources values are type checked."""
        f_rows: List[Tuple[str, Tuple[str, ...], Any, str]] = []
        for f_value in ([""], ["ok", 5], [None]):
            f_rows.append(
                (
                    "DEV",
                    ("modules",),
                    f_value,
                    "Profile 'DEV'.modules entries must be non-empty strings",
                )
            )
        for f_value in ([], None):
            f_rows.append(
                (
                    "DEV",
                    ("resources",),
                    f_value,
                    "Profile 'DEV'.resources must be a dictionary",
                )
            )
        f_rows += [
            (
                "DEV",
                ("resources", "small"),
                [],
                "Profile 'DEV'.resources['small'] must be a dictionary",
            ),
            (
                "DEV",
                ("resources", "large"),
                None,
                "Profile 'DEV'.resources['large'] must be a dictionary",
            ),
            (
                "DEV",
                ("resources", "small", "queue"),
                5,
                "Profile 'DEV'.resources['small']['queue'] must be a string or null",
            ),
            (
                "DEV",
                ("resources", "large", "memory"),
                False,
                "Profile 'DEV'.resources['large']['memory'] must be a string or null",
            ),
            (
                "DEV",
                ("resources", "small", "pmem"),
                ["x"],
                "Profile 'DEV'.resources['small']['pmem'] must be a string or null",
            ),
        ]
        self._assertMutationRows(f_rows)

    def testRankIdentityCancellationAndPoolsShape(self) -> None:
        """rank_identity, cancellation and lustre_pools are shape and type checked."""
        f_rank = "Profile 'DEV'.rank_identity"
        f_cancel = "Profile 'DEV'.cancellation"
        f_rows: List[Tuple[str, Tuple[str, ...], Any, str]] = []
        for f_value in ([], None):
            f_rows.append(
                ("DEV", ("rank_identity",), f_value, f"{f_rank} must be a dictionary")
            )
        for f_value in ("", None, 1):
            f_rows.append(
                (
                    "DEV",
                    ("rank_identity", "global"),
                    f_value,
                    f"{f_rank}['global'] must be a non-empty string",
                )
            )
        for f_value in ("", None):
            f_rows.append(
                (
                    "DEV",
                    ("rank_identity", "node"),
                    f_value,
                    f"{f_rank}['node'] must be a non-empty string",
                )
            )
        for f_value in (5, False):
            f_rows.append(
                (
                    "DEV",
                    ("rank_identity", "local"),
                    f_value,
                    f"{f_rank}['local'] must be a string or null",
                )
            )
        for f_value in ([], None):
            f_rows.append(
                ("DEV", ("cancellation",), f_value, f"{f_cancel} must be a dictionary")
            )
        f_rows += [
            (
                "DEV",
                ("cancellation",),
                {},
                f"{f_cancel} keys mismatch: missing=['grace_seconds', 'poll_interval_seconds'], extra=[]",
            ),
            (
                "DEV",
                ("cancellation", "extra"),
                1,
                f"{f_cancel} keys mismatch: missing=[], extra=['extra']",
            ),
        ]
        for f_value in ([], None):
            f_rows.append(
                (
                    "DEV",
                    ("lustre_pools",),
                    f_value,
                    "Profile 'DEV'.lustre_pools must be a dictionary",
                )
            )
        f_rows += [
            (
                "DEV",
                ("lustre_pools", "hdd"),
                5,
                "Profile 'DEV'.lustre_pools['hdd'] must be a string or null",
            ),
            (
                "DEV",
                ("lustre_pools", "ssd"),
                True,
                "Profile 'DEV'.lustre_pools['ssd'] must be a string or null",
            ),
        ]
        self._assertMutationRows(f_rows)

        # Missing and extra keys together.
        f_doc = self._mutated("DEV", ("cancellation", "poll_interval_seconds"), _DELETE)
        self._mutated("DEV", ("cancellation", "x"), 1, f_doc)
        self._assertRejected(
            f_doc,
            f"{f_cancel} keys mismatch: missing=['poll_interval_seconds'], extra=['x']",
        )
        self._assertCanonicalStillLoads()

    def testNullableFieldsAcceptNullAndEmptyString(self) -> None:
        """Fields documented as 'string or null' accept the empty string."""
        f_canonical = (
            ProfileLoader.load(self.m_env_json_path).getProfile("DEV").toDict()
        )
        for f_local in ("", None):
            with self.subTest(f_local=repr(f_local)):
                f_doc = self._mutated("DEV", ("resources", "small", "queue"), "")
                self._mutated("DEV", ("rank_identity", "local"), f_local, f_doc)
                self._mutated("DEV", ("lustre_pools", "hdd"), "", f_doc)
                f_tmp = tempfile.TemporaryDirectory()
                self.addCleanup(f_tmp.cleanup)
                f_path = os.path.join(f_tmp.name, "profile.json")
                with open(f_path, "w", encoding="utf-8") as f_file:
                    json.dump(f_doc, f_file)
                f_rec = ProfileLoader.load(f_path).getProfile("DEV")
                self.assertEqual(f_rec.resources["small"]["queue"], "")
                if f_local is None:
                    self.assertIsNone(f_rec.rank_identity["local"])
                else:
                    self.assertEqual(f_rec.rank_identity["local"], "")
                self.assertEqual(f_rec.lustre_pools["hdd"], "")
                f_expected = copy.deepcopy(f_canonical)
                f_expected["resources"]["small"]["queue"] = ""
                f_expected["rank_identity"]["local"] = f_local
                f_expected["lustre_pools"]["hdd"] = ""
                self.assertEqual(f_rec.toDict(), f_expected)

    def testLegacyCommandImportsAndEntryDispatch(self) -> None:
        """Verify legacy command classes import correctly and accept expected parameters."""
        # Ensure all main entry classes can be instantiated
        f_compare = CompareMain(f_request=CompareRequest("lsmio", ("test_folder",)))
        self.assertIsInstance(f_compare, CompareMain)

        f_latex = LatexMain(LatexRequest("plots", "sources.yaml", f_tsv_dir="tsv"))
        self.assertIsInstance(f_latex, LatexMain)

        f_hpc = HpcEnvMain()
        self.assertIsInstance(f_hpc, HpcEnvMain)

        f_shell = ShellMain()
        self.assertIsInstance(f_shell, ShellMain)

        f_test = TestMain()
        self.assertIsInstance(f_test, TestMain)

        f_run = RunMain("ior", "small")
        self.assertIsInstance(f_run, RunMain)
