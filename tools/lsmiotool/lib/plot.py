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
from typing import Any, Dict, List, Union, Sequence

import numpy as np
from numpy.typing import NDArray
import matplotlib.pyplot as plt

from lsmiotool.lib.log import Console
import math

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from lsmiotool.lib.compare import CompareFigure, ComparePanel


class PlotMetaData:
    """Metadata for plot visualization, including title and axis labels."""

    def __init__(self, title: str, x_label: str, y_label: str) -> None:
        """
        Initialize plot metadata.

        Args:
            title: Plot title
            x_label: Label for x-axis
            y_label: Label for y-axis
        """
        self.title: str = title
        self.x_label: str = x_label
        self.y_label: str = y_label


class PlotData:
    """Data series for plotting, including legend and x/y values."""

    def __init__(
        self, legend: str, x_series: List[Union[int, str]], y_series: List[float]
    ) -> None:
        """
        Initialize plot data.

        Args:
            legend: Legend label for the data series
            x_series: List of x-axis values
            y_series: List of y-axis values
        """
        self.legend: str = legend
        self.x_series: NDArray[Any] = np.array(x_series)
        self.y_series: NDArray[np.float64] = np.array(y_series)


class Plot:
    """Single data series plot with metadata."""

    def __init__(self, meta_data: PlotMetaData, plot_data: PlotData) -> None:
        """
        Initialize plot with metadata and data series.

        Args:
            meta_data: Plot metadata
            plot_data: Data series to plot
        """
        self.meta_data: PlotMetaData = meta_data
        self.plot_data: PlotData = plot_data

    def plot(self, file_name: str) -> None:
        """
        Generate and save the plot.

        Args:
            file_name: Path to save the plot image
        """
        # Metadata
        plt.title(self.meta_data.title)
        plt.xlabel(self.meta_data.x_label)
        plt.ylabel(self.meta_data.y_label)

        # Plot data
        plt.plot(self.plot_data.x_series, self.plot_data.y_series)

        # Configure and save image
        plt.grid()
        plt.savefig(file_name)
        plt.close()


class MultiPlot:
    """Multiple data series plot with metadata."""

    def __init__(self, meta_data: PlotMetaData, *plot_data_args: PlotData) -> None:
        """
        Initialize plot with metadata and multiple data series.

        Args:
            meta_data: Plot metadata
            *plot_data_args: Variable number of data series to plot
        """
        self.meta_data: PlotMetaData = meta_data
        self.plot_data_list: List[PlotData] = list(plot_data_args)

    def plot(self, file_name: str) -> None:
        """
        Generate and save the plot.

        Args:
            file_name: Path to save the plot image
        """
        # Metadata
        plt.title(self.meta_data.title)
        plt.xlabel(self.meta_data.x_label)
        plt.ylabel(self.meta_data.y_label)

        # Plot data series
        for plot_data in self.plot_data_list:
            plt.plot(plot_data.x_series, plot_data.y_series, label=plot_data.legend)

        # Configure and save image
        plt.grid()
        plt.legend()
        plt.savefig(file_name)
        plt.close()


class MultiBarPlot:
    """Grouped bar chart plotting multiple data series with metadata."""

    m_meta_data: PlotMetaData
    m_plot_data_list: List[PlotData]
    m_allow_negative: bool

    def __init__(
        self,
        f_meta_data: PlotMetaData,
        *f_plot_data_args: PlotData,
        allow_negative: bool = False,
    ) -> None:
        """Initialize grouped bar plot with metadata and multiple data series.

        Args:
            f_meta_data: Plot metadata (title, axis labels)
            *f_plot_data_args: Variable number of data series to plot
            allow_negative: Whether to preserve negative values without clamping
        """
        self.m_meta_data: PlotMetaData = f_meta_data
        self.m_plot_data_list: List[PlotData] = list(f_plot_data_args)
        self.m_allow_negative: bool = allow_negative

    @property
    def allow_negative(self) -> bool:
        return self.m_allow_negative

    def plot(self, f_file_name: str) -> None:
        """Generate and save grouped bar chart.

        Args:
            f_file_name: Path to save the plot image
        """
        x_categories: List[Any] = []
        if self.m_plot_data_list:
            for plot_data in self.m_plot_data_list:
                for x in plot_data.x_series:
                    if x not in x_categories:
                        x_categories.append(x)
            try:
                x_categories.sort()
            except TypeError:
                pass

        if len(x_categories) > 6:
            fig_width = max(8.0, len(x_categories) * 0.45)
            plt.figure(figsize=(fig_width, 6.0))
        else:
            plt.figure()

        # Metadata
        plt.title(self.m_meta_data.title)
        plt.xlabel(self.m_meta_data.x_label)
        plt.ylabel(self.m_meta_data.y_label)

        if self.m_plot_data_list and x_categories:
            n_series = len(self.m_plot_data_list)
            total_group_width = 0.8
            bar_width = total_group_width / n_series
            indices = np.arange(len(x_categories))

            for i, plot_data in enumerate(self.m_plot_data_list):
                series_map = dict(zip(plot_data.x_series, plot_data.y_series))
                y_values: List[float] = []
                for cat in x_categories:
                    val = float(series_map.get(cat, 0.0))
                    if not self.m_allow_negative and val < 0.0:
                        Console.warning(
                            f"Negative value {val} clamped to 0.0 for {plot_data.legend}"
                        )
                        val = 0.0
                    y_values.append(val)

                offset = (i - (n_series - 1) / 2.0) * bar_width
                plt.bar(
                    indices + offset,
                    y_values,
                    width=bar_width,
                    label=plot_data.legend,
                )

            if len(x_categories) > 6:
                rotation = 60 if len(x_categories) > 15 else 45
                plt.xticks(
                    indices,
                    [str(cat) for cat in x_categories],
                    rotation=rotation,
                    ha="right",
                    rotation_mode="anchor",
                )
            else:
                plt.xticks(indices, [str(cat) for cat in x_categories])

            handles, labels = plt.gca().get_legend_handles_labels()
            if handles:
                plt.legend()

        # Configure and save image
        plt.grid(True, axis="y", linestyle="--", alpha=0.6)
        plt.tight_layout()
        plt.savefig(f_file_name, bbox_inches="tight")
        plt.close()


class DeltaBarPlot(MultiBarPlot):
    """Specialized delta bar chart generator rendering bidirectional +/- deltas."""

    m_is_percentage: bool

    def __init__(
        self,
        f_meta_data: PlotMetaData,
        f_plot_data: PlotData,
        f_is_percentage: bool = True,
    ) -> None:
        super().__init__(f_meta_data, f_plot_data, allow_negative=True)
        self.m_is_percentage: bool = f_is_percentage

    @property
    def is_percentage(self) -> bool:
        return self.m_is_percentage

    def plot(self, f_file_name: str) -> None:
        """Renders single-bar delta chart with horizontal zero line and green/red bars."""
        if not self.m_plot_data_list:
            return

        plot_data = self.m_plot_data_list[0]
        categories = list(plot_data.x_series)
        values = [float(v) for v in plot_data.y_series]
        n = len(categories)

        fig_width = max(8.0, n * 0.5) if n > 6 else 8.0
        plt.figure(figsize=(fig_width, 6.0))

        plt.title(self.m_meta_data.title)
        plt.xlabel(self.m_meta_data.x_label)
        plt.ylabel(self.m_meta_data.y_label)

        indices = np.arange(n)
        # Green for improvements (>= 0), Red for regressions (< 0)
        colors = ["#2ca02c" if v >= 0.0 else "#d62728" for v in values]
        bars = plt.bar(indices, values, width=0.6, color=colors)

        # Explicit horizontal zero line (INV-PAIR-4)
        plt.axhline(0, color="black", linewidth=0.8, linestyle="-", zorder=2)

        # Value labels above positive bars and below negative bars
        for bar, val in zip(bars, values):
            va = "bottom" if val >= 0.0 else "top"
            label = f"{val:+.1f}%" if self.m_is_percentage else f"{val:+.1f}"
            plt.annotate(
                label,
                (bar.get_x() + bar.get_width() / 2.0, val),
                xytext=(0, 3 if val >= 0.0 else -10),
                textcoords="offset points",
                ha="center",
                va=va,
                fontsize=9,
            )

        if n > 6:
            rotation = 60 if n > 15 else 45
            plt.xticks(
                indices,
                [str(c) for c in categories],
                rotation=rotation,
                ha="right",
                rotation_mode="anchor",
            )
        else:
            plt.xticks(indices, [str(c) for c in categories])

        plt.grid(True, axis="y", linestyle="--", alpha=0.6)
        plt.tight_layout()
        plt.savefig(f_file_name, bbox_inches="tight")
        plt.close()


class ComparePanelPlot:
    """Renders grouped bar or line charts for lsmiotool compare invocations."""

    m_figure: CompareFigure
    m_style: str

    def __init__(self, f_figure: CompareFigure, f_style: str) -> None:
        """Initialize ComparePanelPlot with figure spec and style ('bars' or 'lines')."""
        if f_style not in ("bars", "lines"):
            raise ValueError(
                f"Invalid plot style '{f_style}': must be 'bars' or 'lines'"
            )
        self.m_figure: CompareFigure = f_figure
        self.m_style: str = f_style

    def _widestLabelInches(self, f_fig: "plt.Figure") -> float:
        """Width in inches of the widest line of any x category label."""
        renderer = f_fig.canvas.get_renderer()
        widest = 0.0
        for cat in self.m_figure.x_categories:
            for line in str(cat).split("\n"):
                text = f_fig.text(0, 0, line, fontsize=plt.rcParams["xtick.labelsize"])
                widest = max(widest, text.get_window_extent(renderer).width / f_fig.dpi)
                text.remove()
        return widest

    def _makeLegend(self, f_fig: "plt.Figure", f_ncol: int, f_anchor_y: float):
        """Adds the figure legend, lower centre at f_anchor_y (figure fraction)."""
        handles = []
        labels = []
        for idx in self.m_figure.legend:
            series = self.m_figure.series[idx]
            if self.m_style == "bars":
                handle = Patch(facecolor=series.colour, label=series.label)
            else:
                handle = Line2D(
                    [0],
                    [0],
                    color=series.colour,
                    marker="o",
                    label=series.label,
                )
            handles.append(handle)
            labels.append(series.label)
        return f_fig.legend(
            handles=handles,
            labels=labels,
            loc="lower center",
            bbox_to_anchor=(0.5, f_anchor_y),
            ncol=f_ncol,
            frameon=True,
        )

    def _legendHeightInches(self, f_fig: "plt.Figure", f_ncol: int) -> float:
        """Height in inches of the legend as drawn with f_ncol columns."""
        legend = self._makeLegend(f_fig, f_ncol, 0.0)
        height = legend.get_window_extent(f_fig.canvas.get_renderer()).height
        legend.remove()
        return height / f_fig.dpi

    def draw(self) -> "plt.Figure":
        """Builds and returns the matplotlib figure without saving or closing it."""
        grid = self.m_figure.grid
        n_rows = len(grid)
        n_cols = len(grid[0]) if n_rows > 0 else 0
        if n_rows == 0 or n_cols == 0:
            fig, _ = plt.subplots(1, 1, squeeze=False)
            return fig

        n_cats = len(self.m_figure.x_categories)
        panel_height = 4.0
        grid_height = panel_height * n_rows

        # Provisional size; panel width and legend height are set once the
        # label and legend extents can be measured.
        fig, axes = plt.subplots(
            n_rows, n_cols, squeeze=False, figsize=(5.0 * n_cols, grid_height + 2.0)
        )

        panel_width = max(5.0, 0.45 * n_cats + 1.5)
        if n_cats <= 6:
            # Unrotated tick labels: one slot per category must hold the widest line.
            label_width = self._widestLabelInches(fig)
            panel_width = max(panel_width, (label_width + 0.2) * (n_cats + 0.1) + 1.5)
        fig_width = panel_width * n_cols

        n_legend = len(self.m_figure.legend)
        ncol = min(n_legend, max(1, int(fig_width / 2.5))) if n_legend > 0 else 1
        legend_height = self._legendHeightInches(fig, ncol) if n_legend > 0 else 0.0
        # Title band: the suptitle's own height between two 0.1 in pads.
        title_text = fig.text(
            0, 0, self.m_figure.title, fontsize=plt.rcParams["figure.titlesize"]
        )
        title_height = (
            title_text.get_window_extent(fig.canvas.get_renderer()).height / fig.dpi
        )
        title_text.remove()
        top_height = title_height + 0.2
        fig_height = grid_height + legend_height + 0.2 + top_height
        fig.set_size_inches(fig_width, fig_height)

        for r in range(n_rows):
            for c in range(n_cols):
                panel: ComparePanel = grid[r][c]
                ax = axes[r][c]

                ax.set_title(panel.title)
                ax.set_ylabel(panel.y_label)
                if r == n_rows - 1:
                    ax.set_xlabel(self.m_figure.x_label)

                ax.set_xticks(range(n_cats))
                if n_cats > 6:
                    rotation = 60 if n_cats > 15 else 45
                    ax.set_xticklabels(
                        [str(cat) for cat in self.m_figure.x_categories],
                        rotation=rotation,
                        ha="right",
                        rotation_mode="anchor",
                    )
                else:
                    ax.set_xticklabels([str(cat) for cat in self.m_figure.x_categories])

                if panel.zero_line:
                    ax.axhline(0, color="black", linewidth=0.8)

                if self.m_style == "bars":
                    n_series = len(panel.values)
                    width = (0.8 / n_series) if n_series > 0 else 0.8
                    for i, (series_idx, cat_vals) in enumerate(panel.values):
                        series = self.m_figure.series[series_idx]
                        offset = (i - (n_series - 1) / 2.0) * width
                        finite_xs: List[float] = []
                        finite_ys: List[float] = []
                        for cat_idx, v in enumerate(cat_vals):
                            if v is not None and not math.isnan(v):
                                finite_xs.append(cat_idx + offset)
                                finite_ys.append(v)
                        if finite_xs:
                            bars = ax.bar(
                                finite_xs,
                                finite_ys,
                                width=width,
                                color=series.colour,
                            )
                            if panel.value_labels:
                                for bar, val in zip(bars, finite_ys):
                                    va = "bottom" if val >= 0.0 else "top"
                                    label = f"{val:+.1f}%"
                                    ax.annotate(
                                        label,
                                        (bar.get_x() + bar.get_width() / 2.0, val),
                                        xytext=(0, 3 if val >= 0.0 else -10),
                                        textcoords="offset points",
                                        ha="center",
                                        va=va,
                                        fontsize=9,
                                    )
                else:
                    for series_idx, cat_vals in panel.values:
                        series = self.m_figure.series[series_idx]
                        y_vals = [
                            math.nan if (v is None or math.isnan(v)) else float(v)
                            for v in cat_vals
                        ]
                        ax.plot(
                            range(n_cats),
                            y_vals,
                            color=series.colour,
                            marker="o",
                        )
                    finite = [
                        v
                        for _, cat_vals in panel.values
                        for v in cat_vals
                        if v is not None and not math.isnan(v)
                    ]
                    # Lines start at 0 as bars do, unless the data is negative.
                    if finite and min(finite) >= 0.0:
                        top = max(finite) * 1.05
                        ax.set_ylim(0.0, top if top > 0.0 else 1.0)
                    elif finite and max(finite) <= 0.0:
                        ax.set_ylim(min(finite) * 1.05, 0.0)

                if panel.no_data:
                    ax.text(
                        0.5,
                        0.5,
                        "no data",
                        transform=ax.transAxes,
                        ha="center",
                        va="center",
                    )

                ax.grid(True, axis="y", linestyle="--", alpha=0.6)

        fig.suptitle(self.m_figure.title, y=1.0 - 0.1 / fig_height, va="top")

        bottom_frac = (legend_height + 0.2) / fig_height
        # tight_layout itself keeps the panels below the suptitle.
        fig.tight_layout(rect=[0, bottom_frac, 1, 1.0])

        if self.m_figure.legend:
            self._makeLegend(fig, ncol, 0.1 / fig_height)

        return fig

    def plot(self, f_file_name: str) -> None:
        """Builds the figure, saves it to file, and ensures the figure is closed."""
        fig = self.draw()
        try:
            fig.savefig(f_file_name, bbox_inches="tight")
        finally:
            plt.close(fig)
