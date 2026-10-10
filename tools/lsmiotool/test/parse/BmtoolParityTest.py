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

"""Parity of lsmiotool's LSMIO reports with bmtool parse/lsmio-parse.sh (ISSUES H1, H7, H8)."""

import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import patch

from lsmiotool.lib import data, output
from lsmiotool.lib.cli import parseParseArguments
from lsmiotool.lib.main import CompareVariantsMain, ParseMain
from lsmiotool.lib.runparse import (
    ArchivedArtifactLayout,
    RunRootResolver,
    extractRun,
    generateReports,
)

BMTOOL_PARSE_SCRIPT = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "bmtool", "parse", "lsmio-parse.sh"
    )
)
BMTOOL_PARSE_DIR = os.path.dirname(BMTOOL_PARSE_SCRIPT)
EXAMPLE_IOR_OUTPUTS = os.path.join(os.path.dirname(__file__), "example", "ior-outputs")


# bmtool's #!/bin/sh is bash on its sites (Viking, ARCHER2). Its globs then sort by the
# locale's collation, which lsmiotool reproduces; dash (Ubuntu's sh) sorts by bytes.
BMTOOL_SHELL = "bash"


def requireBmtoolShell(f_case: unittest.TestCase, f_script: str) -> None:
    """Skip f_case unless bmtool's script and its tools / en_US.UTF-8 collation exist."""
    for f_tool in (BMTOOL_SHELL, "grep", "egrep", "awk", "sed", "perl", "tail"):
        if shutil.which(f_tool) is None:
            f_case.skipTest(f"'{f_tool}' not available")
    if not os.path.isfile(f_script):
        f_case.skipTest(f"bmtool script not available: {f_script}")
    try:
        f_locales = subprocess.run(
            ["locale", "-a"], capture_output=True, text=True, check=False
        ).stdout.lower()
    except OSError:
        f_case.skipTest("locale not available")
    if "en_us.utf8" not in f_locales and "en_us.utf-8" not in f_locales:
        f_case.skipTest("en_US.UTF-8 locale (bmtool's collation) not available")


def hasGlibcGlobCollation() -> bool:
    """Return True if the host shell glob under en_US.UTF-8 uses glibc collation (ignores punctuation)."""
    with tempfile.TemporaryDirectory(prefix="lsmiotool-glob-check-") as f_td:
        os.makedirs(os.path.join(f_td, "1"), exist_ok=True)
        os.makedirs(os.path.join(f_td, "16"), exist_ok=True)
        open(os.path.join(f_td, "1", "a"), "w").close()
        open(os.path.join(f_td, "16", "a"), "w").close()
        f_cmd = 'LC_ALL=en_US.UTF-8; for f in */a; do echo "$f"; break; done'
        try:
            f_proc = subprocess.run(
                [BMTOOL_SHELL, "-c", f_cmd],
                cwd=f_td,
                capture_output=True,
                text=True,
                check=False,
            )
            return f_proc.stdout.strip().startswith("16")
        except OSError:
            return False


def lmpLog(f_bws: List[float], f_extra: Optional[List[str]] = None) -> str:
    """A constructed LSMIO-enabled LAMMPS (in.reaxc.hns) log, one rank's run_tee output.

    No real LMP output exists locally: the LAMMPS part follows LAMMPS' log format for
    bmtool's input (thermo every 10 of 100 steps, 'restart 10'), the LSMIO part the
    lsmio::Benchmark formatIterations/formatSummary output ('iwrite,<MiB/s>,...' per
    restart write, then 'write,<max>,<min>,<mean>,...'), which is what lmp-parse.sh's
    "grep '^.write,'" selects.
    """
    f_lines = [
        "LAMMPS (29 Oct 2020)",
        "  using 1 OpenMP thread(s) per MPI task",
        "Reading data file ...",
        "  triclinic box = (0.0000000 0.0000000 0.0000000) to (13.759000 14.734000 "
        "10.528000) with tilt (0.0000000 -5.4260000 0.0000000)",
        "  1 by 1 by 1 MPI processor grid",
        "  reading atoms ...",
        "  304 atoms",
        "  read_data CPU = 0.002 seconds",
        "Replicating atoms ...",
        "  19456 atoms",
        "  replicate CPU = 0.004 seconds",
        "Setting up Verlet run ...",
        "  Unit style    : real",
        "  Current step  : 0",
        "  Time step     : 0.1",
        "Per MPI rank memory allocation (min/avg/max) = 1031 | 1031 | 1031 Mbytes",
        "Step Temp PotEng Press E_vdwl E_coul Volume ",
    ]
    for f_step in range(0, 101, 10):
        f_lines.append(
            f"{f_step:8d}   {300 - f_step * 0.07:10.4f}   -113.27833    "
            f"{437.52 + f_step:10.4f}   -111.57687   -1.7014647    1731859.9 "
        )
    f_lines += [
        "Loop time of 812.345 on 4 procs for 100 steps with 19456 atoms",
        "",
        "Performance: 0.001 ns/day, 22565.139 hours/ns, 0.123 timesteps/s",
        "99.6% CPU use with 4 MPI tasks x 1 OpenMP threads",
        "",
        "BENCHMARK RESULTS: ",
        "",
        "Iteration-WRITE: LSMIO SYN: false BLF: false",
        "accessmax(MiB)/smin(MiB/s)mean(MiB/s)total(MiB)total(Ops)iteration",
    ]
    f_lines += [f"iwrite,{f_bw:.2f},{f_bw:.2f},{f_bw:.2f},18.25,1,1" for f_bw in f_bws]
    f_lines += [
        "",
        "Bench-WRITE: LSMIO SYN: false BLF: false",
        AGG_HEADER,
        "------,----------,----------,-----------,-----------,----------,----------",
        f"write,{max(f_bws):.2f},{min(f_bws):.2f},{sum(f_bws) / len(f_bws):.2f},"
        f"{18.25 * len(f_bws):.2f},{len(f_bws)},{len(f_bws)}",
        "",
    ]
    f_lines += f_extra or []
    f_lines.append("Total wall time: 0:13:40")
    return "\n".join(f_lines) + "\n"

AGG_HEADER = (
    "access,max(MiB)/s,min(MiB/s),mean(MiB/s),total(MiB),total(Ops),iteration"
)


def rankLog(
    f_write: Optional[str],
    f_read: Optional[str],
) -> str:
    """Render a bm_* rank log with the given 'write,...'/'read,...' summary lines."""
    f_lines = [
        "BENCHMARK RESULTS: ",
        "",
        "Iteration-WRITE: Native Flush: false BLF: false",
        "accessmax(MiB)/smin(MiB/s)mean(MiB/s)total(MiB)total(Ops)iteration",
        "iwrite,179.48,179.48,179.48,256.00,4096,1",
        "",
    ]
    if f_write is not None:
        f_lines += [
            "Bench-WRITE: Native Flush: false BLF: false",
            AGG_HEADER,
            "------,----------,----------,-----------,-----------,----------,----------",
            f_write,
            "",
        ]
    if f_read is not None:
        f_lines += [
            "Bench-READ: Native Flush: false BLF: false",
            AGG_HEADER,
            "------,----------,----------,-----------,-----------,----------,----------",
            f_read,
            "",
        ]
    return "\n".join(f_lines) + "\n"


def rankValues(f_rank: int, f_salt: int) -> Dict[str, str]:
    """Deterministic, non-trivial per-rank summary lines."""
    f_w = 400.0 + ((f_rank * 37 + f_salt * 11) % 211) + ((f_rank * 13) % 100) / 100.0
    f_r = 1900.0 + ((f_rank * 53 + f_salt * 7) % 307) + ((f_rank * 29) % 100) / 100.0
    return {
        "write": f"write,{f_w:.2f},{f_w - 341.73:.2f},{f_w - 76.68:.2f},2559.96,40960,10",
        "read": f"read,{f_r:.2f},{f_r - 173.08:.2f},{f_r - 72.77:.2f},2559.96,40960,10",
    }


def writeBmtoolLayout(
    f_root: str,
    f_nodes: List[str],
    f_infix: str = "native",
    f_date: str = "2026-10-07",
) -> None:
    """Create '<nodes>/<date>/out-<infix>-<rf>-<bs>-<date>-<host>-<localid>.txt' rank logs."""
    for f_n in f_nodes:
        for f_salt, (f_rf, f_bs) in enumerate(
            (f_rf, f_bs)
            for f_rf in data.BMTOOL_STRIPE_COUNTS
            for f_bs in data.BMTOOL_BLOCK_SIZES
        ):
            for f_rank in range(int(f_n)):
                f_vals = rankValues(f_rank, f_salt + int(f_n))
                f_path = os.path.join(
                    f_root,
                    f_n,
                    f_date,
                    f"out-{f_infix}-{f_rf}-{f_bs}-{f_date}-node{100 + f_rank:03d}-0.txt",
                )
                os.makedirs(os.path.dirname(f_path), exist_ok=True)
                with open(f_path, "w") as f_f:
                    f_f.write(rankLog(f_vals["write"], f_vals["read"]))


def readTree(f_root: str) -> Dict[str, bytes]:
    """Map relative path -> bytes for every report file under f_root."""
    f_out: Dict[str, bytes] = {}
    for f_dir, _f_subdirs, f_files in os.walk(f_root):
        for f_name in f_files:
            if f_name == data.LSM_REPORT_FILE or re.match(
                r"agg-.*-report\.csv$", f_name
            ):
                f_path = os.path.join(f_dir, f_name)
                with open(f_path, "rb") as f_f:
                    f_out[os.path.relpath(f_path, f_root)] = f_f.read()
    return f_out


class BmtoolPrimitivesTest(unittest.TestCase):
    """awk number formatting, glob collation and per-combination aggregation."""

    def testAwkNumberFormatting(self) -> None:
        self.assertEqual(data.formatAwkNumber(20479.68), "20479.7")
        self.assertEqual(data.formatAwkNumber(163838.4), "163838")
        self.assertEqual(data.formatAwkNumber(2621440.0), "2621440")
        self.assertEqual(data.formatAwkNumber(3634.912), "3634.91")
        self.assertEqual(data.formatAwkNumber(0.0), "0")
        self.assertEqual(data.formatAwkNumber(1234567.5), "1.23457e+06")
        self.assertEqual(data.awkToNumber(" 12.5x"), 12.5)
        self.assertEqual(data.awkToNumber("abc"), 0.0)
        self.assertTrue(data.awkIsStrNum(" 10\r"))
        self.assertFalse(data.awkIsStrNum("10x"))

    def testShellGlobCollationOrder(self) -> None:
        """bmtool's glob under en_US.UTF-8 puts '16/...' before '1/...' (punctuation ignored)."""
        f_paths = [
            "1/agg-4-1M-report.csv",
            "16/agg-16-1M-report.csv",
            "2/agg-16-8M-report.csv",
            "24/agg-4-64K-report.csv",
            "8/agg-16-64K-report.csv",
            "8/agg-16-1M-report.csv",
            "8/agg-4-1M-report.csv",
        ]
        self.assertEqual(
            sorted(f_paths, key=data.bmtoolCollationKey),
            [
                "16/agg-16-1M-report.csv",
                "1/agg-4-1M-report.csv",
                "24/agg-4-64K-report.csv",
                "2/agg-16-8M-report.csv",
                "8/agg-16-1M-report.csv",
                "8/agg-16-64K-report.csv",
                "8/agg-4-1M-report.csv",
            ],
        )

    def testAggregateSumsColumnsAndMaxIteration(self) -> None:
        """Columns 2-6 are summed across ranks; column 7 is the maximum (H1)."""
        f_agg = data.LsmioBmtoolAggregate()
        f_agg.addLines(
            rankLog(
                "write,521.21,179.48,444.53,2559.96,40960,10",
                "read,2089.25,1916.17,2016.48,2559.96,40960,10",
            ).split("\n")
        )
        f_agg.addLines(
            rankLog(
                "write,500.5,170.25,440.1,2559.96,40960,9",
                "read,2000.75,1900,2000,2559.96,40960,12",
            ).split("\n")
        )
        self.assertEqual(
            f_agg.aggLines(),
            [
                AGG_HEADER,
                "write,1021.71,349.73,884.63,5119.92,81920,10",
                "read,4090,3816.17,4016.48,5119.92,81920,12",
            ],
        )
        self.assertEqual(f_agg.fileCount, 2)

    def testAggregateWithoutSummaryLinesMatchesAwk(self) -> None:
        """A combination whose ranks never reached 'read,' prints awk's empty sums."""
        f_agg = data.LsmioBmtoolAggregate()
        f_agg.addLines(
            rankLog("write,10.5,1,2,3,4,10", None).split("\n")
        )
        self.assertEqual(f_agg.row("write"), "write,10.5,1,2,3,4,10")
        self.assertEqual(f_agg.row("read"), "read,,,,,,0")

    def testReportRowsTransform(self) -> None:
        """generate_report keeps the last two write/read lines, prefixed 'N,rf,bs,'."""
        self.assertEqual(
            data.bmtoolReportRows(
                "8/agg-16-1M-report.csv",
                [
                    AGG_HEADER,
                    "write,3634.91,2746.7,3376.47,20479.7,327680,10",
                    "read,18104.3,13845.5,15947.3,20479.7,327680,10",
                ],
            ),
            [
                "8,16,1M,write,3634.91,2746.7,3376.47,20479.7,327680,10",
                "8,16,1M,read,18104.3,13845.5,15947.3,20479.7,327680,10",
            ],
        )


def extractShellFunction(f_script: str, f_name: str) -> str:
    """Source text of shell function f_name() in f_script."""
    with open(f_script) as f_f:
        f_text = f_f.read()
    f_match = re.search(
        rf"^({re.escape(f_name)}\(\) \{{.*?^\}})", f_text, flags=re.M | re.S
    )
    if f_match is None:
        raise AssertionError(f"{f_name}() not found in {f_script}")
    return f_match.group(1)


def readFile(f_path: str) -> bytes:
    with open(f_path, "rb") as f_f:
        return f_f.read()


class IorLmpParityTest(unittest.TestCase):
    """ior-report.csv / lmp-report.csv match bmtool's ior-parse.sh / lmp-parse.sh (M14, M16)."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-iorlmp-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _iorOutputs(self, f_dir: str) -> str:
        """The example IOR outputs plus edge cases: a '-c-' setup infix, trailing
        blanks, an empty file, a hidden file and a 2-digit node directory."""
        shutil.copytree(EXAMPLE_IOR_OUTPUTS, f_dir)
        f_src = os.path.join(
            f_dir, "1", "2023-07-21", "out-collective-4-1M-2023-07-21-node169-0.txt.2"
        )
        with open(f_src) as f_f:
            f_text = f_f.read()
        f_day = os.path.join(f_dir, "16", "2023-07-22")
        os.makedirs(f_day)
        with open(
            os.path.join(f_day, "out-hdf5-c-16-8M-2023-07-22-nid001234-0.txt"), "w"
        ) as f_f:
            f_f.write(
                re.sub(r"(?m)^(write|read)( .*)$", r"\1\2   ", f_text)
            )
        open(os.path.join(f_day, "out-base-4-64K-2023-07-22-node001-0.txt"), "w").close()
        with open(os.path.join(f_day, ".out-base-4-1M-2023-07-22-node001-0.txt.rc"), "w") as f_f:
            f_f.write("write 1 2 3\n")
        return f_dir

    def testIorReportMatchesRealBmtoolScript(self) -> None:
        f_script = os.path.join(BMTOOL_PARSE_DIR, "ior-parse.sh")
        requireBmtoolShell(self, f_script)
        with open(f_script) as f_f:
            f_body = re.search(r"(?ms)^(REPORT_FILE=.*?^done)", f_f.read()).group(1)
        f_driver = os.path.join(self.m_temp_dir, "iorref.sh")
        with open(f_driver, "w") as f_f:
            f_f.write('IOR_DIR_OBASE="$1"\n' + f_body + "\n")

        f_bm = self._iorOutputs(os.path.join(self.m_temp_dir, "bm"))
        f_py = self._iorOutputs(os.path.join(self.m_temp_dir, "py"))
        subprocess.run(
            [BMTOOL_SHELL, f_driver, f_bm],
            env=dict(os.environ, LC_ALL="en_US.UTF-8"),
            check=True,
            capture_output=True,
        )
        output.IorAggOutput(f_py).generateReports()
        f_expected = readFile(os.path.join(f_bm, data.IOR_REPORT_FILE))
        self.assertEqual(readFile(os.path.join(f_py, data.IOR_REPORT_FILE)), f_expected)
        # Both StdDev columns survive (466.80 must not become the OPs StdDev)
        self.assertIn(
            b"1,16,64K,write,887.21,773.61,839.98,35.41,14195.36,12377.73,13439.62,566.57,",
            f_expected,
        )
        # bmtool quirks kept: its seds expect 5-character nid names (ARCHER2 has 6)
        # and trailing blanks become a trailing comma
        self.assertIn(b"16,16,8M-2023-07-22-nid001234-0.txt,write,", f_expected)
        self.assertIn(b",MPIIO,0,\n", f_expected)

    def testIorReportIntoOtherDirectory(self) -> None:
        f_src = self._iorOutputs(os.path.join(self.m_temp_dir, "src"))
        f_out = os.path.join(self.m_temp_dir, "out")
        output.IorAggOutput(f_src).generateReports(f_out)
        self.assertTrue(data.isUsableReport(os.path.join(f_out, data.IOR_REPORT_FILE)))
        self.assertFalse(os.path.exists(os.path.join(f_src, data.IOR_REPORT_FILE)))

    def testIorSingleRunDataKeepsBothStdDev(self) -> None:
        f_path = os.path.join(
            EXAMPLE_IOR_OUTPUTS, "1", "2023-07-21",
            "out-collective-16-64K-2023-07-21-node169-0.txt.2",
        )
        f_map = data.IorSingleRunData(f_path).getMap()
        self.assertEqual(f_map["write"]["StdDev"], 35.41)
        self.assertEqual(f_map["write"][data.IOR_OPS_STDDEV_KEY], 566.57)
        self.assertEqual(
            data.iorSummaryKeys(["a", "StdDev", "b", "StdDev", "a"]),
            ["a", "StdDev", "b", data.IOR_OPS_STDDEV_KEY, "a#2"],
        )

    def _lmpOutputs(self, f_dir: str) -> Dict[str, float]:
        """bmtool LMP layout <n>/<date>/out-lmp-lsmio-<rf>-<bs>-<date>-<host>-0.txt
        (one log per rank). Returns the expected throughput per 'n/rf/bs' (the last
        'iwrite' line of the last file in glob order)."""
        f_expected: Dict[str, float] = {}
        for f_n in ("1", "2", "4"):
            for f_salt, (f_rf, f_bs) in enumerate(
                (f_rf, f_bs)
                for f_rf in data.BMTOOL_STRIPE_COUNTS
                for f_bs in data.BMTOOL_BLOCK_SIZES
            ):
                if f_n == "4" and f_bs == "8M":
                    continue  # a missing combination is simply not reported
                for f_rank in range(int(f_n)):
                    f_bws = [
                        100.0 + 7 * f_i + 13 * f_rank + 3 * f_salt + int(f_n)
                        for f_i in range(10)
                    ]
                    f_extra = (
                        ["#write,1.5:colon-cut"]
                        if (f_n, f_rf, f_bs, f_rank) == ("2", "16", "8M", 1)
                        else None
                    )
                    f_path = os.path.join(
                        f_dir, f_n, "2026-10-07",
                        f"out-lmp-lsmio-{f_rf}-{f_bs}-2026-10-07-node{100 + f_rank:03d}-0.txt",
                    )
                    os.makedirs(os.path.dirname(f_path), exist_ok=True)
                    with open(f_path, "w") as f_f:
                        f_f.write(lmpLog(f_bws, f_extra))
                    f_expected[f"{f_n}/{f_rf}/{f_bs}"] = (
                        1.5 if f_extra else round(f_bws[-1], 2)
                    )
        return f_expected

    def testLmpReportMatchesRealBmtoolScript(self) -> None:
        """Verified against a constructed fixture only: no real LMP outputs exist."""
        f_script = os.path.join(BMTOOL_PARSE_DIR, "lmp-parse.sh")
        requireBmtoolShell(self, f_script)
        f_driver = os.path.join(self.m_temp_dir, "lmpref.sh")
        with open(f_driver, "w") as f_f:
            f_f.write(extractShellFunction(f_script, "generate_report"))
            f_f.write('\nLMP_DIR_OBASE="$1"\ngenerate_report\n')

        f_bm = os.path.join(self.m_temp_dir, "bm")
        f_py = os.path.join(self.m_temp_dir, "py")
        self._lmpOutputs(f_bm)
        f_expected = self._lmpOutputs(f_py)
        subprocess.run(
            [BMTOOL_SHELL, f_driver, f_bm],
            env=dict(os.environ, LC_ALL="en_US.UTF-8"),
            check=True,
            capture_output=True,
        )
        output.LmpAggOutput(f_py).generateReports()
        f_bm_report = readFile(os.path.join(f_bm, data.LMP_REPORT_FILE))
        self.assertEqual(readFile(os.path.join(f_py, data.LMP_REPORT_FILE)), f_bm_report)

        f_rows = f_bm_report.decode().splitlines()
        self.assertEqual(len(f_rows), 16)
        self.assertEqual(f_rows[0], "1,4,64K,iwrite,164.00,164.00,164.00,18.25,1,1")
        self.assertIn("2,16,8M,#write,1.5", f_rows)  # awk -F: cuts at the colon

        # ... and reads back as the throughput, not row[3] ('iwrite') as 0
        f_summary = data.LmpSummaryData(os.path.join(f_bm, data.LMP_REPORT_FILE))
        for f_rf in data.BMTOOL_STRIPE_COUNTS:
            for f_bs in data.BMTOOL_BLOCK_SIZES:
                f_x, f_y = f_summary.timeSeries(False, int(f_rf), f_bs)
                f_nodes = ["1", "2"] if f_bs == "8M" else ["1", "2", "4"]
                self.assertEqual(f_x, [int(f_n) for f_n in f_nodes])
                self.assertEqual(
                    f_y, [f_expected[f"{f_n}/{f_rf}/{f_bs}"] for f_n in f_nodes]
                )

    def testLmpSingleRunDataUsesLastResultLine(self) -> None:
        f_path = os.path.join(self.m_temp_dir, "out-lmp-lsmio-4-1M-x.txt")
        with open(f_path, "w") as f_f:
            f_f.write(lmpLog([300.0, 412.5]))
        f_run = data.LmpSingleRunData(f_path)
        self.assertEqual(f_run.getMap()["write"]["throughput"], 412.5)
        self.assertEqual(f_run.getIterData()["write"], [300.0, 412.5])
        self.assertEqual(f_run.bmtoolLine, "iwrite,412.50,412.50,412.50,18.25,1,1")
        self.assertEqual(data.lmpReportField("p:12:#write,1.5:x"), "#write,1.5")
        self.assertTrue(data.isLmpResultLine("iwrite,1"))
        self.assertFalse(data.isLmpResultLine("write,1"))

    def testLmpPartialOutputsDoNotRaise(self) -> None:
        """A node dir with fewer logs than nodes still reports (bmtool has no check)."""
        f_dir = os.path.join(self.m_temp_dir, "py")
        self._lmpOutputs(f_dir)
        f_day = os.path.join(f_dir, "4", "2026-10-07")
        for f_name in os.listdir(f_day):
            if "node103" in f_name:
                os.remove(os.path.join(f_day, f_name))
        f_agg = output.LmpAggOutput(f_dir)
        f_agg.generateReports()
        self.assertTrue(data.isUsableReport(os.path.join(f_dir, data.LMP_REPORT_FILE)))
        with self.assertRaises(output.MissingDataError):
            f_agg.getMap()



class LsmioAggOutputParityTest(unittest.TestCase):
    """LsmioAggOutput.generateReports reproduces bmtool byte for byte (H1)."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-bmparity-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def testKnownValuesAcrossRanks(self) -> None:
        """Sums, not rank 0's line, reach the agg files and lsm-report.csv."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["2"])
        output.LsmioAggOutput(f_root).generateReports(f_out_dir=f_root)

        f_r0 = rankValues(0, 0 + 2)["write"].split(",")
        f_r1 = rankValues(1, 0 + 2)["write"].split(",")
        f_expected = "write," + ",".join(
            [
                data.formatAwkNumber(float(f_r0[f_i]) + float(f_r1[f_i]))
                for f_i in range(1, 6)
            ]
            + ["10"]
        )
        self.assertNotEqual(f_expected, rankValues(0, 2)["write"])
        with open(os.path.join(f_root, "2", "agg-4-64K-report.csv")) as f_f:
            f_agg = f_f.read().split("\n")
        self.assertEqual(f_agg[0], AGG_HEADER)
        self.assertEqual(f_agg[1], f_expected)

        with open(os.path.join(f_root, data.LSM_REPORT_FILE)) as f_f:
            f_rows = f_f.read().splitlines()
        self.assertEqual(len(f_rows), 12)
        self.assertIn("2,4,64K," + f_expected, f_rows)
        self.assertTrue(all(len(f_row.split(",")) == 10 for f_row in f_rows))
        self.assertTrue(f_rows[0].startswith("2,16,1M,write,"))

    def testMatchesRealBmtoolScript(self) -> None:
        """Runs bmtool's own generate_aggregates/generate_report and diffs the bytes."""
        for f_tool in (BMTOOL_SHELL, "grep", "egrep", "awk", "sed", "perl", "tail"):
            if shutil.which(f_tool) is None:
                self.skipTest(f"'{f_tool}' not available")
        if not os.path.isfile(BMTOOL_PARSE_SCRIPT):
            self.skipTest("bmtool parse script not available")
        try:
            f_locales = subprocess.run(
                ["locale", "-a"], capture_output=True, text=True, check=False
            ).stdout.lower()
        except OSError:
            self.skipTest("locale not available")
        if "en_us.utf8" not in f_locales and "en_us.utf-8" not in f_locales:
            self.skipTest("en_US.UTF-8 locale (bmtool's collation) not available")
        if not hasGlibcGlobCollation():
            self.skipTest(
                "Host shell glob does not use glibc collation (bmtool's collation on Viking/ARCHER2)"
            )

        with open(BMTOOL_PARSE_SCRIPT) as f_f:
            f_script = f_f.read()
        f_funcs = re.findall(
            r"^(generate_(?:aggregates|report)\(\) \{.*?^\})",
            f_script,
            flags=re.M | re.S,
        )
        self.assertEqual(len(f_funcs), 2)
        f_driver = os.path.join(self.m_temp_dir, "bmref.sh")
        with open(f_driver, "w") as f_f:
            f_f.write("\n\n".join(f_funcs))
            f_f.write(
                '\nLSM_DIR_OBASE="$1"\ngenerate_aggregates "$2" >/dev/null\n'
                "generate_report >/dev/null\n"
            )

        for f_scale, f_nodes in (("small", ["1", "2", "4", "16"]), ("variants", ["8"])):
            f_bm_dir = os.path.join(self.m_temp_dir, f"bm-{f_scale}")
            f_py_dir = os.path.join(self.m_temp_dir, f"py-{f_scale}")
            writeBmtoolLayout(f_bm_dir, f_nodes)
            writeBmtoolLayout(f_py_dir, f_nodes)

            f_env = dict(os.environ, LC_ALL="en_US.UTF-8")
            subprocess.run(
                [BMTOOL_SHELL, f_driver, f_bm_dir, f_scale],
                env=f_env,
                check=True,
                capture_output=True,
            )
            with patch("lsmiotool.lib.log.Console.warning"):
                output.LsmioAggOutput(f_py_dir, f_scale=f_scale).generateReports(
                    f_out_dir=f_py_dir
                )

            f_bm_tree = readTree(f_bm_dir)
            self.assertIn(data.LSM_REPORT_FILE, f_bm_tree)
            self.assertEqual(readTree(f_py_dir), f_bm_tree, f"scale={f_scale}")

    def testMissingNodeDirAndCombinationAreSkippedWithWarning(self) -> None:
        """Missing node dirs / combos warn instead of raising, like bmtool."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["2"])
        for f_name in os.listdir(os.path.join(f_root, "2", "2026-10-07")):
            if "-16-8M-" in f_name:
                os.remove(os.path.join(f_root, "2", "2026-10-07", f_name))

        with patch("lsmiotool.lib.log.Console.warning") as f_warn:
            output.LsmioAggOutput(f_root, f_scale="bake").generateReports()
        f_msgs = [str(f_c[0][0]) for f_c in f_warn.call_args_list]
        self.assertTrue(any("skipping node 1" in f_m for f_m in f_msgs))
        self.assertTrue(any("16-8M" in f_m for f_m in f_msgs))
        self.assertFalse(
            os.path.exists(os.path.join(f_root, "2", "agg-16-8M-report.csv"))
        )
        with open(os.path.join(f_root, data.LSM_REPORT_FILE)) as f_f:
            self.assertEqual(len(f_f.read().splitlines()), 10)

    def testPartialRankFilesDoNotRaise(self) -> None:
        """A node dir holding fewer rank files than nodes still yields reports."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["8"])
        f_day = os.path.join(f_root, "8", "2026-10-07")
        for f_name in os.listdir(f_day):
            if "node107" in f_name:
                os.remove(os.path.join(f_day, f_name))

        f_agg = output.LsmioAggOutput(f_root, f_scale="variants")
        f_agg.generateReports(f_out_dir=f_root)
        self.assertTrue(data.isUsableReport(os.path.join(f_root, data.LSM_REPORT_FILE)))
        with self.assertRaises(output.MissingDataError):
            f_agg.getMap()

    def testNoRowsNeverWritesEmptyReport(self) -> None:
        """Regeneration without data writes no lsm-report.csv (H7)."""
        f_root = os.path.join(self.m_temp_dir, "outputs-empty")
        os.makedirs(f_root)
        with patch("lsmiotool.lib.log.Console.warning") as f_warn:
            output.LsmioAggOutput(f_root, f_scale="variants").generateReports()
        self.assertFalse(os.path.exists(os.path.join(f_root, data.LSM_REPORT_FILE)))
        self.assertTrue(
            any("not writing" in str(f_c[0][0]) for f_c in f_warn.call_args_list)
        )

    def testZeroByteReportCountsAsMissing(self) -> None:
        """ensureLsmioReports regenerates over a zero-byte lsm-report.csv (H7)."""
        f_root = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_root, ["1"])
        f_report = os.path.join(f_root, data.LSM_REPORT_FILE)
        open(f_report, "w").close()
        self.assertTrue(output.ensureLsmioReports(f_root))
        self.assertGreater(os.path.getsize(f_report), 0)


class RunParseParityTest(unittest.TestCase):
    """Manifest-layout runs (pristine and archived) report like bmtool (H1, H7)."""

    def setUp(self) -> None:
        from lsmiotool.test.parse.RunParseTest import RunParseTest

        self.m_helper = RunParseTest("testExplicitSucceededPaths")
        self.m_helper.setUp()
        self.m_temp_dir = self.m_helper.m_temp_dir

    def tearDown(self) -> None:
        self.m_helper.tearDown()

    def _writeRankLogs(self, f_run_root: str) -> None:
        f_resolved = RunRootResolver.resolve(f_run_root)
        for f_pt in f_resolved.points:
            for f_salt, f_combo in enumerate(f_resolved.plan.combinations):
                f_dir = os.path.join(f_pt.pointDir, "logs", f_combo.name)
                os.makedirs(f_dir, exist_ok=True)
                for f_rank in range(f_pt.scalePoint.tasks):
                    f_vals = rankValues(f_rank, f_salt)
                    with open(os.path.join(f_dir, f"rank_{f_rank}.log"), "w") as f_f:
                        f_f.write(rankLog(f_vals["write"], f_vals["read"]))

    def _bmtoolEquivalent(self, f_run_root: str, f_dest: str) -> None:
        """Lay the run's rank logs out like bmtool and aggregate them with LsmioAggOutput."""
        f_resolved = RunRootResolver.resolve(f_run_root)
        for f_pt in f_resolved.points:
            for f_combo in f_resolved.plan.combinations:
                for f_rank in range(f_pt.scalePoint.tasks):
                    f_src = os.path.join(
                        f_pt.pointDir, "logs", f_combo.name, f"rank_{f_rank}.log"
                    )
                    f_dst = os.path.join(
                        f_dest,
                        str(f_pt.scalePoint.nodes),
                        "2026-10-07",
                        f"out-native-{f_combo.stripe_count}-{f_combo.block_size}"
                        f"-2026-10-07-node{100 + f_rank:03d}-0.txt",
                    )
                    os.makedirs(os.path.dirname(f_dst), exist_ok=True)
                    shutil.copyfile(f_src, f_dst)
        output.LsmioAggOutput(f_dest).generateReports(f_out_dir=f_dest)

    def testArchivedRunRootParsesLikeBmtool(self) -> None:
        """A run root moved to '<dest>/outputs-<arm>:run' resolves and sums ranks."""
        f_run_root, _f_plan, _ = self.m_helper._setupSucceededRun(
            "run-archived-001", "lsmio", "bake"
        )
        self._writeRankLogs(f_run_root)
        f_archived = os.path.join(
            self.m_temp_dir, "lsmio-archive", "variants", "outputs-native-legacy:run"
        )
        os.makedirs(os.path.dirname(f_archived))
        shutil.move(f_run_root, f_archived)
        os.makedirs(f_run_root)  # executeArchive leaves the emptied source behind

        f_resolved = RunRootResolver.resolve(f_archived)
        self.assertEqual(f_resolved.runRoot, f_archived)
        self.assertEqual(f_resolved.runId, "run-archived-001")
        self.assertTrue(
            all(f_pt.pointDir.startswith(f_archived) for f_pt in f_resolved.points)
        )

        f_out = os.path.join(self.m_temp_dir, "reports")
        f_files = generateReports(f_resolved, extractRun(f_resolved), f_out)
        self.assertIn("lsm-report.csv", f_files)

        f_bm = os.path.join(self.m_temp_dir, "bm-equivalent")
        self._bmtoolEquivalent(f_archived, f_bm)
        self.assertEqual(readTree(f_out), readTree(f_bm))

    def _setupPartialRun(self, f_run_id: str) -> Tuple[str, Set[Tuple[int, str]]]:
        """An lsmio 'bake' run (points of 1, 2, 4, 8 tasks) that failed at point 1.

        Point 0 succeeded. Point 1 ran combinations 0-3 cleanly, rank 1 of
        combination 4 failed and combination 5 never ran (rank logs exist for all
        six); its job ended FAILED. Points 2 and 3 never ran. Returns the run root and
        the (point ordinal, combination) pairs with complete output.
        """
        from lsmiotool.lib.artifacts import ArtifactStore
        from lsmiotool.lib.evidence import EvidenceKind, EvidenceStore, JobHandle

        f_plan = self.m_helper._createPlan(f_run_id, "lsmio", "bake")
        f_store = ArtifactStore(self.m_temp_dir, f_run_id)
        f_store.allocateRun(f_plan)
        f_ev = EvidenceStore(f_store.layout, f_plan=f_plan)
        f_complete: Set[Tuple[int, str]] = set()

        for f_idx in (0, 1):
            f_sp = f_plan.scale_points[f_idx]
            f_store.preparePoint(f_sp, f_ordinal=f_idx)
            f_handle = JobHandle("slurm", f"77{f_idx}")
            f_ev.recordSubmissionRequested(f_sp, "client", f_ordinal=f_idx)
            f_ev.recordSubmissionDispatched(f_sp, "client", f_ordinal=f_idx)
            f_ev.recordSubmissionRecorded(
                f_sp, "client", f_handle=f_handle, f_ordinal=f_idx
            )
            f_ev.recordWorkerEvent(
                f_sp, 1, EvidenceKind.CONTROLLER_STARTED, f_ordinal=f_idx
            )
            for f_c_idx, f_combo in enumerate(f_plan.combinations):
                if f_idx == 1 and f_c_idx == 5:
                    continue
                f_failed = f_idx == 1 and f_c_idx == 4
                f_ev.recordControllerResult(
                    f_sp,
                    f_combo,
                    f_payload={"exit_code": 1 if f_failed else 0},
                    f_ordinal=f_idx,
                )
                for f_rank in range(f_sp.tasks):
                    f_ev.recordRankResult(
                        f_sp,
                        f_rank,
                        f_combo,
                        f_payload={"exit_code": 1 if f_failed and f_rank == 1 else 0},
                        f_ordinal=f_idx,
                    )
                if not f_failed:
                    f_complete.add((f_idx, f_combo.name))
            f_ev.recordSchedulerObservation(
                f_sp,
                "reconciler",
                1,
                f_payload={
                    "state": "failed" if f_idx else "succeeded",
                    "handle": f_handle.toDict(),
                },
                f_ordinal=f_idx,
            )

        # Rank logs for every combination of points 0 and 1
        for f_idx in (0, 1):
            f_sp = f_plan.scale_points[f_idx]
            f_pt_dir = f_store.layout.pointDir(f_sp, f_idx)
            for f_salt, f_combo in enumerate(f_plan.combinations):
                f_dir = os.path.join(f_pt_dir, "logs", f_combo.name)
                os.makedirs(f_dir, exist_ok=True)
                for f_rank in range(f_sp.tasks):
                    f_vals = rankValues(f_rank, f_salt)
                    with open(os.path.join(f_dir, f"rank_{f_rank}.log"), "w") as f_f:
                        f_f.write(rankLog(f_vals["write"], f_vals["read"]))
        return f_store.layout.runRoot, f_complete

    def _bmtoolEquivalentOf(
        self, f_run_root: str, f_complete: Set[Tuple[int, str]], f_dest: str
    ) -> None:
        """bmtool layout of just the complete combinations, aggregated by LsmioAggOutput."""
        f_resolved = RunRootResolver.resolve(f_run_root, f_allow_partial=True)
        for f_pt in f_resolved.points:
            for f_combo in f_resolved.plan.combinations:
                if (f_pt.ordinal, f_combo.name) not in f_complete:
                    continue
                for f_rank in range(f_pt.scalePoint.tasks):
                    f_dst = os.path.join(
                        f_dest,
                        str(f_pt.scalePoint.nodes),
                        "2026-10-07",
                        f"out-native-{f_combo.stripe_count}-{f_combo.block_size}"
                        f"-2026-10-07-node{100 + f_rank:03d}-0.txt",
                    )
                    os.makedirs(os.path.dirname(f_dst), exist_ok=True)
                    shutil.copyfile(
                        os.path.join(
                            f_pt.pointDir, "logs", f_combo.name, f"rank_{f_rank}.log"
                        ),
                        f_dst,
                    )
        with patch("lsmiotool.lib.log.Console.warning"):
            output.LsmioAggOutput(f_dest).generateReports(f_out_dir=f_dest)

    def testPartiallyFailedRunReportsCompleteCombinations(self) -> None:
        """M9: 'parse' reports every combination with complete rank output, warns about
        the rest and keeps exit code 4 (the run did not succeed)."""
        f_run_root, f_complete = self._setupPartialRun("run-partial-001")
        self.assertEqual(len(f_complete), 10)
        with self.assertRaises(Exception):
            RunRootResolver.resolve(f_run_root)  # strict resolution still refuses

        f_out = os.path.join(self.m_temp_dir, "reports")
        f_inst = ParseMain(f_request=parseParseArguments([f_run_root, "--output-dir", f_out]))
        f_stdout, f_stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", f_stdout), patch("sys.stderr", f_stderr):
            f_code = f_inst.run()
        self.assertEqual(f_code, 4, f_stderr.getvalue())
        f_err = f_stderr.getvalue()
        self.assertIn("did not succeed", f_err)
        self.assertIn("01-tasks-2", f_err)
        self.assertIn("rank 1 has no successful result", f_err)
        self.assertIn("02-tasks-4", f_err)
        self.assertIn("c4_b64K", f_stdout.getvalue())

        f_bm = os.path.join(self.m_temp_dir, "bm-equivalent")
        self._bmtoolEquivalentOf(f_run_root, f_complete, f_bm)
        f_tree = readTree(f_out)
        self.assertEqual(f_tree, readTree(f_bm))
        self.assertEqual(len(f_tree), 11)  # 10 agg files + lsm-report.csv

        # The same run moved into an archive regenerates in place without raising
        f_arch = os.path.join(self.m_temp_dir, "variants", "outputs-native:run")
        shutil.copytree(f_run_root, f_arch)
        with patch("lsmiotool.lib.log.Console.warning"):
            self.assertIsNotNone(output.regenerateLsmioReports(f_arch))
        self.assertEqual(
            readFile(os.path.join(f_arch, data.LSM_REPORT_FILE)),
            readFile(os.path.join(f_bm, data.LSM_REPORT_FILE)),
        )

    def testRunWithNothingCompleteKeepsExitCode(self) -> None:
        """No complete combination: no report, exit 4 for a failed run."""
        f_run_root, _f_complete = self._setupPartialRun("run-partial-002")
        f_layout_logs = os.path.join(f_run_root, "points")
        for f_dir, _f_sub, f_files in os.walk(f_layout_logs):
            for f_name in f_files:
                if f_name.startswith("rank_") and f_name.endswith(".log"):
                    os.remove(os.path.join(f_dir, f_name))
        f_out = os.path.join(self.m_temp_dir, "reports-none")
        f_inst = ParseMain(f_request=parseParseArguments([f_run_root, "--output-dir", f_out]))
        f_stderr = io.StringIO()
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", f_stderr):
            self.assertEqual(f_inst.run(), 4)
        self.assertIn("no point/combination has complete output", f_stderr.getvalue())
        self.assertFalse(os.path.exists(os.path.join(f_out, data.LSM_REPORT_FILE)))

    def _parseRunAndBmtoolLayout(
        self, f_target: str, f_setup: str, f_log_for: Any
    ) -> Tuple[bytes, bytes]:
        """Parse a succeeded <f_target> 'local' run whose combination logs come from
        f_log_for(combo), and lay the same logs out like bmtool; return both reports."""
        f_run_root, f_plan, _ = self.m_helper._setupSucceededRun(
            f"run-{f_target}-bm-001", f_target, "local", f_setup
        )
        f_bm = os.path.join(self.m_temp_dir, f"bm-{f_target}")
        f_logs = os.path.join(f_run_root, "points", "00-tasks-1", "logs")
        os.makedirs(f_logs, exist_ok=True)
        for f_combo in f_plan.combinations:
            f_text = f_log_for(f_combo)
            with open(os.path.join(f_logs, f"{f_target}_{f_combo.name}.stdout"), "w") as f_f:
                f_f.write(f_text)
            f_dst = os.path.join(
                f_bm, "1", "2026-10-07",
                f"out-{f_setup.lower()}-{f_combo.stripe_count}-{f_combo.block_size}"
                "-2026-10-07-node100-0.txt",
            )
            os.makedirs(os.path.dirname(f_dst), exist_ok=True)
            with open(f_dst, "w") as f_f:
                f_f.write(f_text)

        f_out = os.path.join(self.m_temp_dir, f"out-{f_target}")
        f_inst = ParseMain(f_request=parseParseArguments([f_run_root, "--output-dir", f_out]))
        f_stderr = io.StringIO()
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", f_stderr):
            self.assertEqual(f_inst.run(), 0, f_stderr.getvalue())
        f_name = data.IOR_REPORT_FILE if f_target == "ior" else data.LMP_REPORT_FILE
        if f_target == "ior":
            data.generateBmtoolIorReport(f_bm)
        else:
            data.generateBmtoolLmpReport(f_bm)
        return readFile(os.path.join(f_out, f_name)), readFile(os.path.join(f_bm, f_name))

    def testRunParseIorReportLikeBmtool(self) -> None:
        """M14: the run parser's ior-report.csv rows are bmtool's for the same logs."""
        f_example = os.path.join(EXAMPLE_IOR_OUTPUTS, "2", "2023-07-21")

        def logFor(f_combo: Any) -> str:
            f_name = next(
                f_n
                for f_n in sorted(os.listdir(f_example))
                if f"-{f_combo.stripe_count}-{f_combo.block_size}-" in f_n
            )
            with open(os.path.join(f_example, f_name)) as f_f:
                return f_f.read()

        f_ours, f_bmtool = self._parseRunAndBmtoolLayout("ior", "BASE", logFor)
        self.assertEqual(f_ours, f_bmtool)
        self.assertEqual(len(f_ours.splitlines()), 12)

    def testRunParseLmpReportLikeBmtool(self) -> None:
        """M16 (constructed fixture only): run parser lmp-report.csv rows match bmtool."""

        def logFor(f_combo: Any) -> str:
            f_seed = f_combo.stripe_count + len(f_combo.block_size)
            return lmpLog([100.0 + f_seed + f_i for f_i in range(10)])

        f_ours, f_bmtool = self._parseRunAndBmtoolLayout("lmp", "LSMIO", logFor)
        self.assertEqual(f_ours, f_bmtool)
        self.assertEqual(len(f_ours.splitlines()), 6)
        self.assertTrue(f_ours.startswith(b"1,4,64K,iwrite,"))

    def testArchivedLayoutPinsRunRoot(self) -> None:
        f_layout = ArchivedArtifactLayout("/a/b/outputs-x:run", "run-1")
        self.assertEqual(f_layout.runRoot, "/a/b/outputs-x:run")
        self.assertEqual(f_layout.manifestPath, "/a/b/outputs-x:run/manifest.json")
        self.assertEqual(f_layout.runId, "run-1")

    def testParseInfersLatestRunFromBenchmarkRootFilteredByTarget(self) -> None:
        """'parse lsmio' searches <benchmark_root>/runs and ignores other targets (H8)."""
        f_lsm_root, _p, _ = self.m_helper._setupSucceededRun(
            "run-20261001T000000Z-aaaa", "lsmio", "local"
        )
        self._writeRankLogs(f_lsm_root)
        self.m_helper._setupSucceededRun(
            "run-20261009T000000Z-bbbb", "ior", "local", "BASE"
        )
        # A bmtool working dir named after the benchmark must not shadow <root>/runs
        os.makedirs(os.path.join(self.m_temp_dir, "lsmio", "outputs"))

        f_out = os.path.join(self.m_temp_dir, "reports")
        f_inst = ParseMain(
            f_request=parseParseArguments(["lsmio", "--output-dir", f_out]),
            f_benchmark_root=self.m_temp_dir,
        )
        f_stdout, f_stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", f_stdout), patch("sys.stderr", f_stderr):
            f_code = f_inst.run()
        self.assertEqual(f_code, 0, f_stderr.getvalue())
        self.assertTrue(data.isUsableReport(os.path.join(f_out, data.LSM_REPORT_FILE)))

        # Scale filter: no lsmio 'small' run exists
        f_inst = ParseMain(
            f_request=parseParseArguments(["lsmio", "small", "--output-dir", f_out]),
            f_benchmark_root=self.m_temp_dir,
        )
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            self.assertEqual(f_inst.run(), 3)


class ParseArchiveModeTest(unittest.TestCase):
    """'parse lsmio backends <scale>' / 'parse <archive dir>' / compare on archives (H7, H8)."""

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.mkdtemp(prefix="lsmiotool-parsearchive-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_temp_dir, ignore_errors=True)

    def _run(self, f_argv: List[str]) -> int:
        f_inst = ParseMain(
            f_request=parseParseArguments(f_argv), f_benchmark_root=self.m_temp_dir
        )
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            with patch("lsmiotool.lib.log.Console.warning"):
                return f_inst.run()

    def testCliAcceptsScaleForms(self) -> None:
        self.assertEqual(parseParseArguments(["lsmio", "small"]).scale, "small")
        self.assertEqual(parseParseArguments(["lsmio", "baseline"]).scale, "variants")
        f_req = parseParseArguments(["lsmio", "backends", "small"])
        self.assertEqual((f_req.mode, f_req.scale), ("backends", "small"))

    def testParseBackendsRegeneratesEveryArm(self) -> None:
        f_dest = os.path.join(self.m_temp_dir, "lsmio-archive", "backends", "small")
        for f_arm in ("adios", "native"):
            writeBmtoolLayout(os.path.join(f_dest, f"outputs-{f_arm}"), ["1", "2"], f_arm)
        self.assertEqual(self._run(["lsmio", "backends", "small"]), 0)
        for f_arm in ("adios", "native"):
            f_report = os.path.join(f_dest, f"outputs-{f_arm}", data.LSM_REPORT_FILE)
            with open(f_report) as f_f:
                f_rows = f_f.read().splitlines()
            self.assertEqual(len(f_rows), 24)
            self.assertTrue(f_rows[0].startswith("1,16,1M,write,"))

    def testBareBenchmarkNameIsNeverACwdDirectory(self) -> None:
        """M17: 'parse lsmio <scale>' resolves runs even when the cwd has a lsmio/ dir with
        outputs-* children (bmtool leaves $BM_PATH/lsmio/outputs-failed); './lsmio' parses it."""
        f_cwd = os.path.join(self.m_temp_dir, "cwd")
        f_failed = os.path.join(f_cwd, "lsmio", "outputs-failed")
        writeBmtoolLayout(f_failed, ["8"], "native")
        f_orig_cwd = os.getcwd()
        os.chdir(f_cwd)
        try:
            self.assertEqual(self._run(["lsmio", "small"]), 3)  # no runs to parse
            self.assertFalse(
                os.path.exists(os.path.join(f_failed, data.LSM_REPORT_FILE))
            )
            self.assertEqual(self._run(["./lsmio"]), 0)
        finally:
            os.chdir(f_orig_cwd)
        self.assertTrue(data.isUsableReport(os.path.join(f_failed, data.LSM_REPORT_FILE)))

    def testParseVariantsParsesRunsNotArchive(self) -> None:
        """Like bmtool lsmio-parse.sh, only backends mode reads the archive: 'parse lsmio
        variants' parses the latest run and leaves archived arms alone (R4)."""
        f_dest = os.path.join(self.m_temp_dir, "lsmio-archive", "variants")
        f_arm = os.path.join(f_dest, "outputs-native-autotune:run")
        writeBmtoolLayout(f_arm, ["8"], "native-autotune")
        self.assertEqual(self._run(["lsmio", "variants"]), 3)  # no runs to parse
        self.assertFalse(os.path.exists(os.path.join(f_arm, data.LSM_REPORT_FILE)))
        # An archive dest is still parsed when named explicitly
        self.assertEqual(self._run([f_dest]), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_arm, data.LSM_REPORT_FILE)))

    def testParseMissingArchiveDestination(self) -> None:
        self.assertEqual(self._run(["lsmio", "backends", "large"]), 3)

    def testParseBmtoolLayoutDirectory(self) -> None:
        f_dir = os.path.join(self.m_temp_dir, "outputs-native")
        writeBmtoolLayout(f_dir, ["1"])
        self.assertEqual(self._run([f_dir]), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_dir, data.LSM_REPORT_FILE)))

    def testCompareVariantsNeverWritesEmptyReport(self) -> None:
        """compare variants regenerates bmtool-layout arms and leaves data-less ones alone."""
        f_archive = os.path.join(self.m_temp_dir, "variants")
        writeBmtoolLayout(
            os.path.join(f_archive, "outputs-native-autotune"), ["8"], "native-autotune"
        )
        f_empty_arm = os.path.join(f_archive, "outputs-native-legacy")
        os.makedirs(f_empty_arm)
        f_zero_arm = os.path.join(f_archive, "outputs-native-mmap")
        os.makedirs(f_zero_arm)
        open(os.path.join(f_zero_arm, data.LSM_REPORT_FILE), "w").close()

        f_cm = CompareVariantsMain(
            f_archive_folder=f_archive,
            f_op="write",
            f_stripes=4,
            f_blocksize="1M",
            f_output_dir=os.path.join(self.m_temp_dir, "plots"),
        )
        with patch("lsmiotool.lib.log.Console.warning"), patch(
            "lsmiotool.lib.log.Console.info"
        ):
            self.assertEqual(f_cm.run(), 0)
        self.assertTrue(
            data.isUsableReport(
                os.path.join(f_archive, "outputs-native-autotune", data.LSM_REPORT_FILE)
            )
        )
        self.assertFalse(
            os.path.exists(os.path.join(f_empty_arm, data.LSM_REPORT_FILE))
        )
        self.assertEqual(
            os.path.getsize(os.path.join(f_zero_arm, data.LSM_REPORT_FILE)), 0
        )


class ParseLegacyBmtoolDirsTest(unittest.TestCase):
    """M15: parseLegacy reads $BM_PATH/<benchmark>/outputs like bmtool's parse."""

    def setUp(self) -> None:
        self.m_root = tempfile.mkdtemp(prefix="lsmiotool-parselegacy-")

    def tearDown(self) -> None:
        shutil.rmtree(self.m_root, ignore_errors=True)

    def _run(self, *f_args: str, **f_kwargs: Any) -> int:
        from lsmiotool.lib.main import ParseLegacyMain

        f_kwargs.setdefault("f_benchmark_root", self.m_root)
        f_inst = ParseLegacyMain(*f_args, **f_kwargs)
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            with patch("lsmiotool.lib.log.Console.warning"):
                return f_inst.run()

    def testLsmioDefaultsToBenchmarkRootOutputs(self) -> None:
        f_outputs = os.path.join(self.m_root, "lsmio", "outputs")
        writeBmtoolLayout(f_outputs, ["1", "2"])
        # The old lookup (<BM_DIR>/logs/jobs) must not be used
        writeBmtoolLayout(os.path.join(self.m_root, "logs", "jobs"), ["1"])
        self.assertEqual(self._run("lsmio", "bake"), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_outputs, data.LSM_REPORT_FILE)))
        self.assertFalse(
            os.path.exists(os.path.join(self.m_root, "logs", "jobs", data.LSM_REPORT_FILE))
        )
        with open(os.path.join(f_outputs, data.LSM_REPORT_FILE)) as f_f:
            self.assertEqual(len(f_f.read().splitlines()), 24)

    def testExplicitPath(self) -> None:
        f_dir = os.path.join(self.m_root, "elsewhere")
        writeBmtoolLayout(f_dir, ["8"])
        self.assertEqual(self._run("lsmio", "variants", f_dir), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_dir, data.LSM_REPORT_FILE)))
        self.assertEqual(self._run("lsmio", "variants"), 1)  # no <root>/lsmio/outputs

    def testIorAndLmpOutputs(self) -> None:
        f_ior = os.path.join(self.m_root, "ior", "outputs")
        shutil.copytree(EXAMPLE_IOR_OUTPUTS, f_ior)
        self.assertEqual(self._run("ior", "small"), 0)
        self.assertTrue(data.isUsableReport(os.path.join(f_ior, data.IOR_REPORT_FILE)))

        f_lmp = os.path.join(self.m_root, "lmp", "outputs", "2", "2026-10-07")
        os.makedirs(f_lmp)
        with open(os.path.join(f_lmp, "out-lmp-lsmio-4-1M-2026-10-07-node1-0.txt"), "w") as f_f:
            f_f.write(lmpLog([10.0, 20.0]))
        self.assertEqual(self._run("lmp", "bake"), 0)
        with open(os.path.join(self.m_root, "lmp", "outputs", data.LMP_REPORT_FILE)) as f_f:
            self.assertEqual(
                f_f.read(), "2,4,1M,iwrite,20.00,20.00,20.00,18.25,1,1\n"
            )

    def testBackendsArchiveMode(self) -> None:
        f_dest = os.path.join(self.m_root, "lsmio-archive", "backends", "small")
        for f_arm in ("native", "rocksdb"):
            writeBmtoolLayout(os.path.join(f_dest, f"outputs-{f_arm}"), ["1", "2"], f_arm)
        self.assertEqual(self._run("lsmio", "backends", "small"), 0)
        for f_arm in ("native", "rocksdb"):
            self.assertTrue(
                data.isUsableReport(
                    os.path.join(f_dest, f"outputs-{f_arm}", data.LSM_REPORT_FILE)
                )
            )
        # Explicit archive destination; a missing one is an error
        f_other = os.path.join(self.m_root, "other-dest")
        writeBmtoolLayout(os.path.join(f_other, "outputs-plugin"), ["1"], "plugin")
        self.assertEqual(self._run("lsmio", "backends", "small", f_other), 0)
        self.assertTrue(
            data.isUsableReport(os.path.join(f_other, "outputs-plugin", data.LSM_REPORT_FILE))
        )
        self.assertEqual(self._run("lsmio", "backends", "large"), 3)

    def testSsdUsesSsdBenchmarkRoot(self) -> None:
        from lsmiotool.lib.main import ParseLegacyMain

        with patch("lsmiotool.lib.main.siteBenchmarkRoots", return_value=["/ssd/bm"]) as f_roots:
            f_inst = ParseLegacyMain("lsmio", "small", ssd=True)
            self.assertEqual(
                f_inst._getTargetDir("lsmio", "small", True), "/ssd/bm/lsmio/outputs"
            )
        f_roots.assert_called_with(("ssd",))

    def testDefaultTargetDirIsBenchmarkRootOutputs(self) -> None:
        """bmtool parses $BM_PATH/<benchmark>/outputs (jobs/<benchmark>-vars.in.sh)."""
        from lsmiotool.lib.main import ParseLegacyMain

        for f_bench in ("ior", "lsmio", "lmp"):
            f_inst = ParseLegacyMain(f_bench, "bake", f_benchmark_root="/bm")
            self.assertEqual(
                f_inst._getTargetDir(f_bench, "bake", False),
                os.path.join("/bm", f_bench, "outputs"),
            )
        self.assertEqual(self._run("lsmio", "bake"), 1)  # no outputs directory

    def testInvalidArguments(self) -> None:
        from lsmiotool.lib.main import ParseLegacyMain

        for f_args in (
            ("lsmio", "backends", "variants"),
            ("ior", "backends", "small"),
            ("lsmio", "small", "/a", "/b"),
        ):
            with patch("lsmiotool.lib.log.Console.error"):
                with self.assertRaises(SystemExit):
                    ParseLegacyMain(*f_args)


if __name__ == "__main__":
    unittest.main()
