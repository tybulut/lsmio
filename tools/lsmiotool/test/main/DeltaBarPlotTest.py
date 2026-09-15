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
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lsmiotool.lib import plot


class DeltaBarPlotTest(unittest.TestCase):
    """Unit tests for DeltaBarPlot asserting negative preservation, zero line, and dynamic colors."""

    def testConstructionAndProperties(self) -> None:
        """Asserts DeltaBarPlot configures allow_negative=True and is_percentage flag."""
        meta = plot.PlotMetaData("Delta Test", "Variant", "Delta Bandwidth (%)")
        pdata = plot.PlotData("Delta", ["footer", "btree"], [15.5, -8.2])

        chart_pct = plot.DeltaBarPlot(meta, pdata, f_is_percentage=True)
        self.assertTrue(chart_pct.allow_negative)
        self.assertTrue(chart_pct.is_percentage)

        chart_abs = plot.DeltaBarPlot(meta, pdata, f_is_percentage=False)
        self.assertTrue(chart_abs.allow_negative)
        self.assertFalse(chart_abs.is_percentage)

    def testNegativeValuesPreservedWithoutClampingOrWarnings(self) -> None:
        """Asserts negative delta values are not clamped to 0.0 and emit zero warnings (INV-PAIR-4)."""
        meta = plot.PlotMetaData("Delta Preservation", "Variant", "Delta (%)")
        pdata = plot.PlotData("Delta", ["v1", "v2", "v3"], [-25.0, 50.0, -10.0])

        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = os.path.join(temp_dir, "delta.png")
            chart = plot.DeltaBarPlot(meta, pdata)

            with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
                with patch("matplotlib.pyplot.bar") as mock_bar:
                    chart.plot(out_file)

                    # No clamping warnings
                    self.assertEqual(mock_warn.call_count, 0)

                    # Bar values preserve negatives exactly
                    self.assertTrue(mock_bar.called)
                    call_args = mock_bar.call_args
                    _, y_values = call_args[0]
                    self.assertEqual(list(y_values), [-25.0, 50.0, -10.0])

    def testHorizontalZeroLineAndColorEncoding(self) -> None:
        """Asserts DeltaBarPlot draws a horizontal zero line and uses green/red bar colors."""
        meta = plot.PlotMetaData("Color Test", "Variant", "Delta (%)")
        pdata = plot.PlotData("Delta", ["gain", "loss", "neutral"], [12.0, -15.0, 0.0])

        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = os.path.join(temp_dir, "color.png")
            chart = plot.DeltaBarPlot(meta, pdata)

            with patch("matplotlib.pyplot.axhline") as mock_axhline:
                with patch("matplotlib.pyplot.bar") as mock_bar:
                    chart.plot(out_file)

                    # Zero line asserted
                    mock_axhline.assert_called_once()
                    self.assertEqual(mock_axhline.call_args[0][0], 0)

                    # Colors: >=0 is green (#2ca02c), <0 is red (#d62728)
                    call_kwargs = mock_bar.call_args[1]
                    colors = call_kwargs.get("color")
                    self.assertEqual(colors, ["#2ca02c", "#d62728", "#2ca02c"])

    def testAnnotationFormatting(self) -> None:
        """Asserts DeltaBarPlot formats annotations with % for percentage and +/- signs."""
        meta = plot.PlotMetaData("Annotate Test", "Variant", "Delta (%)")
        pdata = plot.PlotData("Delta", ["p1", "p2"], [10.5, -5.2])

        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = os.path.join(temp_dir, "annotate.png")

            # Percentage mode
            chart_pct = plot.DeltaBarPlot(meta, pdata, f_is_percentage=True)
            with patch("matplotlib.pyplot.annotate") as mock_annotate:
                chart_pct.plot(out_file)
                labels = [call[0][0] for call in mock_annotate.call_args_list]
                self.assertEqual(labels, ["+10.5%", "-5.2%"])

            # Absolute mode
            chart_abs = plot.DeltaBarPlot(meta, pdata, f_is_percentage=False)
            with patch("matplotlib.pyplot.annotate") as mock_annotate_abs:
                chart_abs.plot(out_file)
                labels_abs = [call[0][0] for call in mock_annotate_abs.call_args_list]
                self.assertEqual(labels_abs, ["+10.5", "-5.2"])

    def testEndToEndFileGeneration(self) -> None:
        """Asserts actual file creation on disk."""
        meta = plot.PlotMetaData("EndToEnd Test", "Variant", "Delta Bandwidth (%)")
        pdata = plot.PlotData("Delta", ["footer", "btree"], [10.0, -5.0])

        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = os.path.join(temp_dir, "real_delta.png")
            chart = plot.DeltaBarPlot(meta, pdata)
            chart.plot(out_file)

            self.assertTrue(os.path.isfile(out_file))
            self.assertGreater(os.path.getsize(out_file), 0)


if __name__ == "__main__":
    unittest.main()
