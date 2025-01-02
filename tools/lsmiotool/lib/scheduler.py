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
# 

import os, sys, signal, importlib
import json, subprocess, base64


from lsmiotool import settings
from lsmiotool.lib import env, log, debuggable, plot
from lsmiotool.lib import plot, data
from lsmiotool.lib.env import hpcvars


# BM_DIRNAME, BM_TYPE, JOB_RUNNING, SB_ACCOUNT, SB_EMAIL, USER, job_scrip
class Scheduler(debuggable.DebuggableObject):
  def __init__(self, *args, **kwargs):
    super(Scheduler, self).__init__()
    self.cmd_manager = "dummy"
    self.cmd_submit = "dummy"
    self.run_env = {}
    self.arg_one = ""


  def encode(self, f_input: dict):
    serialized_data = json.dumps(f_input)
    return base64.b64encode(serialized_data.encode()).decode()

  def dencode(self, f_input: str):
    decoded_data = base64.b64decode(str).decode()
    return json.loads(decoded_data)

  def run(self, f_concurrency: int, f_pernode: int, f_job_script: str):
    self.concurrency = f_concurrency
    self.pernode = f_pernode
    self.job_script = f_job_script
    self.nodes = self.concurrency /self.pernode 
    self.wallhour = 2 + (self.nodes / 3)
    self.run_env['BM_NUM_TASKS'] = self.concurrency
    self.arg_one = self.encode(self.run_env)
    self._runSubmit()

  def waitForCompletion(self):
    while True:
      output = self._runStatus()
      match = False
      while line in output:
        if output.match("JOBID"):
          continue
        match = True
        break
      if match == True:
        break
      sleep(8)

  def execute(self, f_cmd: str, f_args: dict):
    return subprocess.run([f_cmd] + f_args)


class SlurmScheduler(Scheduler):
  def __init__(self, *args, **kwargs):
    super(SlurmScheduler, self).__init__()
    self.cmd_manager = "squeue"
    self.cmd_submit = "sbatch"

  def _runSubmit(self, f_script: str):
    self.args_submit = [
      "--export=ALL",
      "--ntasks=" + self.concurrency,
      "--nodes=" + self.nodes,
      "--job-name=LSMIO-" + f_script + "-" + self.concurrency,
      "--time=" + self.wallhour + ":00:00",
      "--account='" + self.run_env['SB_ACCOUNT'] + "'",
      "--mail-user='" + self.run_env['SB_EMAIL'] + "'",
      f_script + ".sbatch",
      "hpc-internal",
      self.arg_one
    ]
    self.execute(self.cmd_submit, self.args_submit)

  def _runStatus(self):
    self.args_status = [
        "-u",
        hpcvars.USER,
        "--format=%.15i %.9P %.20j %.8u %.8T %.10M %.9l %.6D %R"
    ]
    return self.execute(self.cmd_manager, self.args_status)


class PbsScheduler(Scheduler):
  def __init__(self, *args, **kwargs):
    super(SlurmScheduler, self).__init__()
    self.cmd_manager = "qstat"
    self.cmd_submit = "qsub"

  def _runSubmit(self, f_script: str):
    os.chdir(LSMIOTOOL_ROOT_DIR)
    self._submitargs = [
      "-v", 
      "BM_SCRIPT,BM_DIRNAME,BM_CMD,BM_TYPE,BM_SCALE,BM_SSD,BM_NUM_TASKS,BM_NUM_CORES",
      "-l",
      "select=" + self.concurrency + ":mem=24GB",
      f_script + ".pbs",
      "hpc-internal",
      self.arg_one
    ]
    self.execute(self.cmd_submit, self.args_submit)

  def _runStatus(self):
    self.args_status = [
        "-u",
        hpcvars.USER
    ]
    return self.execute(self.cmd_manager, self.args_status)

  def jobLocal(self):
    for concurrency in [1]:
      pernode = 1
      self.run(concurrency, pernode, "job-small")
      self.waitForCompletion()

  def jobBake(self):
    for concurrency in [4]:
      pernode = 1
      self.run(concurrency, pernode, "job-small")
      self.waitForCompletion()

  def jobSmall(self):
    for concurrency in [1, 2, 4, 8, 16, 24, 32, 40, 48]:
      pernode = 1
      self.run(concurrency, pernode, "job-small")
      self.waitForCompletion()

  def jobLarge(self):
    for concurrency in [4, 8, 16, 32, 64, 128, 192, 256]:
      pernode = 4
      self.run(concurrency, pernode, "job-large")
      self.waitForCompletion()

