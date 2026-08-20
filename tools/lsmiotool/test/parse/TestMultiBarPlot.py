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

import os
import tempfile
import unittest
from unittest import TestCase
from unittest.mock import patch, MagicMock

import numpy as np

from lsmiotool.lib import plot


class TestMultiBarPlot(TestCase):
    """Unit tests for MultiBarPlot grouped bar chart plotting class."""

    m_temp_dir: tempfile.TemporaryDirectory

    def setUp(self) -> None:
        self.m_temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.m_temp_dir.cleanup()

    def testGroupedBarGeneration(self) -> None:
        """Test grouped bar chart generation creates a non-empty image file."""
        meta = plot.PlotMetaData("Test Comparison", "Nodes", "Throughput (MB/s)")
        pd1 = plot.PlotData("series1", [1, 2, 4], [100.0, 200.0, 400.0])
        pd2 = plot.PlotData("series2", [1, 2, 4], [150.0, 250.0, 450.0])

        out_path = os.path.join(self.m_temp_dir.name, "test_grouped_bar.png")
        mbp = plot.MultiBarPlot(meta, pd1, pd2)
        mbp.plot(out_path)

        self.assertTrue(os.path.exists(out_path), "Plot file must exist")
        self.assertGreater(os.path.getsize(out_path), 0, "Plot file must not be empty")

    def testMultipleSeriesOffsets(self) -> None:
        """Test bar widths and offsets are calculated dynamically across multiple series."""
        meta = plot.PlotMetaData("Multi-series Test", "Nodes", "Throughput")
        pd1 = plot.PlotData("s1", [1, 2], [10.0, 20.0])
        pd2 = plot.PlotData("s2", [1, 2], [30.0, 40.0])
        pd3 = plot.PlotData("s3", [1, 2], [50.0, 60.0])

        mbp = plot.MultiBarPlot(meta, pd1, pd2, pd3)
        self.assertEqual(len(mbp.m_plot_data_list), 3)

        out_path = os.path.join(self.m_temp_dir.name, "multi_series.png")
        with patch("matplotlib.pyplot.bar") as mock_bar:
            mbp.plot(out_path)
            self.assertEqual(mock_bar.call_count, 3)

            # Check bar width calculation: 0.8 / 3
            expected_width = 0.8 / 3.0
            for call_args in mock_bar.call_args_list:
                _, kwargs = call_args
                self.assertAlmostEqual(kwargs["width"], expected_width, places=5)

    def testNegativeValueClamping(self) -> None:
        """Test negative values are clamped to 0.0 and trigger a warning."""
        meta = plot.PlotMetaData("Negative Test", "Nodes", "Throughput")
        pd = plot.PlotData("s_neg", [1, 2, 4], [-50.0, 100.0, -10.0])

        out_path = os.path.join(self.m_temp_dir.name, "clamped.png")
        mbp = plot.MultiBarPlot(meta, pd)

        with patch("lsmiotool.lib.log.Console.warning") as mock_warn:
            with patch("matplotlib.pyplot.bar") as mock_bar:
                mbp.plot(out_path)

                # Two warnings for two negative values
                self.assertEqual(mock_warn.call_count, 2)

                # Check clamped values passed to bar
                call_args = mock_bar.call_args_list[0]
                _, y_plotted = call_args[0]
                self.assertEqual(y_plotted, [0.0, 100.0, 0.0])

    def testEmptyPlotDataList(self) -> None:
        """Test MultiBarPlot handles empty plot data list gracefully."""
        meta = plot.PlotMetaData("Empty Test", "Nodes", "Throughput")
        out_path = os.path.join(self.m_temp_dir.name, "empty.png")
        mbp = plot.MultiBarPlot(meta)
        mbp.plot(out_path)

        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 0)

    def testMismatchedXSeries(self) -> None:
        """Test series with differing x-categories are merged with 0.0 fill."""
        meta = plot.PlotMetaData("Mismatched X", "Nodes", "Throughput")
        pd1 = plot.PlotData("s1", [1, 2], [10.0, 20.0])
        pd2 = plot.PlotData("s2", [2, 4], [30.0, 40.0])

        out_path = os.path.join(self.m_temp_dir.name, "mismatched.png")
        mbp = plot.MultiBarPlot(meta, pd1, pd2)

        with patch("matplotlib.pyplot.bar") as mock_bar:
            mbp.plot(out_path)
            self.assertEqual(mock_bar.call_count, 2)

            # s1 should have values for x in [1, 2, 4] -> [10.0, 20.0, 0.0]
            s1_y = mock_bar.call_args_list[0][0][1]
            self.assertEqual(s1_y, [10.0, 20.0, 0.0])

            # s2 should have values for x in [1, 2, 4] -> [0.0, 30.0, 40.0]
            s2_y = mock_bar.call_args_list[1][0][1]
            self.assertEqual(s2_y, [0.0, 30.0, 40.0])
