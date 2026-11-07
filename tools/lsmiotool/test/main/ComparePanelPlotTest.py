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

import math
import os
import tempfile
import unittest
from typing import Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.colors import to_hex

from lsmiotool.lib.compare import CompareFigure, ComparePanel, CompareSeries
from lsmiotool.lib.plot import ComparePanelPlot


def _makePanel(
    f_title: str = "Panel Title",
    f_y_label: str = "MiB/s",
    f_values: Tuple[Tuple[int, Tuple[Optional[float], ...]], ...] = (),
    f_no_data: bool = False,
    f_zero_line: bool = False,
    f_value_labels: bool = False,
) -> ComparePanel:
    return ComparePanel(
        title=f_title,
        y_label=f_y_label,
        values=f_values,
        no_data=f_no_data,
        zero_line=f_zero_line,
        value_labels=f_value_labels,
    )


def _makeFigure(
    f_title: str = "Figure Title",
    f_x_label: str = "Nodes",
    f_x_categories: Tuple[str, ...] = ("1", "2"),
    f_grid: Optional[Tuple[Tuple[ComparePanel, ...], ...]] = None,
    f_series: Optional[Tuple[CompareSeries, ...]] = None,
    f_legend: Optional[Tuple[int, ...]] = None,
) -> CompareFigure:
    series = (
        f_series
        if f_series is not None
        else (CompareSeries("s0", "#2a78d6"), CompareSeries("s1", "#eb6834"))
    )
    legend = f_legend if f_legend is not None else tuple(range(len(series)))
    grid = f_grid if f_grid is not None else ((_makePanel(),),)
    return CompareFigure(
        title=f_title,
        x_label=f_x_label,
        x_categories=f_x_categories,
        grid=grid,
        series=series,
        legend=legend,
    )


class ComparePanelPlotTest(unittest.TestCase):
    """Unit tests for ComparePanelPlot rendering bar and line charts."""

    def tearDown(self) -> None:
        super().tearDown()
        plt.close("all")

    def testBarsDrawOneSlotPerSeriesInItsColour(self) -> None:
        s0 = CompareSeries("s0", "#2a78d6")
        s1 = CompareSeries("s1", "#eb6834")
        s2 = CompareSeries("s2", "#1baf7a")
        series = (s0, s1, s2)

        panel00 = _makePanel(
            f_title="P00",
            f_values=(
                (0, (10.0, 15.0)),
                (2, (20.0, None)),
            ),
        )
        panel01 = _makePanel(f_title="P01")
        panel10 = _makePanel(f_title="P10")
        panel11 = _makePanel(f_title="P11")
        grid = (
            (panel00, panel01),
            (panel10, panel11),
        )

        fig_spec = _makeFigure(
            f_x_categories=("catA", "catB"),
            f_grid=grid,
            f_series=series,
            f_legend=(0, 1, 2),
        )

        plot = ComparePanelPlot(fig_spec, "bars")
        fig = plot.draw()

        ax = fig.axes[0]
        containers = ax.containers
        rectangles = [patch for container in containers for patch in container]
        self.assertEqual(len(rectangles), 3)

        self.assertEqual(len(containers), 2)
        for patch in containers[0]:
            self.assertEqual(to_hex(patch.get_facecolor()), "#2a78d6")
        for patch in containers[1]:
            self.assertEqual(to_hex(patch.get_facecolor()), "#1baf7a")

        patch_s0_cat0 = containers[0][0]
        patch_s2_cat0 = containers[1][0]
        center_s0 = patch_s0_cat0.get_x() + patch_s0_cat0.get_width() / 2.0
        center_s2 = patch_s2_cat0.get_x() + patch_s2_cat0.get_width() / 2.0
        self.assertAlmostEqual((center_s0 + center_s2) / 2.0, 0.0)

    def testNanAndNoneLeaveNoBarAndNoLabel(self) -> None:
        series = (CompareSeries("s0", "#2a78d6"),)
        panel = _makePanel(
            f_title="Delta",
            f_y_label="%",
            f_values=((0, (12.5, math.nan, None, -3.0)),),
            f_zero_line=True,
            f_value_labels=True,
        )
        fig_spec = _makeFigure(
            f_x_categories=("c0", "c1", "c2", "c3"),
            f_grid=((panel,),),
            f_series=series,
            f_legend=(0,),
        )

        plot = ComparePanelPlot(fig_spec, "bars")
        fig = plot.draw()

        ax = fig.axes[0]
        rectangles = [patch for container in ax.containers for patch in container]
        self.assertEqual(len(rectangles), 2)

        texts = [t.get_text() for t in ax.texts]
        self.assertEqual(texts, ["+12.5%", "-3.0%"])

    def testLinesBreakAtGapsAndShowSingleMarkers(self) -> None:
        s0 = CompareSeries("s0", "#2a78d6")
        s1 = CompareSeries("s1", "#eb6834")
        series = (s0, s1)

        panel = _makePanel(
            f_values=(
                (0, (10.0, None, 20.0, math.nan, 30.0)),
                (1, (None, 40.0, None, None, None)),
            ),
        )
        fig_spec = _makeFigure(
            f_x_categories=("c0", "c1", "c2", "c3", "c4"),
            f_grid=((panel,),),
            f_series=series,
            f_legend=(0, 1),
        )

        plot = ComparePanelPlot(fig_spec, "lines")
        fig = plot.draw()

        ax = fig.axes[0]
        self.assertEqual(len(ax.lines), 2)
        line0 = ax.lines[0]
        line1 = ax.lines[1]

        self.assertEqual(line0.get_marker(), "o")
        self.assertEqual(line1.get_marker(), "o")

        y0 = list(line0.get_ydata())
        self.assertEqual(y0[0], 10.0)
        self.assertTrue(math.isnan(y0[1]))
        self.assertEqual(y0[2], 20.0)
        self.assertTrue(math.isnan(y0[3]))
        self.assertEqual(y0[4], 30.0)

        y1 = list(line1.get_ydata())
        self.assertTrue(math.isnan(y1[0]))
        self.assertEqual(y1[1], 40.0)
        self.assertTrue(math.isnan(y1[2]))
        self.assertTrue(math.isnan(y1[3]))
        self.assertTrue(math.isnan(y1[4]))
        self.assertEqual(line1.get_marker(), "o")

    def testZeroLineAndNoDataNote(self) -> None:
        panel_zl = _makePanel(
            f_title="ZeroLine",
            f_zero_line=True,
            f_no_data=False,
            f_values=((0, (10.0, 20.0)),),
        )
        panel_nd = _makePanel(
            f_title="NoData",
            f_zero_line=False,
            f_no_data=True,
            f_values=(),
        )
        fig_spec = _makeFigure(
            f_grid=((panel_zl, panel_nd),),
            f_series=(CompareSeries("s0", "#2a78d6"),),
            f_legend=(0,),
        )

        plot = ComparePanelPlot(fig_spec, "bars")
        fig = plot.draw()

        ax_zl = fig.axes[0]
        ax_nd = fig.axes[1]

        self.assertEqual(len(ax_zl.lines), 1)
        self.assertEqual(list(ax_zl.lines[0].get_ydata()), [0, 0])
        self.assertFalse(any(t.get_text() == "no data" for t in ax_zl.texts))

        self.assertEqual(len(ax_nd.lines), 0)
        self.assertTrue(any(t.get_text() == "no data" for t in ax_nd.texts))

    def testLegendIsOutsideEveryPanel(self) -> None:
        cases = [
            ("6x3 bars", 6, 3, 9, 2, "bars"),
            ("2x2 lines", 2, 2, 12, 4, "lines"),
            ("4x2 variants", 4, 2, 4, 26, "bars"),
        ]

        for _name, n_rows, n_cols, n_series, n_cats, style in cases:
            series = tuple(
                CompareSeries(
                    f"series_{i}", f"#{i:02x}{i * 20:02x}{(i * 30) % 256:02x}"
                )
                for i in range(n_series)
            )
            cats = tuple(f"cat_{c}" for c in range(n_cats))

            grid = tuple(
                tuple(
                    _makePanel(
                        f_title=f"P{r}{c}",
                        f_values=((0, tuple(float(k + 1) for k in range(n_cats))),),
                    )
                    for c in range(n_cols)
                )
                for r in range(n_rows)
            )

            fig_spec = _makeFigure(
                f_x_categories=cats,
                f_grid=grid,
                f_series=series,
                f_legend=tuple(range(n_series)),
            )

            plot = ComparePanelPlot(fig_spec, style)
            fig = plot.draw()
            fig.canvas.draw()

            self.assertEqual(len(fig.legends), 1)
            leg = fig.legends[0]
            leg_box = leg.get_window_extent()

            for ax in fig.axes:
                self.assertFalse(
                    leg_box.overlaps(ax.get_window_extent()),
                    f"Legend overlaps axes in {_name}",
                )

            expected_labels = [series[i].label for i in range(n_series)]
            actual_labels = [t.get_text() for t in leg.get_texts()]
            self.assertEqual(actual_labels, expected_labels)

            plt.close(fig)

    def testTitlesAndAxisLabels(self) -> None:
        panel00 = _makePanel(f_title="P00", f_y_label="MiB/s")
        panel01 = _makePanel(f_title="P01", f_y_label="Seconds")
        panel10 = _makePanel(f_title="P10", f_y_label="Count")
        panel11 = _makePanel(f_title="P11", f_y_label="%")
        grid = (
            (panel00, panel01),
            (panel10, panel11),
        )

        fig_spec = _makeFigure(
            f_title="Overall Compare Title",
            f_x_label="Node Count",
            f_x_categories=("1", "2", "4"),
            f_grid=grid,
        )

        plot = ComparePanelPlot(fig_spec, "bars")
        fig = plot.draw()

        self.assertIsNotNone(fig._suptitle)
        self.assertEqual(fig._suptitle.get_text(), "Overall Compare Title")

        expected_titles = [["P00", "P01"], ["P10", "P11"]]
        expected_ylabels = [["MiB/s", "Seconds"], ["Count", "%"]]

        for r in range(2):
            for c in range(2):
                ax = fig.axes[r * 2 + c]
                self.assertEqual(ax.get_title(), expected_titles[r][c])
                self.assertEqual(ax.get_ylabel(), expected_ylabels[r][c])
                self.assertEqual(
                    [t.get_text() for t in ax.get_xticklabels()],
                    ["1", "2", "4"],
                )
                if r == 1:
                    self.assertEqual(ax.get_xlabel(), "Node Count")
                else:
                    self.assertEqual(ax.get_xlabel(), "")

    def testPlotWritesPngAndClosesItsFigure(self) -> None:
        fig_spec = _makeFigure()
        plot = ComparePanelPlot(fig_spec, "bars")

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = os.path.join(tmp_dir, "test.png")
            plot.plot(out_path)

            self.assertTrue(os.path.isfile(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)
            self.assertEqual(len(plt.get_fignums()), 0)

            bad_path = os.path.join(tmp_dir, "nonexistent_dir", "test.png")
            with self.assertRaises(OSError):
                plot.plot(bad_path)
            self.assertEqual(len(plt.get_fignums()), 0)

    def testUnknownStyleIsRefused(self) -> None:
        fig_spec = _makeFigure()
        with self.assertRaises(ValueError):
            ComparePanelPlot(fig_spec, "scatter")
        with self.assertRaises(ValueError):
            ComparePanelPlot(fig_spec, "")
        with self.assertRaises(ValueError):
            ComparePanelPlot(fig_spec, "BARS")
        with self.assertRaises(ValueError):
            ComparePanelPlot(fig_spec, "line")
