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

import os
import re
import shlex
import sys
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union
import unittest

from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import ScalePoint
from lsmiotool.lib.scheduler import (
    JobSpec,
    PbsScriptRenderer,
    SchedulerError,
    SchedulerKind,
    SchedulerScriptError,
    SchedulerScriptRenderer,
    WorkerExecutableValidator,
)
from lsmiotool.lib.site import (
    CertificationState,
    EnvironmentResolver,
    PbsMailMode,
    ResourcePolicy,
    SiteProfile,
    SlurmMailMode,
)
from lsmiotool.lib.worker import ModuleSetup


class PbsRendererTest(unittest.TestCase):
    """Unit test suite verifying exact Isambard PBS resource rendering and directives."""

    def setUp(self) -> None:
        self.m_etc_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_etc_path)
        self.m_isambard_profile = EnvironmentResolver.resolveProfile(
            "ISAMBARD", f_user="testuser", f_home="/tmp"
        )
        self.m_dev_profile = EnvironmentResolver.resolveProfile(
            "DEV", f_user="testuser", f_home="/tmp"
        )

        # Standard test parameters
        self.m_worker_path = "/opt/lsmio/bin/lsmiotool-worker"
        self.m_manifest_path = "/tmp/benchmark/runs/run_001/manifest.json"
        self.m_job_name = "lm-0123456789abcdef01234567"
        self.m_output_path = "/tmp/benchmark/runs/run_001/logs/0-tasks-8.out"
        self.m_error_path = "/tmp/benchmark/runs/run_001/logs/0-tasks-8.err"

    def testGoldenLocalBakeSmallScriptsUseAbe(self) -> None:
        """Validates golden PBS scripts for local (1 task), bake (1..8 tasks), and small (1..48 tasks) with ppn=1."""
        # Scale points: local=[1], bake=[1, 2, 4, 8], small=[1, 2, 4, 8, 16, 24, 32, 40, 48]
        f_small_task_counts = [1, 2, 4, 8, 16, 24, 32, 40, 48]

        for f_tasks in f_small_task_counts:
            f_point = ScalePoint(f_tasks=f_tasks, f_ppn=1, f_nodes=f_tasks)
            f_out_path = f"/tmp/benchmark/runs/run_001/logs/0-tasks-{f_tasks}.out"
            f_err_path = f"/tmp/benchmark/runs/run_001/logs/0-tasks-{f_tasks}.err"

            f_script = PbsScriptRenderer.render(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_worker_executable=self.m_worker_path,
                f_manifest_path=self.m_manifest_path,
                f_job_name=self.m_job_name,
                f_output_path=f_out_path,
                f_error_path=f_err_path,
                f_mail_mode=PbsMailMode.ABE,
            )

            # Assert complete script structure
            f_lines = [f_l.strip() for f_l in f_script.strip().splitlines() if f_l.strip()]

            # 1. Shebang
            self.assertEqual(f_lines[0], "#!/bin/bash")

            # 2. Mandated PBS Directive Order:
            # 1. #PBS -q arm
            self.assertEqual(f_lines[1], "#PBS -q arm")
            # 2. #PBS -m abe
            self.assertEqual(f_lines[2], "#PBS -m abe")
            # 3. #PBS -N <job_name>
            self.assertEqual(f_lines[3], f"#PBS -N {self.m_job_name}")
            # 4. #PBS -l select=<nodes>:ncpus=1:mpiprocs=1:mem=32GB
            self.assertEqual(
                f_lines[4],
                f"#PBS -l select={f_tasks}:ncpus=1:mpiprocs=1:mem=32GB",
            )
            # 5. Small scale: pmem=8G, pvmem=8G
            self.assertEqual(f_lines[5], "#PBS -l pmem=8G")
            self.assertEqual(f_lines[6], "#PBS -l pvmem=8G")
            # 6. Fixed walltime=06:00:00
            self.assertEqual(f_lines[7], "#PBS -l walltime=06:00:00")
            # 7. Output path
            self.assertEqual(f_lines[8], f"#PBS -o {f_out_path}")
            # 8. Error path
            self.assertEqual(f_lines[9], f"#PBS -e {f_err_path}")

            # 3. Shell fail-fast option
            self.assertEqual(f_lines[10], "set -euo pipefail")

            # 4. Module Preamble: check purge and all 27 Isambard modules
            self.assertEqual(f_lines[11], "module purge")
            f_module_lines = f_lines[12:39]
            self.assertEqual(len(f_module_lines), 27)
            for f_mod_name in self.m_isambard_profile.modules:
                self.assertIn(f"module load {shlex.quote(f_mod_name)}", f_module_lines)

            # 5. Worker execution tail
            f_expected_tail = (
                f"exec {shlex.quote(self.m_worker_path)} allocation "
                f"{shlex.quote(self.m_manifest_path)} {shlex.quote(f'0-tasks-{f_tasks}')}"
            )
            self.assertEqual(f_lines[39], f_expected_tail)

    def testGoldenEveryLargeBoundary(self) -> None:
        """Validates golden PBS scripts for large scale boundaries (4..256 tasks, ppn=4) omitting pmem/pvmem."""
        # Large scale points: [4, 8, 16, 32, 64, 128, 192, 256] at ppn=4
        f_large_task_counts = [4, 8, 16, 32, 64, 128, 192, 256]

        for f_tasks in f_large_task_counts:
            f_nodes = f_tasks // 4
            f_point = ScalePoint(f_tasks=f_tasks, f_ppn=4, f_nodes=f_nodes)
            f_out_path = f"/tmp/benchmark/runs/run_001/logs/0-tasks-{f_tasks}.out"
            f_err_path = f"/tmp/benchmark/runs/run_001/logs/0-tasks-{f_tasks}.err"

            f_script = PbsScriptRenderer.render(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_worker_executable=self.m_worker_path,
                f_manifest_path=self.m_manifest_path,
                f_job_name=self.m_job_name,
                f_output_path=f_out_path,
                f_error_path=f_err_path,
                f_mail_mode=PbsMailMode.ABE,
            )

            f_lines = [f_l.strip() for f_l in f_script.strip().splitlines() if f_l.strip()]

            # 1. Shebang
            self.assertEqual(f_lines[0], "#!/bin/bash")

            # 2. Mandated PBS Directive Order:
            # 1. #PBS -q arm
            self.assertEqual(f_lines[1], "#PBS -q arm")
            # 2. #PBS -m abe
            self.assertEqual(f_lines[2], "#PBS -m abe")
            # 3. #PBS -N <job_name>
            self.assertEqual(f_lines[3], f"#PBS -N {self.m_job_name}")
            # 4. #PBS -l select=<nodes>:ncpus=4:mpiprocs=4:mem=32GB
            self.assertEqual(
                f_lines[4],
                f"#PBS -l select={f_nodes}:ncpus=4:mpiprocs=4:mem=32GB",
            )
            # Large scale: pmem and pvmem MUST BE OMITTED!
            self.assertFalse(any("-l pmem" in f_l for f_l in f_lines))
            self.assertFalse(any("-l pvmem" in f_l for f_l in f_lines))

            # 5. Fixed walltime=06:00:00
            self.assertEqual(f_lines[5], "#PBS -l walltime=06:00:00")
            # 6. Output path
            self.assertEqual(f_lines[6], f"#PBS -o {f_out_path}")
            # 7. Error path
            self.assertEqual(f_lines[7], f"#PBS -e {f_err_path}")

            # 3. Shell fail-fast option
            self.assertEqual(f_lines[8], "set -euo pipefail")

            # 4. Module Preamble
            self.assertEqual(f_lines[9], "module purge")
            f_module_lines = f_lines[10:37]
            self.assertEqual(len(f_module_lines), 27)

            # 5. Worker execution tail
            f_expected_tail = (
                f"exec {shlex.quote(self.m_worker_path)} allocation "
                f"{shlex.quote(self.m_manifest_path)} {shlex.quote(f'0-tasks-{f_tasks}')}"
            )
            self.assertEqual(f_lines[37], f_expected_tail)

    def testRejectsSlurmRawAndInjectedMailModes(self) -> None:
        """Asserts rejection of SlurmMailMode.END_FAIL, raw strings, injected values, and invalid types."""
        f_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)

        # 1. SlurmMailMode rejected on PBS renderer
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_mail_mode=SlurmMailMode.END_FAIL,
            )

        # 2. Raw strings rejected
        f_raw_strings = [
            "abe",
            "ABE",
            "END,FAIL",
            "ALL",
            "NONE",
            "FAIL",
            "a",
            "b",
            "e",
            "",
            "   ",
        ]
        for f_raw in f_raw_strings:
            with self.assertRaises(SchedulerScriptError, msg=f"Raw mail string {f_raw!r} should be rejected"):
                PbsScriptRenderer.renderDirectives(
                    f_point=f_point,
                    f_profile=self.m_isambard_profile,
                    f_job_name=self.m_job_name,
                    f_output_path=self.m_output_path,
                    f_error_path=self.m_error_path,
                    f_mail_mode=f_raw,
                )

        # 3. Injected mail strings rejected
        f_injected_strings = [
            "abe\n#PBS -l select=99",
            "abe\r\n#PBS -l select=99",
            "abe\0#PBS",
            "abe; rm -rf /",
        ]
        for f_inj in f_injected_strings:
            with self.assertRaises(SchedulerScriptError, msg=f"Injected string {f_inj!r} should be rejected"):
                PbsScriptRenderer.renderDirectives(
                    f_point=f_point,
                    f_profile=self.m_isambard_profile,
                    f_job_name=self.m_job_name,
                    f_output_path=self.m_output_path,
                    f_error_path=self.m_error_path,
                    f_mail_mode=f_inj,
                )

        # 4. None or invalid types rejected
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_mail_mode=None,
            )

        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
                f_mail_mode=123,
            )

    def testSelectUsesNodesAndPpn(self) -> None:
        """Asserts calculation of nodes = tasks // ppn and select string formatting."""
        # Valid small scale: tasks=8, ppn=1 -> nodes=8
        f_small_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)
        f_small_dirs = PbsScriptRenderer.renderDirectives(
            f_point=f_small_point,
            f_profile=self.m_isambard_profile,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_mail_mode=PbsMailMode.ABE,
        )
        self.assertIn("#PBS -l select=8:ncpus=1:mpiprocs=1:mem=32GB", f_small_dirs)

        # Valid large scale: tasks=128, ppn=4 -> nodes=32
        f_large_point = ScalePoint(f_tasks=128, f_ppn=4, f_nodes=32)
        f_large_dirs = PbsScriptRenderer.renderDirectives(
            f_point=f_large_point,
            f_profile=self.m_isambard_profile,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_mail_mode=PbsMailMode.ABE,
        )
        self.assertIn("#PBS -l select=32:ncpus=4:mpiprocs=4:mem=32GB", f_large_dirs)

        # Mismatched tasks != nodes * ppn
        class MockPointMismatch:
            tasks = 8
            ppn = 1
            nodes = 4

        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=MockPointMismatch(),
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

        # Invalid ppn not in (1, 4)
        class MockPointBadPpn:
            tasks = 8
            ppn = 2
            nodes = 4

        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=MockPointBadPpn(),
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

        # Non-positive tasks or nodes
        class MockPointZeroTasks:
            tasks = 0
            ppn = 1
            nodes = 0

        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=MockPointZeroTasks(),
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

    def testMemPerCorrectedChunkAndSmallPmemPvmem(self) -> None:
        """Asserts mem=32GB per select chunk, and presence of pmem/pvmem only on small scale."""
        # Small scale: ppn=1
        f_small_point = ScalePoint(f_tasks=16, f_ppn=1, f_nodes=16)
        f_small_dirs = PbsScriptRenderer.renderDirectives(
            f_point=f_small_point,
            f_profile=self.m_isambard_profile,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
        )
        self.assertIn("#PBS -l select=16:ncpus=1:mpiprocs=1:mem=32GB", f_small_dirs)
        self.assertIn("#PBS -l pmem=8G", f_small_dirs)
        self.assertIn("#PBS -l pvmem=8G", f_small_dirs)

        # Large scale: ppn=4
        f_large_point = ScalePoint(f_tasks=16, f_ppn=4, f_nodes=4)
        f_large_dirs = PbsScriptRenderer.renderDirectives(
            f_point=f_large_point,
            f_profile=self.m_isambard_profile,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
        )
        self.assertIn("#PBS -l select=4:ncpus=4:mpiprocs=4:mem=32GB", f_large_dirs)
        self.assertFalse(any("pmem" in f_d for f_d in f_large_dirs))
        self.assertFalse(any("pvmem" in f_d for f_d in f_large_dirs))

    def testFixedSixHours(self) -> None:
        """Asserts walltime is always fixed 06:00:00 regardless of node count, and variable walltimes are rejected."""
        # Tested on various node counts
        for f_tasks in [1, 2, 4, 8, 16, 32, 64, 128, 256]:
            f_ppn = 1 if f_tasks <= 48 else 4
            f_nodes = f_tasks // f_ppn
            f_point = ScalePoint(f_tasks=f_tasks, f_ppn=f_ppn, f_nodes=f_nodes)

            f_dirs = PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )
            self.assertIn("#PBS -l walltime=06:00:00", f_dirs)

        # Passing explicit 06:00:00 is accepted
        f_point_1 = ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1)
        f_dirs_exact = PbsScriptRenderer.renderDirectives(
            f_point=f_point_1,
            f_profile=self.m_isambard_profile,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_walltime="06:00:00",
        )
        self.assertIn("#PBS -l walltime=06:00:00", f_dirs_exact)

        # Passing variable or non-06:00:00 walltime must raise SchedulerScriptError
        f_bad_walltimes = [
            "02:00:00",
            "04:00:00",
            "12:00:00",
            "00:30:00",
            "06:00",
            "6:00:00",
            "06:00:01",
        ]
        for f_bad_wt in f_bad_walltimes:
            with self.assertRaises(SchedulerScriptError, msg=f"Should reject variable walltime: {f_bad_wt!r}"):
                PbsScriptRenderer.renderDirectives(
                    f_point=f_point_1,
                    f_profile=self.m_isambard_profile,
                    f_job_name=self.m_job_name,
                    f_output_path=self.m_output_path,
                    f_error_path=self.m_error_path,
                    f_walltime=f_bad_wt,
                )

    def testNoSbatchOrSlurmCredential(self) -> None:
        """Asserts absence of #SBATCH directives, account, or Slurm credentials anywhere in the rendered PBS script."""
        f_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)

        # Create JobSpec with account and mail_user credentials
        f_spec = JobSpec(
            f_point_id="0-tasks-8",
            f_script_path="/tmp/job.sh",
            f_working_dir="/tmp/work",
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_account="my_slurm_account",
            f_mail_user="user@slurm.example.com",
            f_mail_mode=PbsMailMode.ABE,
        )

        f_script = PbsScriptRenderer.renderJobScript(
            f_point=f_point,
            f_profile=self.m_isambard_profile,
            f_spec=f_spec,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
        )

        # Strictly assert NO Slurm directives or credentials exist in rendered script
        self.assertNotIn("#SBATCH", f_script)
        self.assertNotIn("sbatch", f_script.lower())
        self.assertNotIn("my_slurm_account", f_script)
        self.assertNotIn("user@slurm.example.com", f_script)
        self.assertNotIn("--account", f_script)
        self.assertNotIn("--mail-user", f_script)
        self.assertNotIn("--mail-type", f_script)
        self.assertNotIn("END,FAIL", f_script)

    def testConfiguredLabel(self) -> None:
        """Asserts Isambard profile certification label matches configured state."""
        self.assertEqual(
            self.m_isambard_profile.certification,
            CertificationState.CONFIGURED,
        )
        self.assertEqual(
            self.m_isambard_profile.certification.value,
            "configured",
        )
        # Profile document has configured for ISAMBARD
        f_isambard_rec = self.m_profile_doc.profiles["ISAMBARD"]
        self.assertEqual(f_isambard_rec.certification, "configured")
        self.assertFalse(f_isambard_rec.test_only)

    def testDirectiveAdversaries(self) -> None:
        """Tests prevention of directive injection in job name, output path, and error path."""
        f_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)

        # 1. Newline injection in job name
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name="lm-012345\n#PBS -l select=99",
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

        # 2. Carriage return injection in job name
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name="lm-012345\r#PBS -l select=99",
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

        # 3. NUL byte injection in job name
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name="lm-012345\0#PBS",
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

        # 4. Directive injection pattern in job name
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name="lm-012345#PBS-injected",
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name="lm-012345#SBATCH-injected",
                f_output_path=self.m_output_path,
                f_error_path=self.m_error_path,
            )

        # 5. Newline injection in output/error paths
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path="/tmp/out\n#PBS -l select=99",
                f_error_path=self.m_error_path,
            )

        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path=self.m_output_path,
                f_error_path="/tmp/err\n#SBATCH --account=hack",
            )

        # 6. Non-absolute output/error paths
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path="relative/out.log",
                f_error_path=self.m_error_path,
            )

        # 7. Disallowed characters in paths (spaces, shell metacharacters)
        with self.assertRaises(SchedulerScriptError):
            PbsScriptRenderer.renderDirectives(
                f_point=f_point,
                f_profile=self.m_isambard_profile,
                f_job_name=self.m_job_name,
                f_output_path="/tmp/out $(rm -rf /)",
                f_error_path=self.m_error_path,
            )

    def testRenderJobScriptWithJobSpec(self) -> None:
        """Verifies rendering PBS script via renderJobScript using JobSpec."""
        f_point = ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4)
        f_spec = JobSpec(
            f_point_id="0-tasks-4",
            f_script_path="/tmp/job.sh",
            f_working_dir="/tmp/work",
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_mail_mode=PbsMailMode.ABE,
        )

        f_script = PbsScriptRenderer.renderJobScript(
            f_point=f_point,
            f_profile=self.m_isambard_profile,
            f_spec=f_spec,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
        )
        self.assertIn("#PBS -q arm", f_script)
        self.assertIn("#PBS -m abe", f_script)
        self.assertIn(f"#PBS -N {self.m_job_name}", f_script)
        self.assertIn("#PBS -l select=4:ncpus=1:mpiprocs=1:mem=32GB", f_script)
        self.assertIn("#PBS -l pmem=8G", f_script)
        self.assertIn("#PBS -l pvmem=8G", f_script)
        self.assertIn("#PBS -l walltime=06:00:00", f_script)
        self.assertIn(f"#PBS -o {self.m_output_path}", f_script)
        self.assertIn(f"#PBS -e {self.m_error_path}", f_script)
        self.assertIn("set -euo pipefail", f_script)
        self.assertIn("module purge", f_script)
        self.assertIn(f"exec {shlex.quote(self.m_worker_path)} allocation", f_script)

    def testRenderScriptWithValidatedWorker(self) -> None:
        """Verifies that an injected worker validator is invoked during PBS script rendering."""
        f_point = ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8)
        f_validated_calls: List[str] = []

        class MockValidator:
            def validate(self, f_path: str) -> str:
                f_validated_calls.append(f_path)
                return "/validated" + f_path

        f_validator = MockValidator()

        f_script = PbsScriptRenderer.render(
            f_point=f_point,
            f_profile=self.m_isambard_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
            f_worker_validator=f_validator,
        )
        self.assertEqual(f_validated_calls, [self.m_worker_path])
        self.assertIn(f"exec /validated{self.m_worker_path} allocation", f_script)

    def testDevProfileEmptyModules(self) -> None:
        """Verifies rendering PBS script with DEV profile where module list is empty."""
        f_point = ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1)
        f_script = PbsScriptRenderer.render(
            f_point=f_point,
            f_profile=self.m_dev_profile,
            f_worker_executable=self.m_worker_path,
            f_manifest_path=self.m_manifest_path,
            f_job_name=self.m_job_name,
            f_output_path=self.m_output_path,
            f_error_path=self.m_error_path,
        )
        # Should not have module purge or module load
        self.assertNotIn("module purge", f_script)
        self.assertNotIn("module load", f_script)
        self.assertIn("set -euo pipefail", f_script)
        self.assertIn(f"exec {shlex.quote(self.m_worker_path)} allocation", f_script)

    def testMethodAliases(self) -> None:
        """Verifies camelCase and snake_case method aliases on PbsScriptRenderer."""
        self.assertEqual(
            PbsScriptRenderer.renderDirectives,
            PbsScriptRenderer.render_directives,
        )
        self.assertEqual(
            PbsScriptRenderer.renderJobScript,
            PbsScriptRenderer.render_job_script,
        )
