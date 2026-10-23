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

import io
import json
import os
import tempfile
import unittest
from typing import Any, Dict
from unittest.mock import patch

from lsmiotool.lib import paperdata, plot
from lsmiotool.lib.cli import LatexRequest
from lsmiotool.lib.main import LatexDataMain, LatexMain

# Only 'latex' needs PyYAML; without it these tests skip
try:
    import yaml  # noqa: F401

    _HAVE_YAML = True
except ImportError:
    _HAVE_YAML = False


def lsmReportLine(f_node: int, f_stripes: int, f_block_size: str, f_op: str, f_max: str) -> str:
    return f"{f_node},{f_stripes},{f_block_size},{f_op},{f_max},50,75,2559.96,40960,10\n"


@unittest.skipUnless(_HAVE_YAML, "PyYAML is not installed (only 'lsmiotool latex' needs it)")
class LatexMainTest(unittest.TestCase):
    """LatexDataMain and LatexMain run against a small sources.yaml and report."""

    def setUp(self) -> None:
        self.m_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.m_tmp.cleanup)
        self.m_root: str = self.m_tmp.name
        self.m_data: str = os.path.join(self.m_root, "data")
        os.makedirs(os.path.join(self.m_data, "run"))
        with open(os.path.join(self.m_data, "run", "lsm-report.csv"), "w") as f_file:
            for f_node in (1, 2, 4):
                f_file.write(lsmReportLine(f_node, 4, "64K", "write", str(f_node * 1024)))
                f_file.write(lsmReportLine(f_node, 4, "64K", "read", str(f_node * 2048)))
        self.m_sources: str = os.path.join(self.m_root, "sources.yaml")
        self.writeSources(self.doc())
        self.m_out: str = os.path.join(self.m_root, "out")

    def doc(self) -> Dict[str, Any]:
        return {
            "schema": 1,
            "datasets": [{"output": "bm/a.tsv", "kind": "lsmio", "source": "run"}],
            "figures": [
                {
                    "file": "fig.pdf",
                    "title": "T",
                    "y_label": "Y",
                    "y_divisor": 1024,
                    "series": [
                        {
                            "label": "W",
                            "dataset": "bm/a.tsv",
                            "stripes": 4,
                            "block_size": "64K",
                            "op": "write",
                        },
                        {
                            "label": "R",
                            "dataset": "bm/a.tsv",
                            "stripes": 4,
                            "block_size": "64K",
                            "op": "read",
                        },
                    ],
                }
            ],
        }

    def writeSources(self, f_doc: Dict[str, Any]) -> None:
        with open(self.m_sources, "w") as f_file:
            json.dump(f_doc, f_file)  # JSON is YAML

    def dataRequest(self) -> LatexRequest:
        return LatexRequest("data", self.m_sources, f_data_dir=self.m_data, f_output_dir=self.m_out)

    def plotsRequest(self, f_pdf_dir: str) -> LatexRequest:
        return LatexRequest("plots", self.m_sources, f_tsv_dir=self.m_out, f_output_dir=f_pdf_dir)

    def testDataWritesTheTsvsAndReturnsZero(self) -> None:
        """latex data builds each TSV from its report and exits 0."""
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        with open(os.path.join(self.m_out, "bm", "a.tsv"), "rb") as f_file:
            f_lines = f_file.read().split(b"\r\n")
        self.assertEqual(f_lines[0].decode(), "\t".join(paperdata.LSMIO_HEADER))
        self.assertEqual(len(f_lines), 8)
        self.assertEqual(f_lines[7], b"")
        self.assertEqual(f_lines[1].decode().split("\t")[:5], ["1", "4", "64K", "read", "2048.00"])
        self.assertEqual(f_lines[6].decode().split("\t")[:5], ["4", "4", "64K", "write", "4096.00"])

    def testDataExpandsTheHomeDirectory(self) -> None:
        """A '~' in --data-dir and --output-dir is the home directory."""
        f_req = LatexRequest("data", self.m_sources, f_data_dir="~/d", f_output_dir="~/o")
        with patch.dict(os.environ, {"HOME": self.m_root}):
            os.rename(self.m_data, os.path.join(self.m_root, "d"))
            self.assertEqual(LatexDataMain(f_req).run(), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.m_root, "o", "bm", "a.tsv")))

    def testDataReturnsOneWhenSourcesCannotBeRead(self) -> None:
        """A missing sources.yaml is an error with exit status 1 and no output."""
        f_req = LatexRequest(
            "data", os.path.join(self.m_root, "nope.yaml"), f_data_dir=self.m_data, f_output_dir=self.m_out
        )
        with patch.object(paperdata.Console, "error") as f_error:
            self.assertEqual(LatexDataMain(f_req).run(), 1)
        self.assertIn("cannot read", f_error.call_args[0][0])
        self.assertFalse(os.path.exists(self.m_out))

    def testDataReturnsOneWhenAReportIsMissing(self) -> None:
        """A dataset whose report is not in --data-dir stops the run with status 1."""
        f_doc = self.doc()
        f_doc["datasets"][0]["source"] = "nowhere"
        self.writeSources(f_doc)
        with patch("lsmiotool.lib.main.log.Console.error") as f_error:
            self.assertEqual(LatexDataMain(self.dataRequest()).run(), 1)
        self.assertIn("cannot read report", f_error.call_args[0][0])
        self.assertFalse(os.path.exists(os.path.join(self.m_out, "bm", "a.tsv")))

    def testPlotsDrawsEveryFigureFromTheTsvs(self) -> None:
        """latex plots draws one PDF per figure, dividing y by y_divisor, and exits 0."""
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        f_pdf_dir = os.path.join(self.m_root, "pdf")
        with patch.object(plot.MultiPlot, "plot") as f_plot:
            with patch.object(plot, "PlotData", wraps=plot.PlotData) as f_data:
                self.assertEqual(LatexMain(self.plotsRequest(f_pdf_dir)).run(), 0)
        f_plot.assert_called_once_with(os.path.join(f_pdf_dir, "fig.pdf"))
        f_write, f_read = f_data.call_args_list
        self.assertEqual(f_write[0][0], "W")
        self.assertEqual(f_write[0][1], [1, 2, 4])
        self.assertEqual(f_write[0][2], [1.0, 2.0, 4.0])
        self.assertEqual(f_read[0][2], [2.0, 4.0, 8.0])
        self.assertTrue(os.path.isdir(f_pdf_dir))

    def testPlotsWritesARealPdf(self) -> None:
        """Without mocks the figure ends up as a non-empty PDF."""
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        f_pdf_dir = os.path.join(self.m_root, "pdf")
        self.assertEqual(LatexMain(self.plotsRequest(f_pdf_dir)).run(), 0)
        with open(os.path.join(f_pdf_dir, "fig.pdf"), "rb") as f_file:
            self.assertEqual(f_file.read(4), b"%PDF")

    def testPlotsDefaultsToTheCurrentDirectory(self) -> None:
        """Without --output-dir the PDFs go to the working directory."""
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        f_req = LatexRequest("plots", self.m_sources, f_tsv_dir=self.m_out)
        with patch.object(plot.MultiPlot, "plot") as f_plot:
            with patch("os.getcwd", return_value=self.m_root):
                self.assertEqual(LatexMain(f_req).run(), 0)
        f_plot.assert_called_once_with(os.path.join(self.m_root, "fig.pdf"))

    def testPlotsReturnsOneWhenASeriesHasNoData(self) -> None:
        """A series with no point in its TSV is an error, not an empty line."""
        f_doc = self.doc()
        f_doc["figures"][0]["series"][0]["block_size"] = "8M"
        self.writeSources(f_doc)
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        with patch("lsmiotool.lib.main.log.Console.error") as f_error:
            self.assertEqual(LatexMain(self.plotsRequest(os.path.join(self.m_root, "pdf"))).run(), 1)
        self.assertIn("series 'W' has no data", f_error.call_args[0][0])

    def testPlotsReturnsOneWhenASeriesIsAllNan(self) -> None:
        """A series whose points are all nan (runs without data) would draw nothing."""
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        with open(os.path.join(self.m_out, "bm", "a.tsv"), "w", newline="") as f_file:
            f_file.write("\t".join(paperdata.LSMIO_HEADER) + "\r\n")
            for f_node in (1, 2):
                f_file.write(f"{f_node}\t4\t64K\twrite" + "\tnan" * 5 + "\tNA\r\n")
                f_file.write(f"{f_node}\t4\t64K\tread\t1024.00" + "\t1.00" * 5 + "\r\n")
        with patch("lsmiotool.lib.main.log.Console.error") as f_error:
            self.assertEqual(LatexMain(self.plotsRequest(os.path.join(self.m_root, "pdf"))).run(), 1)
        self.assertIn("series 'W' has no data", f_error.call_args[0][0])

    def testPlotsReturnsOneWhenTheTsvsAreMissing(self) -> None:
        """Running plots before data reports the missing TSV."""
        with patch("lsmiotool.lib.main.log.Console.error") as f_error:
            self.assertEqual(LatexMain(self.plotsRequest(os.path.join(self.m_root, "pdf"))).run(), 1)
        self.assertIn("cannot read", f_error.call_args[0][0])

    def testPlotsReturnsOneWhenThereAreNoFigures(self) -> None:
        """A sources.yaml without figures has nothing to draw."""
        f_doc = self.doc()
        del f_doc["figures"]
        self.writeSources(f_doc)
        with patch("lsmiotool.lib.main.log.Console.error") as f_error:
            self.assertEqual(LatexMain(self.plotsRequest(os.path.join(self.m_root, "pdf"))).run(), 1)
        self.assertIn("defines no figures", f_error.call_args[0][0])

    def testPlotsCreatesTheDirectoryOfAFigureFile(self) -> None:
        """A figure file in a subdirectory gets that directory created."""
        f_doc = self.doc()
        f_doc["figures"][0]["file"] = "sub/fig.pdf"
        self.writeSources(f_doc)
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        f_pdf_dir = os.path.join(self.m_root, "pdf")
        with patch.object(plot.MultiPlot, "plot") as f_plot:
            self.assertEqual(LatexMain(self.plotsRequest(f_pdf_dir)).run(), 0)
        f_plot.assert_called_once_with(os.path.join(f_pdf_dir, "sub", "fig.pdf"))
        self.assertTrue(os.path.isdir(os.path.join(f_pdf_dir, "sub")))

    def testPlotsReturnsOneWhenDrawingFails(self) -> None:
        """An OSError or ValueError while drawing is an error with status 1, not a traceback."""
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        for f_err in (OSError("disk full"), ValueError("bad axis")):
            with self.subTest(f_err=f_err):
                with patch.object(plot.MultiPlot, "plot", side_effect=f_err):
                    with patch("lsmiotool.lib.main.log.Console.error") as f_error:
                        self.assertEqual(
                            LatexMain(self.plotsRequest(os.path.join(self.m_root, "pdf"))).run(), 1
                        )
                self.assertIn(str(f_err), f_error.call_args[0][0])

    def testDataReturnsOneWhenTheOutputCannotBeWritten(self) -> None:
        """An --output-dir that is a file is an error with status 1, not a traceback."""
        with open(self.m_out, "w") as f_file:
            f_file.write("not a directory")
        with patch("lsmiotool.lib.main.log.Console.error") as f_error:
            self.assertEqual(LatexDataMain(self.dataRequest()).run(), 1)
        self.assertIn("cannot write the output", f_error.call_args[0][0])

    def testDataPrintsEachWrittenFileAndItsSources(self) -> None:
        """latex data prints every TSV it wrote with where its rows came from."""
        with patch("sys.stdout", new_callable=io.StringIO) as f_stdout:
            self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        self.assertEqual(
            f_stdout.getvalue(),
            f"Wrote {os.path.join(self.m_out, 'bm/a.tsv')}\n  run: 6 rows\n",
        )

    def testPlotsPrintsEachImage(self) -> None:
        """latex plots prints the path of every PDF it drew."""
        self.assertEqual(LatexDataMain(self.dataRequest()).run(), 0)
        f_pdf_dir = os.path.join(self.m_root, "pdf")
        with patch.object(plot.MultiPlot, "plot"):
            with patch("sys.stdout", new_callable=io.StringIO) as f_stdout:
                self.assertEqual(LatexMain(self.plotsRequest(f_pdf_dir)).run(), 0)
        self.assertEqual(
            f_stdout.getvalue(), f"Image generated: {os.path.join(f_pdf_dir, 'fig.pdf')}\n"
        )

    def testSourcesPathExpandsTheHomeDirectory(self) -> None:
        """A '~' in the sources.yaml path is the home directory, as for the directories."""
        with patch.dict(os.environ, {"HOME": self.m_root}):
            f_data = LatexRequest(
                "data", "~/sources.yaml", f_data_dir=self.m_data, f_output_dir=self.m_out
            )
            self.assertEqual(LatexDataMain(f_data).run(), 0)
            f_plots = LatexRequest("plots", "~/sources.yaml", f_tsv_dir=self.m_out)
            with patch.object(plot.MultiPlot, "plot"):
                with patch("os.getcwd", return_value=self.m_root):
                    self.assertEqual(LatexMain(f_plots).run(), 0)


if __name__ == "__main__":
    unittest.main()
