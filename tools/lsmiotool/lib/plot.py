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

    def __init__(self, f_meta_data: PlotMetaData, *f_plot_data_args: PlotData) -> None:
        """Initialize grouped bar plot with metadata and multiple data series.

        Args:
            f_meta_data: Plot metadata (title, axis labels)
            *f_plot_data_args: Variable number of data series to plot
        """
        self.m_meta_data: PlotMetaData = f_meta_data
        self.m_plot_data_list: List[PlotData] = list(f_plot_data_args)

    def plot(self, f_file_name: str) -> None:
        """Generate and save grouped bar chart.

        Args:
            f_file_name: Path to save the plot image
        """
        plt.figure()
        # Metadata
        plt.title(self.m_meta_data.title)
        plt.xlabel(self.m_meta_data.x_label)
        plt.ylabel(self.m_meta_data.y_label)

        if self.m_plot_data_list:
            x_categories: List[Any] = []
            for plot_data in self.m_plot_data_list:
                for x in plot_data.x_series:
                    if x not in x_categories:
                        x_categories.append(x)
            try:
                x_categories.sort()
            except TypeError:
                pass

            if x_categories:
                n_series = len(self.m_plot_data_list)
                total_group_width = 0.8
                bar_width = total_group_width / n_series
                indices = np.arange(len(x_categories))

                for i, plot_data in enumerate(self.m_plot_data_list):
                    series_map = dict(zip(plot_data.x_series, plot_data.y_series))
                    y_values: List[float] = []
                    for cat in x_categories:
                        val = float(series_map.get(cat, 0.0))
                        if val < 0.0:
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

                plt.xticks(indices, [str(cat) for cat in x_categories])
                handles, labels = plt.gca().get_legend_handles_labels()
                if handles:
                    plt.legend()

        # Configure and save image
        plt.grid(True)
        plt.savefig(f_file_name)
        plt.close()
