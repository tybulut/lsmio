#
# Copyright 2023 Serdar Bulut
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

import os
import shutil
import types
import unittest
from typing import Dict, Any, Optional, List, Union
from unittest.mock import MagicMock, Mock, patch

from lsmiotool.lib import jobs, env


class TestSetupJobEnvironmentAndDirs(unittest.TestCase):
    """Unit tests for setup_job_environment_and_dirs function."""
    @patch('lsmiotool.lib.dirs.get_dirs', return_value={'foo': 'bar'})
    @patch('lsmiotool.lib.dirs.setup_data_dirs')
    def test_setup_job_environment_and_dirs(
        self,
        mock_setup: Mock,
        mock_get: Mock
    ) -> None:
        result = jobs.setup_job_environment_and_dirs('dummy_path')
        mock_setup.assert_called_once_with('dummy_path')
        mock_get.assert_called_once_with('dummy_path')
        self.assertEqual(result, {'foo': 'bar'})


class TestBatchJobOrchestration(unittest.TestCase):
    """Unit tests for batch_job_orchestration function."""
    @patch('lsmiotool.lib.jobs.setup_job_environment_and_dirs', return_value={})
    @patch('shutil.copytree')
    @patch('shutil.rmtree')
    @patch('os.path.isdir', return_value=True)
    @patch('subprocess.run')
    @patch('time.sleep')
    def test_batch_job_orchestration_slurm(
        self,
        mock_sleep: Mock,
        mock_run: Mock,
        mock_isdir: Mock,
        mock_rmtree: Mock,
        mock_copytree: Mock,
        mock_setup: Mock
    ) -> None:
        jobs.batch_job_orchestration('lmp', '/tmp', env.HpcManager.SLURM, 'ds')
        mock_run.assert_called()
        self.assertTrue(mock_copytree.called)
        self.assertTrue(mock_rmtree.called)
        self.assertTrue(mock_isdir.called)
        self.assertTrue(mock_sleep.called)

    @patch('lsmiotool.lib.jobs.setup_job_environment_and_dirs', return_value={})
    @patch('subprocess.run')
    @patch('time.sleep')
    def test_batch_job_orchestration_pbs(
        self,
        mock_sleep: Mock,
        mock_run: Mock,
        mock_setup: Mock
    ) -> None:
        jobs.batch_job_orchestration('ior', '/tmp', env.HpcManager.PBS, 'ds')
        mock_run.assert_called()
        self.assertTrue(mock_sleep.called)

    def test_batch_job_orchestration_unknown_manager(self) -> None:
        with self.assertRaises(RuntimeError):
            jobs.batch_job_orchestration('ior', '/tmp', 'unknown', 'ds')


class TestJobScriptGenerator(unittest.TestCase):
    """Unit tests for JobScriptGenerator static methods."""
    def test_generate_pbs_script(self) -> None:
        script = jobs.JobScriptGenerator.generate_pbs_script(
            queue='q',
            name='n',
            walltime='1:00:00',
            output_dir='od',
            batch_in_sh='bi'
        )
        self.assertIn('#PBS -q q', script)
        self.assertIn('#PBS -N n', script)
        self.assertIn('walltime=1:00:00', script)
        self.assertIn('od/', script)
        self.assertIn('. bi', script)

    def test_generate_sbatch_script(self) -> None:
        script = jobs.JobScriptGenerator.generate_sbatch_script(
            mail_type='FAIL',
            mem='2gb',
            ntasks_per_node=2,
            ntasks_per_socket=1,
            ntasks_per_core=1,
            distribution='block',
            output='out',
            error='err',
            batch_in_sh='bi'
        )
        self.assertIn('--mail-type=FAIL', script)
        self.assertIn('--mem=2gb', script)
        self.assertIn('--ntasks-per-node=2', script)
        self.assertIn('--distribution=block', script)
        self.assertIn('--output=out', script)
        self.assertIn('--error=err', script)
        self.assertIn('. bi', script)


class TestIORBenchmark(unittest.TestCase):
    """Unit tests for IORBenchmark class."""
    @patch('subprocess.run')
    @patch('builtins.open', create=True)
    def test_run(
        self,
        mock_open: Mock,
        mock_run: Mock
    ) -> None:
        bench = jobs.IORBenchmark(
            bm_setup='BASE',
            sb_bin='/bin',
            dirs_bm_base='/base',
            ior_dir_output='/out'
        )
        mock_open.return_value.__enter__.return_value = MagicMock()
        mock_run.return_value = MagicMock()
        result = bench.run('16', '64K')
        self.assertTrue(mock_run.called)
        self.assertTrue(mock_open.called)
        self.assertEqual(result, mock_run.return_value)


class TestLMPBenchmark(unittest.TestCase):
    """Unit tests for LMPBenchmark class."""
    @patch('subprocess.run')
    @patch('builtins.open', create=True)
    @patch('os.makedirs')
    def test_run(
        self,
        mock_makedirs: Mock,
        mock_open: Mock,
        mock_run: Mock
    ) -> None:
        bench = jobs.LMPBenchmark(
            bm_setup='LSMIO',
            sb_bin='/bin',
            dirs_bm_base='/base',
            lmp_dir_output='/out',
            bm_num_tasks=1
        )
        mock_open.return_value.__enter__.return_value = MagicMock()
        mock_run.return_value = MagicMock()
        result = bench.run('16', '64K')
        self.assertTrue(mock_run.called)
        self.assertTrue(mock_open.called)
        self.assertTrue(mock_makedirs.called)
        self.assertEqual(result, mock_run.return_value)


class TestLSMIOBenchmark(unittest.TestCase):
    """Unit tests for LSMIOBenchmark class."""
    @patch('subprocess.run')
    @patch('builtins.open', create=True)
    def test_run(
        self,
        mock_open: Mock,
        mock_run: Mock
    ) -> None:
        bench = jobs.LSMIOBenchmark(
            bm_setup='ADIOS-M',
            sb_bin='/bin',
            dirs_bm_base='/base',
            lsm_dir_output='/out'
        )
        mock_open.return_value.__enter__.return_value = MagicMock()
        mock_run.return_value = MagicMock()
        result = bench.run('16', '64K')
        self.assertTrue(mock_run.called)
        self.assertTrue(mock_open.called)
        self.assertEqual(result, mock_run.return_value)


class TestJobsRunner(unittest.TestCase):
    """Unit tests for JobsRunner class methods."""
    def setUp(self) -> None:
        pass

    @patch('subprocess.run')
    def test_run_slurm(self, mock_run: Mock) -> None:
        runner = jobs.JobsRunner(env.HpcManager.SLURM)
        runner.run(
            4,
            2,
            jobs.JobSize.SMALL,
            'testacct',
            'me@example.com',
            None,
            'ior',
            None
        )
        args = mock_run.call_args[0][0]
        self.assertIn('sbatch', args)
        self.assertIn('--account=testacct', args)
        self.assertIn('--mail-user=me@example.com', args)
        self.assertIn('--ntasks=4', args)
        self.assertIn('--nodes=2', args)

    @patch('subprocess.run')
    def test_run_pbs(self, mock_run: Mock) -> None:
        runner = jobs.JobsRunner(env.HpcManager.PBS)
        with patch('os.chdir') as mock_chdir:
            runner.run(
                8,
                4,
                jobs.JobSize.SMALL,
                None,
                None,
                'dir',
                'ior',
                None
            )
            args = mock_run.call_args[0][0]
            self.assertIn('qsub', args)
            self.assertIn('-v', args)
            self.assertIn(
                'BM_SCRIPT,BM_DIRNAME,BM_CMD,BM_TYPE,BM_SCALE,BM_SSD,'
                'BM_NUM_TASKS,BM_NUM_CORES',
                args
            )
            self.assertIn('-l select=8:mem=32GB', args)
            self.assertIn('SMALL.pbs', args)

    @patch('subprocess.run')
    @patch('getpass.getuser', return_value='testuser')
    @patch('time.sleep')
    def test_wait_for_completion_slurm(
        self,
        mock_sleep: Mock,
        mock_user: Mock,
        mock_run: Mock
    ) -> None:
        mock_run.side_effect = [
            MagicMock(stdout='JOBID\n1234\n'),
            MagicMock(stdout='JOBID\n')
        ]
        runner = jobs.JobsRunner(env.HpcManager.SLURM)
        runner.wait_for_completion()
        self.assertEqual(mock_run.call_count, 2)
        args1 = mock_run.call_args_list[0][0][0]
        self.assertIn('squeue', args1)
        self.assertTrue(mock_sleep.called)

    @patch('subprocess.run')
    @patch('getpass.getuser', return_value='testuser')
    @patch('time.sleep')
    def test_wait_for_completion_pbs(
        self,
        mock_sleep: Mock,
        mock_user: Mock,
        mock_run: Mock
    ) -> None:
        mock_run.side_effect = [
            MagicMock(stdout='JOBID\n5678\n'),
            MagicMock(stdout='JOBID\n')
        ]
        runner = jobs.JobsRunner(env.HpcManager.PBS)
        runner.wait_for_completion()
        self.assertEqual(mock_run.call_count, 2)
        args1 = mock_run.call_args_list[0][0][0]
        self.assertIn('qstat', args1)
        self.assertTrue(mock_sleep.called)

    @patch.object(jobs.JobsRunner, 'run')
    @patch.object(jobs.JobsRunner, 'wait_for_completion')
    def test_run_bake(
        self,
        mock_wait: Mock,
        mock_run: Mock
    ) -> None:
        runner = jobs.JobsRunner(env.HpcManager.PBS)
        runner.run_bake()
        mock_run.assert_called_with(
            4,
            1,
            jobs.JobSize.SMALL
        )
        mock_wait.assert_called()

    @patch.object(jobs.JobsRunner, 'run')
    @patch.object(jobs.JobsRunner, 'wait_for_completion')
    def test_run_small(
        self,
        mock_wait: Mock,
        mock_run: Mock
    ) -> None:
        runner = jobs.JobsRunner(env.HpcManager.SLURM)
        runner.run_small()
        self.assertEqual(mock_run.call_count, 9)
        self.assertEqual(mock_wait.call_count, 9)
        mock_run.assert_any_call(
            1,
            1,
            jobs.JobSize.SMALL
        )
        mock_run.assert_any_call(
            48,
            1,
            jobs.JobSize.SMALL
        )

    @patch.object(jobs.JobsRunner, 'run')
    @patch.object(jobs.JobsRunner, 'wait_for_completion')
    def test_run_large(
        self,
        mock_wait: Mock,
        mock_run: Mock
    ) -> None:
        runner = jobs.JobsRunner(env.HpcManager.PBS)
        runner.run_large()
        self.assertEqual(mock_run.call_count, 8)
        self.assertEqual(mock_wait.call_count, 8)
        mock_run.assert_any_call(
            4,
            4,
            jobs.JobSize.LARGE
        )
        mock_run.assert_any_call(
            256,
            4,
            jobs.JobSize.LARGE
        )

