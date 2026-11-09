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
import os
from typing import Any, Dict, List, Optional, Tuple
import unittest
from unittest.mock import patch

from lsmiotool.lib.profile import ProfileDocument, ProfileLoader, ProfileRecord
from lsmiotool.lib.site import (
    CancellationPolicy,
    CertificationState,
    EnvironmentResolver,
    ExecutableRegistry,
    LauncherPolicy,
    PbsMailMode,
    RankIdentityPolicy,
    ResourcePolicy,
    SchedulerKind,
    SiteProfile,
    SiteProfileRegistry,
    SiteResolutionError,
    SlurmMailMode,
    StorageClass,
    findAdiosPluginLibrary,
    resolveArcher2WorkRoot,
)


class SiteResolverTest(unittest.TestCase):
    """Unit tests for typed site resolution, immutable policies, and environment detection."""

    def setUp(self) -> None:
        self.m_default_profile_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_test_user = "alice"
        self.m_test_home = "/home/alice"

    def testEveryExactRootAndPrefix(self) -> None:
        """Assert exact HDD/SSD roots and install prefix for DEV, VIKING, VIKING2, ARCHER2, ISAMBARD."""
        f_expected_roots = {
            "DEV": {
                StorageClass.HDD: "/home/alice/.lsmio-dev/benchmark",
                StorageClass.SSD: "/home/alice/.lsmio-dev/benchmark",
                "prefix": "/home/alice/src/usr",
            },
            "VIKING": {
                StorageClass.HDD: "/mnt/lustre/users/alice/benchmark",
                StorageClass.SSD: "/mnt/bb/tmp/users/alice/benchmark",
                "prefix": "/home/alice/src/usr",
            },
            "VIKING2": {
                StorageClass.HDD: "/mnt/scratch/users/alice/benchmark",
                StorageClass.SSD: "/mnt/scratch/users/alice/benchmark",
                "prefix": "/home/alice/src/usr",
            },
            "ARCHER2": {
                StorageClass.HDD: "/work/e281/e281/alice/benchmark",
                StorageClass.SSD: "/scratch-nvme/e281/e281/alice/benchmark",
                "prefix": "/work/e281/e281/alice/usr",
            },
            "ISAMBARD": {
                StorageClass.HDD: "/projects/external/alice/benchmark",
                StorageClass.SSD: "/scratch/alice/benchmark",
                "prefix": "/home/alice/src/usr",
            },
        }

        f_exec_names = [
            "ior",
            "lmp",
            "bm_native",
            "bm_adios",
            "bm_rocksdb",
            "bm_leveldb",
            "bm_manager",
        ]

        f_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )
        self.assertIsInstance(f_registry, SiteProfileRegistry)

        for f_site_name, f_exp in f_expected_roots.items():
            f_prof = f_registry.getProfile(f_site_name)
            self.assertEqual(f_prof.name, f_site_name)
            self.assertEqual(
                f_prof.getBenchmarkRoot(StorageClass.HDD), f_exp[StorageClass.HDD]
            )
            self.assertEqual(
                f_prof.getBenchmarkRoot(StorageClass.SSD), f_exp[StorageClass.SSD]
            )
            self.assertEqual(f_prof.getBenchmarkRoot("hdd"), f_exp[StorageClass.HDD])
            self.assertEqual(f_prof.getBenchmarkRoot("ssd"), f_exp[StorageClass.SSD])
            self.assertEqual(f_prof.benchmark_roots["hdd"], f_exp[StorageClass.HDD])
            self.assertEqual(f_prof.benchmark_roots["ssd"], f_exp[StorageClass.SSD])
            self.assertEqual(f_prof.install_prefix, f_exp["prefix"])

            # Check executables resolved below prefix/bin
            for f_ex in f_exec_names:
                f_exp_exec_path = f"{f_exp['prefix']}/bin/{f_ex}"
                self.assertEqual(
                    f_prof.executables.getExecutable(f_ex), f_exp_exec_path
                )
                self.assertEqual(f_prof.executables[f_ex], f_exp_exec_path)
                self.assertEqual(getattr(f_prof.executables, f_ex), f_exp_exec_path)

    def testEverySchedulerLauncherAndConfiguredLabel(self) -> None:
        """Assert scheduler kind, launcher policy, certification state, and test_only label for all profiles."""
        f_expected_meta = {
            "DEV": (SchedulerKind.FAKE, "fake", CertificationState.CONFIGURED, True),
            "VIKING": (
                SchedulerKind.SLURM,
                "srun",
                CertificationState.CONFIGURED,
                False,
            ),
            "VIKING2": (
                SchedulerKind.SLURM,
                "srun",
                CertificationState.CONFIGURED,
                False,
            ),
            "ARCHER2": (
                SchedulerKind.SLURM,
                "srun",
                CertificationState.CONFIGURED,
                False,
            ),
            "ISAMBARD": (
                SchedulerKind.PBS,
                "aprun",
                CertificationState.CONFIGURED,
                False,
            ),
        }

        for f_site_name, (
            f_exp_sched,
            f_exp_launch,
            f_exp_cert,
            f_exp_test,
        ) in f_expected_meta.items():
            f_prof = EnvironmentResolver.resolveProfile(
                f_site_name,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            self.assertEqual(f_prof.scheduler, f_exp_sched)
            self.assertEqual(f_prof.launcher.kind, f_exp_launch)
            self.assertEqual(f_prof.certification, f_exp_cert)
            self.assertEqual(f_prof.certification.value, "configured")
            self.assertEqual(f_prof.test_only, f_exp_test)

    def testBackendTypedMailModesAcceptOnlySlurmEndFailAndPbsAbe(self) -> None:
        """Verify that Slurm profiles decode END_FAIL and PBS decodes ABE into typed enums."""
        for f_slurm_site in ("VIKING", "VIKING2", "ARCHER2"):
            f_prof = EnvironmentResolver.resolveProfile(
                f_slurm_site,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            f_small_pol = f_prof.getResourcePolicy("small")
            f_large_pol = f_prof.getResourcePolicy("large")
            self.assertEqual(f_small_pol.mail_mode, SlurmMailMode.END_FAIL)
            self.assertEqual(f_large_pol.mail_mode, SlurmMailMode.END_FAIL)
            self.assertEqual(f_small_pol.mail_mode.value, "END,FAIL")

        f_isambard = EnvironmentResolver.resolveProfile(
            "ISAMBARD",
            f_user=self.m_test_user,
            f_home=self.m_test_home,
            f_document=self.m_profile_doc,
        )
        f_small_pol = f_isambard.getResourcePolicy("small")
        f_large_pol = f_isambard.getResourcePolicy("large")
        self.assertEqual(f_small_pol.mail_mode, PbsMailMode.ABE)
        self.assertEqual(f_large_pol.mail_mode, PbsMailMode.ABE)
        self.assertEqual(f_small_pol.mail_mode.value, "abe")

        f_dev = EnvironmentResolver.resolveProfile(
            "DEV",
            f_user=self.m_test_user,
            f_home=self.m_test_home,
            f_document=self.m_profile_doc,
        )
        self.assertIsNone(f_dev.getResourcePolicy("small").mail_mode)
        self.assertIsNone(f_dev.getResourcePolicy("large").mail_mode)

    def testCrossBackendRawAndInjectedMailModesReject(self) -> None:
        """Assert rejection of cross-backend enums, raw mail strings, reordered, case-changed, and injected values."""
        # 1. Raw string passed to ResourcePolicy constructor must raise TypeError
        with self.assertRaises(TypeError):
            ResourcePolicy(f_scheduler=SchedulerKind.SLURM, f_mail_mode="END,FAIL")

        with self.assertRaises(TypeError):
            ResourcePolicy(f_scheduler=SchedulerKind.PBS, f_mail_mode="abe")

        # 2. Cross-backend enum construction must fail
        with self.assertRaises(SiteResolutionError):
            ResourcePolicy(f_scheduler=SchedulerKind.SLURM, f_mail_mode=PbsMailMode.ABE)

        with self.assertRaises(SiteResolutionError):
            ResourcePolicy(
                f_scheduler=SchedulerKind.PBS, f_mail_mode=SlurmMailMode.END_FAIL
            )

        with self.assertRaises(SiteResolutionError):
            ResourcePolicy(
                f_scheduler=SchedulerKind.FAKE, f_mail_mode=SlurmMailMode.END_FAIL
            )

        # 3. Modify ProfileRecord with invalid or cross-backend mail_mode strings
        f_orig_rec = self.m_profile_doc.getProfile("VIKING")

        f_invalid_slurm_modes = [
            "abe",
            "FAIL,END",
            "end,fail",
            "END_FAIL",
            "ALL",
            "BEGIN",
            "END,FAIL\n#SBATCH --account=injected",
            "END,FAIL; rm -rf /",
        ]
        for f_bad_mode in f_invalid_slurm_modes:
            f_bad_resources = copy.deepcopy(f_orig_rec.resources)
            f_bad_resources["small"]["mail_mode"] = f_bad_mode
            f_rec = ProfileRecord(
                f_name=f_orig_rec.name,
                f_scheduler=f_orig_rec.scheduler,
                f_launcher=f_orig_rec.launcher,
                f_certification=f_orig_rec.certification,
                f_test_only=f_orig_rec.test_only,
                f_benchmark_roots=f_orig_rec.benchmark_roots,
                f_install_prefix=f_orig_rec.install_prefix,
                f_executables=f_orig_rec.executables,
                f_modules=list(f_orig_rec.modules),
                f_resources=f_bad_resources,
                f_rank_identity=f_orig_rec.rank_identity,
                f_cancellation=f_orig_rec.cancellation,
                f_lustre_pools=f_orig_rec.lustre_pools,
            )
            with self.assertRaises(SiteResolutionError):
                EnvironmentResolver.resolveProfile(
                    f_rec, f_user=self.m_test_user, f_home=self.m_test_home
                )

        f_pbs_rec = self.m_profile_doc.getProfile("ISAMBARD")
        f_invalid_pbs_modes = [
            "END,FAIL",
            "ABE",
            "a",
            "be",
            "bea",
            "abe\n#PBS -m injected",
        ]
        for f_bad_mode in f_invalid_pbs_modes:
            f_bad_resources = copy.deepcopy(f_pbs_rec.resources)
            f_bad_resources["small"]["mail_mode"] = f_bad_mode
            f_rec = ProfileRecord(
                f_name=f_pbs_rec.name,
                f_scheduler=f_pbs_rec.scheduler,
                f_launcher=f_pbs_rec.launcher,
                f_certification=f_pbs_rec.certification,
                f_test_only=f_pbs_rec.test_only,
                f_benchmark_roots=f_pbs_rec.benchmark_roots,
                f_install_prefix=f_pbs_rec.install_prefix,
                f_executables=f_pbs_rec.executables,
                f_modules=list(f_pbs_rec.modules),
                f_resources=f_bad_resources,
                f_rank_identity=f_pbs_rec.rank_identity,
                f_cancellation=f_pbs_rec.cancellation,
                f_lustre_pools=f_pbs_rec.lustre_pools,
            )
            with self.assertRaises(SiteResolutionError):
                EnvironmentResolver.resolveProfile(
                    f_rec, f_user=self.m_test_user, f_home=self.m_test_home
                )

    def testExactPbsSmallLargePolicy(self) -> None:
        """Assert exact Isambard PBS small and large resource policy shapes per Section 1.3."""
        f_isambard = EnvironmentResolver.resolveProfile(
            "ISAMBARD",
            f_user=self.m_test_user,
            f_home=self.m_test_home,
            f_document=self.m_profile_doc,
        )

        f_small = f_isambard.getResourcePolicy("small")
        self.assertEqual(f_small.walltime_policy, "fixed_06:00:00")
        self.assertEqual(f_small.queue, "arm")
        self.assertIsNone(f_small.partition)
        self.assertIsNone(f_small.qos)
        self.assertEqual(f_small.memory, "32GB")
        self.assertEqual(f_small.mail_mode, PbsMailMode.ABE)
        self.assertEqual(f_small.pmem, "8G")
        self.assertEqual(f_small.pvmem, "8G")

        f_large = f_isambard.getResourcePolicy("large")
        self.assertEqual(f_large.walltime_policy, "fixed_06:00:00")
        self.assertEqual(f_large.queue, "arm")
        self.assertIsNone(f_large.partition)
        self.assertIsNone(f_large.qos)
        self.assertEqual(f_large.memory, "32GB")
        self.assertEqual(f_large.mail_mode, PbsMailMode.ABE)
        self.assertIsNone(f_large.pmem)
        self.assertIsNone(f_large.pvmem)

    def testCredentialScope(self) -> None:
        """Verify credential requirement scope for Slurm (VIKING, VIKING2, ARCHER2) vs PBS (ISAMBARD) and DEV."""
        for f_slurm_name in ("VIKING", "VIKING2", "ARCHER2"):
            f_prof = EnvironmentResolver.resolveProfile(
                f_slurm_name,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            self.assertTrue(f_prof.requires_credentials)
            self.assertTrue(f_prof.requires_account)
            self.assertTrue(f_prof.requires_email)

            # Valid credentials succeed
            f_prof.validateCredentials("e281", "user@epcc.ed.ac.uk")

            # Missing or whitespace account fails
            for f_bad_acct in (None, "", "   ", "\t"):
                with self.assertRaises(SiteResolutionError):
                    f_prof.validateCredentials(f_bad_acct, "user@epcc.ed.ac.uk")

            # Missing or whitespace email fails
            for f_bad_email in (None, "", "   ", "\t"):
                with self.assertRaises(SiteResolutionError):
                    f_prof.validateCredentials("e281", f_bad_email)

            # Both missing fails
            with self.assertRaises(SiteResolutionError):
                f_prof.validateCredentials(None, None)

        # PBS and DEV require no credentials
        for f_non_slurm in ("ISAMBARD", "DEV"):
            f_prof = EnvironmentResolver.resolveProfile(
                f_non_slurm,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            self.assertFalse(f_prof.requires_credentials)
            self.assertFalse(f_prof.requires_account)
            self.assertFalse(f_prof.requires_email)
            # Validates without raising on None or empty strings
            f_prof.validateCredentials(None, None)
            f_prof.validateCredentials("", "")

    def testSlurmPolicyAndCredentialScope(self) -> None:
        """Verify Slurm credential requirement scope versus PBS/DEV and partition/memory shapes."""
        for f_slurm_name in ("VIKING", "VIKING2", "ARCHER2"):
            f_prof = EnvironmentResolver.resolveProfile(
                f_slurm_name,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            self.assertTrue(f_prof.requires_credentials)
            self.assertTrue(f_prof.requires_account)
            self.assertTrue(f_prof.requires_email)

            # Valid credentials succeed
            f_prof.validateCredentials("e281", "user@epcc.ed.ac.uk")

            # Missing account or email fails
            with self.assertRaises(SiteResolutionError):
                f_prof.validateCredentials("", "user@epcc.ed.ac.uk")
            with self.assertRaises(SiteResolutionError):
                f_prof.validateCredentials("e281", "")
            with self.assertRaises(SiteResolutionError):
                f_prof.validateCredentials(None, "user@epcc.ed.ac.uk")
            with self.assertRaises(SiteResolutionError):
                f_prof.validateCredentials("e281", None)

        # PBS and DEV require no credentials
        for f_non_slurm in ("ISAMBARD", "DEV"):
            f_prof = EnvironmentResolver.resolveProfile(
                f_non_slurm,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            self.assertFalse(f_prof.requires_credentials)
            self.assertFalse(f_prof.requires_account)
            self.assertFalse(f_prof.requires_email)
            # Validates without raising
            f_prof.validateCredentials(None, None)

        # Archer2 shapes: partition standard, qos standard, memory None
        f_archer2 = EnvironmentResolver.resolveProfile(
            "ARCHER2",
            f_user=self.m_test_user,
            f_home=self.m_test_home,
            f_document=self.m_profile_doc,
        )
        for f_shp in ("small", "large"):
            f_pol = f_archer2.getResourcePolicy(f_shp)
            self.assertEqual(f_pol.partition, "standard")
            self.assertEqual(f_pol.qos, "standard")
            self.assertIsNone(f_pol.memory)
            self.assertEqual(f_pol.walltime_policy, "slurm_nodes")

        # Viking / Viking2 shapes: memory 16gb, partition None, qos None
        for f_vk in ("VIKING", "VIKING2"):
            f_vk_prof = EnvironmentResolver.resolveProfile(
                f_vk,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            for f_shp in ("small", "large"):
                f_pol = f_vk_prof.getResourcePolicy(f_shp)
                self.assertEqual(f_pol.memory, "16gb")
                self.assertIsNone(f_pol.partition)
                self.assertIsNone(f_pol.qos)
                self.assertEqual(f_pol.walltime_policy, "slurm_nodes")

    def testViking2Pools(self) -> None:
        """Verify Viking2 lustre pools scratch.disk and scratch.flash versus None on other sites."""
        f_vk2 = EnvironmentResolver.resolveProfile(
            "VIKING2",
            f_user=self.m_test_user,
            f_home=self.m_test_home,
            f_document=self.m_profile_doc,
        )
        self.assertEqual(f_vk2.lustre_pools["hdd"], "scratch.disk")
        self.assertEqual(f_vk2.lustre_pools["ssd"], "scratch.flash")
        self.assertEqual(f_vk2.getLustrePool(StorageClass.HDD), "scratch.disk")
        self.assertEqual(f_vk2.getLustrePool(StorageClass.SSD), "scratch.flash")
        self.assertEqual(f_vk2.getLustrePool("hdd"), "scratch.disk")
        self.assertEqual(f_vk2.getLustrePool("ssd"), "scratch.flash")

        for f_other in ("DEV", "VIKING", "ARCHER2", "ISAMBARD"):
            f_prof = EnvironmentResolver.resolveProfile(
                f_other,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            self.assertIsNone(f_prof.lustre_pools["hdd"])
            self.assertIsNone(f_prof.lustre_pools["ssd"])
            self.assertIsNone(f_prof.getLustrePool(StorageClass.HDD))
            self.assertIsNone(f_prof.getLustrePool(StorageClass.SSD))

    def testPbsLocalRankNone(self) -> None:
        """Assert that Isambard PBS rank identity policy defines ALPS_APP_PE, hostname, and local_rank is None."""
        f_isambard = EnvironmentResolver.resolveProfile(
            "ISAMBARD",
            f_user=self.m_test_user,
            f_home=self.m_test_home,
            f_document=self.m_profile_doc,
        )
        f_rank = f_isambard.rank_identity
        self.assertEqual(f_rank.global_rank, "ALPS_APP_PE")
        self.assertEqual(f_rank.node_name, "hostname")
        self.assertEqual(f_rank.node, "hostname")
        self.assertIsNone(f_rank.local_rank)
        self.assertEqual(
            f_rank.toDict(),
            {"global": "ALPS_APP_PE", "node": "hostname", "local": None},
        )

        # Slurm profiles and DEV define SLURM_PROCID, SLURMD_NODENAME, SLURM_LOCALID
        for f_site in ("DEV", "VIKING", "VIKING2", "ARCHER2"):
            f_prof = EnvironmentResolver.resolveProfile(
                f_site,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            f_r = f_prof.rank_identity
            self.assertEqual(f_r.global_rank, "SLURM_PROCID")
            self.assertEqual(f_r.node_name, "SLURMD_NODENAME")
            self.assertEqual(f_r.local_rank, "SLURM_LOCALID")

    def testDetectionBranches(self) -> None:
        """Test all hostname, group, and environment detection branches."""
        # 1. Viking2 precedence over Viking on hostname containing viking2
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="viking2-login01", f_env={}),
            "VIKING2",
        )
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="node01.viking2.york.ac.uk", f_env={}
            ),
            "VIKING2",
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="viking2", f_env={}), "VIKING2"
        )

        # 2. Viking on hostname containing viking (and not viking2)
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="viking-login01", f_env={}), "VIKING"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="node01.viking.york.ac.uk", f_env={}),
            "VIKING",
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="viking", f_env={}), "VIKING"
        )

        # 3. Isambard on xci or nid prefix
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="xci-login01", f_env={}), "ISAMBARD"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="nid000123", f_env={}), "ISAMBARD"
        )

        # 4. Archer2 on hostname or groups
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="archer2-login01", f_env={}),
            "ARCHER2",
        )
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="login01", f_groups=["users", "archer2"], f_env={}
            ),
            "ARCHER2",
        )

        # 5. Explicit LSMIO_ENV overrides
        self.assertEqual(
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "ISAMBARD"}), "ISAMBARD"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "viking2"}), "VIKING2"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "VIKING"}), "VIKING"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "ARCHER2"}), "ARCHER2"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "DEV"}, f_test_mode=True),
            "DEV",
        )

        # 6. Unmatched hostname in test mode resolves to DEV
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="unknown-workstation", f_env={}, f_test_mode=True
            ),
            "DEV",
        )

    def testUnknownAmbiguousAndDevProductionFail(self) -> None:
        """Assert fail-closed on unknown host in production, DEV in production, and ambiguous hosts."""
        # 1. Unknown hostname without test_mode must fail
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.detect(
                f_hostname="generic-laptop", f_env={}, f_test_mode=False
            )

        # 2. LSMIO_ENV=DEV without test_mode must fail
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "DEV"}, f_test_mode=False)

        # 3. Invalid LSMIO_ENV name must fail
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "UNKNOWN_SITE"})

    def testDetectionIsFirstMatchInBmtoolOrder(self) -> None:
        """Hosts matching several rules resolve first-match: viking, viking2, archer2, isambard."""
        # ARCHER2 compute/login nodes: nid* in group archer2 is ARCHER2, not ISAMBARD/ambiguous
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="nid001234", f_groups=["e281", "archer2"], f_env={}
            ),
            "ARCHER2",
        )
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="ln01", f_groups=["e281", "archer2"], f_env={}
            ),
            "ARCHER2",
        )
        # Without the archer2 group, nid*/xci* stays ISAMBARD
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="nid001234", f_groups=["e281"], f_env={}
            ),
            "ISAMBARD",
        )
        # archer2 hostname beats the xci prefix; viking beats the archer2 group
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="xci-archer2-login", f_env={}),
            "ARCHER2",
        )
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="viking-login", f_groups=["archer2"], f_env={}
            ),
            "VIKING",
        )
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="login1.viking2.york.ac.uk", f_groups=["archer2"], f_env={}
            ),
            "VIKING2",
        )
        # grep -w semantics: group/host words, not substrings
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="workstation",
                f_groups=["archer2x"],
                f_env={},
                f_test_mode=True,
            ),
            "DEV",
        )
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="vikingfoo", f_env={}, f_test_mode=True
            ),
            "DEV",
        )
        # LSMIO_ENV still overrides detection
        self.assertEqual(
            EnvironmentResolver.detect(
                f_hostname="nid001234",
                f_groups=["archer2"],
                f_env={"LSMIO_ENV": "ISAMBARD"},
            ),
            "ISAMBARD",
        )

    def testResolveArcher2WorkRoot(self) -> None:
        """ARCHER2_WORK_ROOT override is honoured; default is /work/e281/e281/$USER."""
        self.assertEqual(
            resolveArcher2WorkRoot({"USER": "alice"}), "/work/e281/e281/alice"
        )
        self.assertEqual(
            resolveArcher2WorkRoot({"USER": "alice", "ARCHER2_WORK_ROOT": ""}),
            "/work/e281/e281/alice",
        )
        self.assertEqual(
            resolveArcher2WorkRoot(
                {"USER": "alice", "ARCHER2_WORK_ROOT": "/work/x/y/alice/"}
            ),
            "/work/x/y/alice",
        )
        with self.assertRaises(SiteResolutionError):
            resolveArcher2WorkRoot({"ARCHER2_WORK_ROOT": "relative/path"})
        with self.assertRaises(SiteResolutionError):
            resolveArcher2WorkRoot({"ARCHER2_WORK_ROOT": "/work/a\nb"})
        with self.assertRaises(SiteResolutionError):
            resolveArcher2WorkRoot({"USER": "../evil"})

    def testFindAdiosPluginLibrary(self) -> None:
        """findAdiosPluginLibrary finds liblsmio_adios.so/.dylib under <prefix>/lib or returns None."""
        import tempfile

        with tempfile.TemporaryDirectory() as f_prefix:
            self.assertIsNone(findAdiosPluginLibrary(f_prefix))
            os.makedirs(os.path.join(f_prefix, "lib"))
            self.assertIsNone(findAdiosPluginLibrary(f_prefix))

            f_dylib = os.path.join(f_prefix, "lib", "liblsmio_adios.dylib")
            open(f_dylib, "w").close()
            self.assertEqual(findAdiosPluginLibrary(f_prefix), f_dylib)

            f_so = os.path.join(f_prefix, "lib", "liblsmio_adios.so")
            open(f_so, "w").close()
            self.assertEqual(findAdiosPluginLibrary(f_prefix), f_so)

            # lib64 is not where ADIOS2_PLUGIN_PATH points
            os.remove(f_so)
            os.remove(f_dylib)
            os.makedirs(os.path.join(f_prefix, "lib64"))
            open(os.path.join(f_prefix, "lib64", "liblsmio_adios.so"), "w").close()
            self.assertIsNone(findAdiosPluginLibrary(f_prefix))

        with self.assertRaises(SiteResolutionError):
            findAdiosPluginLibrary("")

    def testUnresolvedTemplateFails(self) -> None:
        """Assert rejection of unresolved placeholders, escaping paths (..), and invalid username/home."""
        # 1. Unresolved template placeholder
        f_orig_rec = self.m_profile_doc.getProfile("VIKING")
        f_bad_roots = copy.deepcopy(f_orig_rec.benchmark_roots)
        f_bad_roots["hdd"] = "/mnt/lustre/users/{unknown_var}/benchmark"
        f_rec = ProfileRecord(
            f_name=f_orig_rec.name,
            f_scheduler=f_orig_rec.scheduler,
            f_launcher=f_orig_rec.launcher,
            f_certification=f_orig_rec.certification,
            f_test_only=f_orig_rec.test_only,
            f_benchmark_roots=f_bad_roots,
            f_install_prefix=f_orig_rec.install_prefix,
            f_executables=f_orig_rec.executables,
            f_modules=list(f_orig_rec.modules),
            f_resources=f_orig_rec.resources,
            f_rank_identity=f_orig_rec.rank_identity,
            f_cancellation=f_orig_rec.cancellation,
            f_lustre_pools=f_orig_rec.lustre_pools,
        )
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.resolveProfile(
                f_rec, f_user=self.m_test_user, f_home=self.m_test_home
            )

        # 2. Escaping path traversal in template
        f_bad_prefix_roots = copy.deepcopy(f_orig_rec.benchmark_roots)
        f_bad_prefix_roots["hdd"] = "/mnt/lustre/users/{user}/benchmark/../../escaped"
        f_rec_escape = ProfileRecord(
            f_name=f_orig_rec.name,
            f_scheduler=f_orig_rec.scheduler,
            f_launcher=f_orig_rec.launcher,
            f_certification=f_orig_rec.certification,
            f_test_only=f_orig_rec.test_only,
            f_benchmark_roots=f_bad_prefix_roots,
            f_install_prefix=f_orig_rec.install_prefix,
            f_executables=f_orig_rec.executables,
            f_modules=list(f_orig_rec.modules),
            f_resources=f_orig_rec.resources,
            f_rank_identity=f_orig_rec.rank_identity,
            f_cancellation=f_orig_rec.cancellation,
            f_lustre_pools=f_orig_rec.lustre_pools,
        )
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.resolveProfile(
                f_rec_escape, f_user=self.m_test_user, f_home=self.m_test_home
            )

        # 3. Path traversal in username
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.resolveProfile(
                "VIKING",
                f_user="../baduser",
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )

        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.resolveProfile(
                "VIKING",
                f_user="bad/user",
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )

        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.resolveProfile(
                "VIKING",
                f_user="",
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )

        # 4. Path traversal or relative path in home
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.resolveProfile(
                "VIKING",
                f_user=self.m_test_user,
                f_home="relative/home",
                f_document=self.m_profile_doc,
            )

        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.resolveProfile(
                "VIKING",
                f_user=self.m_test_user,
                f_home="/home/alice/../escape",
                f_document=self.m_profile_doc,
            )

    def _vikingProfile(self) -> SiteProfile:
        return EnvironmentResolver.resolveProfile(
            "VIKING",
            f_user=self.m_test_user,
            f_home=self.m_test_home,
            f_document=self.m_profile_doc,
        )

    def _slurmPolicy(self) -> ResourcePolicy:
        return ResourcePolicy(
            f_scheduler=SchedulerKind.SLURM,
            f_walltime_policy="short",
            f_partition="nodes",
            f_qos="std",
            f_memory="4G",
            f_mail_mode=SlurmMailMode.END_FAIL,
        )

    def testArcher2WorkRootFallsBackToLoginName(self) -> None:
        """Assert the ARCHER2 work root falls back to the login name and reports an unknown one."""
        for f_env in [{"USER": ""}, {"USER": "  "}, {}]:
            with self.subTest(f_env=f_env):
                with patch("getpass.getuser", return_value="bob") as f_getuser:
                    self.assertEqual(
                        resolveArcher2WorkRoot(f_env), "/work/e281/e281/bob"
                    )
                f_getuser.assert_called_once_with()
        for f_env, f_error in [
            ({"USER": ""}, OSError("no login")),
            ({}, KeyError("uid")),
        ]:
            with self.subTest(f_error=f_error):
                with patch("getpass.getuser", side_effect=f_error):
                    with self.assertRaises(SiteResolutionError) as f_cm:
                        resolveArcher2WorkRoot(f_env)
                self.assertEqual(
                    str(f_cm.exception),
                    "Cannot resolve ARCHER2 work root: USER is unset and the login name is unknown",
                )
                self.assertIs(f_cm.exception.__cause__, f_error)
        with patch("getpass.getuser", return_value=""):
            with self.assertRaises(SiteResolutionError) as f_cm:
                resolveArcher2WorkRoot({})
        self.assertEqual(
            str(f_cm.exception), "Invalid user name for ARCHER2 work root: ''"
        )
        f_env_alice = {"USER": "alice"}
        with patch("getpass.getuser") as f_getuser:
            self.assertEqual(
                resolveArcher2WorkRoot(f_env_alice), "/work/e281/e281/alice"
            )
        f_getuser.assert_not_called()
        self.assertEqual(f_env_alice, {"USER": "alice"})

    def testPolicyConstructorsRejectInvalidArguments(self) -> None:
        """Assert policy constructors reject invalid arguments with their exact messages."""
        f_rows: List[Tuple[Any, type, str]] = []
        for f_val in ["", None, 5]:
            f_rows.append(
                (
                    lambda f_v=f_val: LauncherPolicy(f_v),
                    SiteResolutionError,
                    f"Launcher kind must be a non-empty string, got: {f_val!r}",
                )
            )
        for f_val in ["", None]:
            f_rows.append(
                (
                    lambda f_v=f_val: RankIdentityPolicy(f_v, "N"),
                    SiteResolutionError,
                    f"global_rank must be a non-empty string, got: {f_val!r}",
                )
            )
            f_rows.append(
                (
                    lambda f_v=f_val: RankIdentityPolicy("G", f_v),
                    SiteResolutionError,
                    f"node_name must be a non-empty string, got: {f_val!r}",
                )
            )
        for f_val in [5, b"x"]:
            f_rows.append(
                (
                    lambda f_v=f_val: RankIdentityPolicy("G", "N", f_v),
                    SiteResolutionError,
                    f"local_rank must be str or None, got: {f_val!r}",
                )
            )
        for f_val in [0, -1, "5", 1.5]:
            f_rows.append(
                (
                    lambda f_v=f_val: CancellationPolicy(f_v, 5),
                    SiteResolutionError,
                    f"poll_interval_seconds must be a positive integer, got: {f_val!r}",
                )
            )
        for f_val in [0, -2, "1", 2.0]:
            f_rows.append(
                (
                    lambda f_v=f_val: CancellationPolicy(5, f_v),
                    SiteResolutionError,
                    f"grace_seconds must be a positive integer, got: {f_val!r}",
                )
            )
        f_rows.append(
            (
                lambda: ResourcePolicy(
                    f_scheduler=SchedulerKind.SLURM,
                    f_mail_mode=5,  # type: ignore[arg-type]
                ),
                TypeError,
                "mail_mode must be SlurmMailMode, PbsMailMode, or None, got: int",
            )
        )
        f_rows.append(
            (
                lambda: ResourcePolicy(f_mail_mode=SchedulerKind.SLURM),  # type: ignore[arg-type]
                TypeError,
                "mail_mode must be SlurmMailMode, PbsMailMode, or None, got: SchedulerKind",
            )
        )
        f_rows.append(
            (
                lambda: ResourcePolicy(f_scheduler="slurm"),  # type: ignore[arg-type]
                TypeError,
                "scheduler must be a SchedulerKind enum, got: str",
            )
        )
        for f_index, (f_call, f_type, f_message) in enumerate(f_rows):
            with self.subTest(f_index=f_index, f_message=f_message):
                with self.assertRaises(f_type) as f_cm:
                    f_call()
                self.assertIs(type(f_cm.exception), f_type)
                self.assertEqual(str(f_cm.exception), f_message)
        # Observation O5: a bool is an int, so CancellationPolicy(True, True) is accepted.
        self.assertEqual(
            repr(CancellationPolicy(True, True)),  # type: ignore[arg-type]
            "CancellationPolicy(poll_interval_seconds=True, grace_seconds=True)",
        )

    def testFrozenValueObjectsRejectSetAndDelete(self) -> None:
        """Assert frozen value objects reject attribute assignment and deletion and stay unchanged."""
        f_vk = self._vikingProfile()
        f_rows = [
            (LauncherPolicy("srun", "pmi2"), "m_kind"),
            (
                RankIdentityPolicy("SLURM_PROCID", "SLURMD_NODENAME", "SLURM_LOCALID"),
                "m_global_rank",
            ),
            (CancellationPolicy(5, 30), "m_grace_seconds"),
            (self._slurmPolicy(), "m_queue"),
            (ExecutableRegistry(f_vk.executables.toDict()), "m_executables"),
        ]
        for f_obj, f_slot in f_rows:
            f_name = type(f_obj).__name__
            with self.subTest(f_name=f_name):
                f_before = f_obj.toDict()
                with self.assertRaises(AttributeError) as f_cm:
                    setattr(f_obj, f_slot, "x")
                self.assertEqual(
                    str(f_cm.exception), f"Cannot modify immutable {f_name}"
                )
                with self.assertRaises(AttributeError) as f_cm:
                    delattr(f_obj, f_slot)
                self.assertEqual(
                    str(f_cm.exception),
                    f"Cannot delete attribute from immutable {f_name}",
                )
                self.assertEqual(f_obj.toDict(), f_before)

    def testUnfrozenValueObjectsSetAndDelete(self) -> None:
        """Assert objects that are not frozen yet allow slot assignment and deletion."""
        for f_cls, f_slot, f_value in [
            (LauncherPolicy, "m_kind", "k"),
            (RankIdentityPolicy, "m_node_name", "n"),
            (CancellationPolicy, "m_grace_seconds", 3),
            (ResourcePolicy, "m_queue", "q"),
            (ExecutableRegistry, "m_executables", {"a": "/a"}),
        ]:
            with self.subTest(f_cls=f_cls.__name__):
                f_raw = f_cls.__new__(f_cls)
                setattr(f_raw, f_slot, f_value)
                self.assertTrue(hasattr(f_raw, f_slot))
                self.assertEqual(getattr(f_raw, f_slot), f_value)
                delattr(f_raw, f_slot)
                self.assertFalse(hasattr(f_raw, f_slot))
                with self.assertRaises(AttributeError):
                    getattr(f_raw, f_slot)

    def testLauncherPolicyDictAndRepr(self) -> None:
        """Assert LauncherPolicy dictionary and repr include the srun MPI mode only when set."""
        f_srun = LauncherPolicy("srun", "pmi2")
        f_mpirun = LauncherPolicy("mpirun")
        self.assertEqual(f_srun.toDict(), {"kind": "srun", "srun_mpi": "pmi2"})
        self.assertEqual(f_mpirun.toDict(), {"kind": "mpirun"})
        self.assertEqual(repr(f_srun), "LauncherPolicy(kind='srun', srun_mpi='pmi2')")
        self.assertEqual(repr(f_mpirun), "LauncherPolicy(kind='mpirun')")

    def testValueObjectReprAndEquality(self) -> None:
        """Assert value object equality and exact repr strings."""
        f_vk = self._vikingProfile()
        f_other_exec = {
            f_key: "/opt/x/bin/" + f_key
            for f_key in sorted(ExecutableRegistry.REQUIRED_EXECUTABLES)
        }
        f_rows: List[Tuple[Any, Any, Any, Any]] = [
            (
                LauncherPolicy("srun", "pmi2"),
                LauncherPolicy("srun", "pmi2"),
                LauncherPolicy("mpirun"),
                "srun",
            ),
            (
                RankIdentityPolicy("SLURM_PROCID", "SLURMD_NODENAME", "SLURM_LOCALID"),
                RankIdentityPolicy("SLURM_PROCID", "SLURMD_NODENAME", "SLURM_LOCALID"),
                RankIdentityPolicy("SLURM_PROCID", "SLURMD_NODENAME"),
                "x",
            ),
            (
                CancellationPolicy(5, 30),
                CancellationPolicy(5, 30),
                CancellationPolicy(5, 31),
                5,
            ),
            (
                self._slurmPolicy(),
                self._slurmPolicy(),
                ResourcePolicy(
                    f_scheduler=SchedulerKind.SLURM,
                    f_walltime_policy="short",
                    f_partition="nodes",
                    f_qos="std",
                    f_memory="8G",
                    f_mail_mode=SlurmMailMode.END_FAIL,
                ),
                "x",
            ),
            (
                ExecutableRegistry(f_vk.executables.toDict()),
                ExecutableRegistry(f_vk.executables.toDict()),
                ExecutableRegistry(f_other_exec),
                f_vk.executables.toDict(),
            ),
        ]
        for f_obj, f_twin, f_diff, f_foreign in f_rows:
            with self.subTest(f_name=type(f_obj).__name__):
                self.assertTrue(f_obj == f_twin)
                self.assertFalse(f_obj == f_diff)
                self.assertFalse(f_obj == f_foreign)
        self.assertEqual(
            repr(
                RankIdentityPolicy("SLURM_PROCID", "SLURMD_NODENAME", "SLURM_LOCALID")
            ),
            "RankIdentityPolicy(global_rank='SLURM_PROCID', node_name='SLURMD_NODENAME', local_rank='SLURM_LOCALID')",
        )
        self.assertEqual(
            repr(RankIdentityPolicy("PMI_RANK", "HOST")),
            "RankIdentityPolicy(global_rank='PMI_RANK', node_name='HOST', local_rank=None)",
        )
        self.assertEqual(
            repr(CancellationPolicy(5, 30)),
            "CancellationPolicy(poll_interval_seconds=5, grace_seconds=30)",
        )
        self.assertEqual(
            repr(self._slurmPolicy()),
            "ResourcePolicy(scheduler=<SchedulerKind.SLURM: 'slurm'>, walltime_policy='short', "
            "queue=None, partition='nodes', qos='std', memory='4G', "
            "mail_mode=<SlurmMailMode.END_FAIL: 'END,FAIL'>, pmem=None, pvmem=None)",
        )
        self.assertEqual(
            repr(ExecutableRegistry(f_other_exec)),
            f"ExecutableRegistry({f_other_exec!r})",
        )

    def testResourcePolicySchedulerScope(self) -> None:
        """Assert the scheduler scope of resource policies and the Fake scheduler mail rule."""
        f_rows: List[Tuple[ResourcePolicy, Optional[SchedulerKind], bool]] = [
            (ResourcePolicy(f_queue="q"), None, False),
            (ResourcePolicy(f_mail_mode=PbsMailMode.ABE), None, False),
            (ResourcePolicy(f_scheduler=SchedulerKind.FAKE), SchedulerKind.FAKE, False),
            (
                ResourcePolicy(
                    f_scheduler=SchedulerKind.PBS,
                    f_mail_mode=PbsMailMode.ABE,
                    f_queue="workq",
                ),
                SchedulerKind.PBS,
                False,
            ),
            (self._slurmPolicy(), SchedulerKind.SLURM, True),
        ]
        for f_index, (f_policy, f_kind, f_requires) in enumerate(f_rows):
            with self.subTest(f_index=f_index):
                self.assertIs(f_policy.scheduler, f_kind)
                self.assertIs(f_policy.requires_credentials, f_requires)
                self.assertIs(f_policy.requires_account, f_requires)
                self.assertIs(f_policy.requires_email, f_requires)
        self.assertIs(f_rows[1][0].mail_mode, PbsMailMode.ABE)
        with self.assertRaises(SiteResolutionError) as f_cm:
            ResourcePolicy(
                f_scheduler=SchedulerKind.FAKE, f_mail_mode=SlurmMailMode.END_FAIL
            )
        self.assertEqual(
            str(f_cm.exception),
            "Fake scheduler cannot accept mail_mode: SlurmMailMode.END_FAIL",
        )

    def testValidateCredentialsScope(self) -> None:
        """Assert credential validation applies to Slurm only and rejects blank accounts and emails."""
        f_pbs = ResourcePolicy(f_scheduler=SchedulerKind.PBS, f_queue="workq")
        for f_policy in [f_pbs, ResourcePolicy()]:
            with self.subTest(f_scheduler=f_policy.scheduler):
                self.assertIsNone(f_policy.validateCredentials())
                self.assertIsNone(f_policy.validateCredentials(None, None))
        f_slurm = self._slurmPolicy()
        for f_account in [None, "", "  "]:
            with self.subTest(f_account=f_account):
                with self.assertRaises(SiteResolutionError) as f_cm:
                    f_slurm.validateCredentials(f_account, "e@x")
                self.assertEqual(
                    str(f_cm.exception),
                    "Slurm scheduler policy requires a non-empty account (SB_ACCOUNT)",
                )
        for f_email in [None, "", "   "]:
            with self.subTest(f_email=f_email):
                with self.assertRaises(SiteResolutionError) as f_cm:
                    f_slurm.validateCredentials("acc", f_email)
                self.assertEqual(
                    str(f_cm.exception),
                    "Slurm scheduler policy requires a non-empty email (SB_EMAIL)",
                )
        self.assertIsNone(f_slurm.validateCredentials("acc", "e@x"))
        # Observation O6: a non-string account is accepted through str().
        self.assertIsNone(f_slurm.validateCredentials(123, "e@x"))  # type: ignore[arg-type]

    def testExecutableRegistryRejectsMissingAndRelative(self) -> None:
        """Assert the executable registry rejects missing, relative and empty executable paths."""
        f_ex = dict(self._vikingProfile().executables.toDict())
        f_copy = dict(f_ex)
        f_without = {f_k: f_v for f_k, f_v in f_ex.items() if f_k not in ("ior", "lmp")}
        f_rows: List[Tuple[Dict[str, Any], str]] = [
            (f_without, "Missing required executables in registry: ['ior', 'lmp']"),
            (
                {},
                "Missing required executables in registry: ['bm_adios', 'bm_leveldb', "
                "'bm_manager', 'bm_native', 'bm_rocksdb', 'ior', 'lmp']",
            ),
            (
                {**f_ex, "ior": "bin/ior"},
                "Executable 'ior' path must be an absolute path, got: 'bin/ior'",
            ),
            (
                {**f_ex, "lmp": None},
                "Executable 'lmp' path must be an absolute path, got: None",
            ),
            (
                {**f_ex, "lmp": ""},
                "Executable 'lmp' path must be an absolute path, got: ''",
            ),
        ]
        for f_index, (f_dict, f_message) in enumerate(f_rows):
            with self.subTest(f_index=f_index):
                with self.assertRaises(SiteResolutionError) as f_cm:
                    ExecutableRegistry(f_dict)
                self.assertEqual(str(f_cm.exception), f_message)
        self.assertEqual(f_ex, f_copy)

    def testSiteProfileConstructorRejectsInvalidArguments(self) -> None:
        """Assert SiteProfile validates every constructor argument with its exact message."""
        f_vk = self._vikingProfile()
        f_roots = dict(f_vk.benchmark_roots)
        f_res = dict(f_vk.resources)
        f_small = f_res["small"]
        f_ex = f_vk.executables.toDict()
        f_kw: Dict[str, Any] = dict(
            f_name=f_vk.name,
            f_scheduler=f_vk.scheduler,
            f_launcher=f_vk.launcher,
            f_certification=f_vk.certification,
            f_test_only=f_vk.test_only,
            f_benchmark_roots=f_vk.benchmark_roots,
            f_install_prefix=f_vk.install_prefix,
            f_executables=f_vk.executables,
            f_modules=f_vk.modules,
            f_resources=f_vk.resources,
            f_rank_identity=f_vk.rank_identity,
            f_cancellation=f_vk.cancellation,
            f_lustre_pools=f_vk.lustre_pools,
        )
        f_valid = SiteProfile(**f_kw)
        self.assertEqual(f_valid.toDict(), f_vk.toDict())
        self.assertEqual(f_valid.name, "VIKING")

        f_hdd = StorageClass.HDD
        f_ssd = StorageClass.SSD
        f_rows: List[Tuple[str, Any, str]] = [
            ("f_name", "", "Site name must be a non-empty string, got: ''"),
            ("f_name", None, "Site name must be a non-empty string, got: None"),
            (
                "f_scheduler",
                "slurm",
                "Scheduler must be a SchedulerKind enum, got: 'slurm'",
            ),
            ("f_launcher", "srun", "Launcher must be a LauncherPolicy, got: 'srun'"),
            (
                "f_certification",
                "configured",
                "Certification must be a CertificationState enum, got: 'configured'",
            ),
            ("f_test_only", 0, "test_only must be a boolean, got: 0"),
            ("f_test_only", "false", "test_only must be a boolean, got: 'false'"),
            (
                "f_install_prefix",
                "opt/lsmio",
                "install_prefix must be an absolute path, got: 'opt/lsmio'",
            ),
            (
                "f_install_prefix",
                None,
                "install_prefix must be an absolute path, got: None",
            ),
            (
                "f_install_prefix",
                "",
                "install_prefix must be an absolute path, got: ''",
            ),
            (
                "f_executables",
                f_ex,
                f"executables must be an ExecutableRegistry, got: {f_ex!r}",
            ),
            (
                "f_rank_identity",
                None,
                "rank_identity must be a RankIdentityPolicy, got: None",
            ),
            (
                "f_cancellation",
                (5, 30),
                "cancellation must be a CancellationPolicy, got: (5, 30)",
            ),
            (
                "f_benchmark_roots",
                {**f_roots, "hdd": "scratch/hdd"},
                f"Benchmark root for {f_hdd} must be an absolute path, got: 'scratch/hdd'",
            ),
            (
                "f_benchmark_roots",
                {StorageClass.SSD: f_roots["ssd"], StorageClass.HDD: None},
                f"Benchmark root for {f_hdd} must be an absolute path, got: None",
            ),
            (
                "f_benchmark_roots",
                {"hdd": f_roots["hdd"]},
                f"Missing benchmark root for storage class: {f_ssd}",
            ),
            (
                "f_lustre_pools",
                {"ssd": None},
                f"Missing lustre pool for storage class: {f_hdd}",
            ),
            (
                "f_resources",
                {"small": f_small},
                "resources must contain exactly 'small' and 'large' shapes, got: {'small'}",
            ),
            (
                "f_resources",
                {**f_res, "huge": f_small},
                "resources must contain exactly 'small' and 'large' shapes, got: ",
            ),
            (
                "f_resources",
                {"small": f_small, "large": {"queue": "q"}},
                "Resource policy for 'large' must be ResourcePolicy, got: {'queue': 'q'}",
            ),
        ]
        for f_key, f_val, f_message in f_rows:
            with self.subTest(f_key=f_key, f_val=f_val):
                f_args = dict(f_kw)
                f_args[f_key] = f_val
                with self.assertRaises(SiteResolutionError) as f_cm:
                    SiteProfile(**f_args)
                if f_message.endswith("got: "):
                    # Set order is not stable, so only the prefix is pinned.
                    self.assertTrue(str(f_cm.exception).startswith(f_message))
                else:
                    self.assertEqual(str(f_cm.exception), f_message)
        # Observation O7: an unknown storage class key escapes as ValueError.
        f_args = dict(f_kw)
        f_args["f_benchmark_roots"] = {**f_roots, "nvme": "/x"}
        with self.assertRaises(ValueError) as f_cm:
            SiteProfile(**f_args)
        self.assertNotIsInstance(f_cm.exception, SiteResolutionError)
        self.assertEqual(str(f_cm.exception), "'nvme' is not a valid StorageClass")
        self.assertEqual(f_vk.toDict(), SiteProfile(**f_kw).toDict())
