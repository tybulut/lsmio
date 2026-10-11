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

"""Legacy env.py site detection and library prefix parity with bmtool vars.in.sh (H12)."""

import json
import os
import subprocess
import sys
import unittest
from typing import Any, Dict, List, Optional


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


if __name__ == "__main__":
    unittest.main()
