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

"""Tests bmtool's LSMIO setup check (BM_SETUP) and its variant resolver after the '-M'
setups and the duplicate variants were removed."""

import os
import subprocess
import unittest
from typing import Tuple

_BMTOOL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "bmtool")
)


class BmtoolSetupTest(unittest.TestCase):
    """bmtool checks BM_SETUP before any other argument and resolves variants like lsmiotool."""

    def _parseWithSetup(self, f_setup: str) -> subprocess.CompletedProcess:
        """Run 'bmtool parse lsmio backends small native --no-such-option' with BM_SETUP.

        The unknown option makes bmtool stop right after the argument checks, so a
        setup that passes never reaches the HPC environment or the archive.
        """
        f_env = os.environ.copy()
        f_env["BM_RELOCATED"] = "1"
        f_env["SB_EMAIL"] = "test@example.com"
        f_env["SB_ACCOUNT"] = "test"
        f_env["BM_SETUP"] = f_setup
        return subprocess.run(
            [
                "/bin/sh",
                os.path.join(_BMTOOL_DIR, "bmtool"),
                "parse",
                "lsmio",
                "backends",
                "small",
                "native",
                "--no-such-option",
            ],
            env=f_env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _resolveVariant(self, f_variant: str) -> Tuple[int, str]:
        """Source jobs/lsmio-variants.in.sh and run resolve_variant; (status, flags)."""
        f_script = (
            '. "$1"; resolve_variant "$2" >/dev/null 2>&1; '
            'f_rc=$?; echo "$f_rc|$BM_VARIANT_FLAGS"'
        )
        f_res = subprocess.run(
            [
                "/bin/sh",
                "-c",
                f_script,
                "sh",
                os.path.join(_BMTOOL_DIR, "jobs", "lsmio-variants.in.sh"),
                f_variant,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        f_rc, f_flags = f_res.stdout.strip().split("|", 1)
        return int(f_rc), f_flags

    def testRemovedSetupNamesAreRejected(self) -> None:
        for f_setup, f_shown in (
            ("NATIVE-M", "NATIVE-M"),
            ("rocksdb-m", "ROCKSDB-M"),
            ("BOGUS", "BOGUS"),
        ):
            with self.subTest(setup=f_setup):
                f_res = self._parseWithSetup(f_setup)
                self.assertEqual(f_res.returncode, 1)
                self.assertIn(
                    f"ERROR: Unknown LSMIO setup BM_SETUP=[{f_shown}]", f_res.stdout
                )

    def testSetupNamesAreCaseInsensitive(self) -> None:
        """A valid setup in any case passes the check and reaches the option parsing."""
        for f_setup in ("NATIVE", "native", "Rocksdb", "manager"):
            with self.subTest(setup=f_setup):
                f_res = self._parseWithSetup(f_setup)
                self.assertEqual(f_res.returncode, 1)
                self.assertNotIn("Unknown LSMIO setup", f_res.stdout)
                self.assertIn(
                    "ERROR: Unknown argument for parse cmd: [--no-such-option]",
                    f_res.stdout,
                )

    def testVariantResolution(self) -> None:
        # Supported variants, with and without a backend prefix
        self.assertEqual(self._resolveVariant("default"), (0, "--lsmio-no-autotune"))
        self.assertEqual(
            self._resolveVariant("native-btree"),
            (0, "--lsmio-no-autotune --lsmio-memtable btree"),
        )
        self.assertEqual(
            self._resolveVariant("version-main-abc123-no-pread"),
            (0, "--lsmio-no-autotune"),
        )
        # Removed '-M' prefixes, retired variants and versioned retired variants
        for f_variant in (
            "native-m-btree",
            "footer",
            "footer-btree",
            "manoff-pool-8",
            "version-main-abc123-footer",
            "version-main-abc123-pread",
        ):
            with self.subTest(variant=f_variant):
                self.assertEqual(self._resolveVariant(f_variant)[0], 1)


if __name__ == "__main__":
    unittest.main()
