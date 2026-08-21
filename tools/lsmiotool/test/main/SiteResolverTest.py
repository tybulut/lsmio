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
import unittest

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
)


class SiteResolverTest(unittest.TestCase):
    """Unit tests for typed site resolution, immutable policies, and environment detection."""

    def setUp(self) -> None:
        self.m_default_profile_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "etc", "environments.json")
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
            self.assertEqual(f_prof.getBenchmarkRoot(StorageClass.HDD), f_exp[StorageClass.HDD])
            self.assertEqual(f_prof.getBenchmarkRoot(StorageClass.SSD), f_exp[StorageClass.SSD])
            self.assertEqual(f_prof.getBenchmarkRoot("hdd"), f_exp[StorageClass.HDD])
            self.assertEqual(f_prof.getBenchmarkRoot("ssd"), f_exp[StorageClass.SSD])
            self.assertEqual(f_prof.benchmark_roots["hdd"], f_exp[StorageClass.HDD])
            self.assertEqual(f_prof.benchmark_roots["ssd"], f_exp[StorageClass.SSD])
            self.assertEqual(f_prof.install_prefix, f_exp["prefix"])

            # Check executables resolved below prefix/bin
            for f_ex in f_exec_names:
                f_exp_exec_path = f"{f_exp['prefix']}/bin/{f_ex}"
                self.assertEqual(f_prof.executables.getExecutable(f_ex), f_exp_exec_path)
                self.assertEqual(f_prof.executables[f_ex], f_exp_exec_path)
                self.assertEqual(getattr(f_prof.executables, f_ex), f_exp_exec_path)

    def testEverySchedulerLauncherAndConfiguredLabel(self) -> None:
        """Assert scheduler kind, launcher policy, certification state, and test_only label for all profiles."""
        f_expected_meta = {
            "DEV": (SchedulerKind.FAKE, "fake", CertificationState.CONFIGURED, True),
            "VIKING": (SchedulerKind.SLURM, "srun", CertificationState.CONFIGURED, False),
            "VIKING2": (SchedulerKind.SLURM, "srun", CertificationState.CONFIGURED, False),
            "ARCHER2": (SchedulerKind.SLURM, "srun", CertificationState.CONFIGURED, False),
            "ISAMBARD": (SchedulerKind.PBS, "aprun", CertificationState.CONFIGURED, False),
        }

        for f_site_name, (f_exp_sched, f_exp_launch, f_exp_cert, f_exp_test) in f_expected_meta.items():
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
            ResourcePolicy(f_scheduler=SchedulerKind.PBS, f_mail_mode=SlurmMailMode.END_FAIL)

        with self.assertRaises(SiteResolutionError):
            ResourcePolicy(f_scheduler=SchedulerKind.FAKE, f_mail_mode=SlurmMailMode.END_FAIL)

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

        # Viking / Viking2 shapes: memory 8gb, partition None, qos None
        for f_vk in ("VIKING", "VIKING2"):
            f_vk_prof = EnvironmentResolver.resolveProfile(
                f_vk,
                f_user=self.m_test_user,
                f_home=self.m_test_home,
                f_document=self.m_profile_doc,
            )
            for f_shp in ("small", "large"):
                f_pol = f_vk_prof.getResourcePolicy(f_shp)
                self.assertEqual(f_pol.memory, "8gb")
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
            EnvironmentResolver.detect(f_hostname="viking2-login01", f_env={}), "VIKING2"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="node01.viking2.york.ac.uk", f_env={}), "VIKING2"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="viking2", f_env={}), "VIKING2"
        )

        # 2. Viking on hostname containing viking (and not viking2)
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="viking-login01", f_env={}), "VIKING"
        )
        self.assertEqual(
            EnvironmentResolver.detect(f_hostname="node01.viking.york.ac.uk", f_env={}), "VIKING"
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
            EnvironmentResolver.detect(f_hostname="archer2-login01", f_env={}), "ARCHER2"
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
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "DEV"}, f_test_mode=True), "DEV"
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
            EnvironmentResolver.detect(
                f_env={"LSMIO_ENV": "DEV"}, f_test_mode=False
            )

        # 3. Invalid LSMIO_ENV name must fail
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.detect(f_env={"LSMIO_ENV": "UNKNOWN_SITE"})

        # 4. Ambiguous hostname matching multiple sites must fail closed
        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.detect(
                f_hostname="xci-archer2-login", f_env={}
            )

        with self.assertRaises(SiteResolutionError):
            EnvironmentResolver.detect(
                f_hostname="viking-login", f_groups=["archer2"], f_env={}
            )

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
