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

import argparse
import importlib
import os
import signal
import subprocess
import sys

import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Union

from lsmiotool import settings
from lsmiotool.lib import data, debuggable, env, log, plot

# Catch CTRL-C
signal.signal(signal.SIGINT, signal.SIG_DFL)


class BaseMain(debuggable.DebuggableObject):
    """Base class for all main execution modes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize base main execution mode."""
        super(BaseMain, self).__init__()


class TestMain(BaseMain):
    """Test execution mode for running unit tests."""

    def run(self) -> None:
        """Execute test suite and report results."""
        from lsmiotool import test
        test.run_and_report()


class ShellMain(BaseMain):
    """Interactive shell execution mode."""

    def run(self) -> None:
        """Start an interactive Python shell with local context."""
        import code
        code.interact(local=dict(globals(), **locals()))



class NotImplemented(BaseMain):
    """Placeholder for unimplemented execution modes."""

    def run(self) -> None:
        """Exit with error for unimplemented modes."""
        log.Console.error("Not Implemented")
        sys.exit(1)



class DemoMain(BaseMain):
    """Demo execution mode for example plots."""

    def demoRunDummy(self) -> None:
        """Generate a dummy plot with sample data."""
        fn = "demo.png"
        md = plot.PlotMetaData(
            "Sports Watch Data", "Average Pulse", "Calorie Burnage"
        )
        pd = plot.PlotData(
            [80, 85, 90, 95, 100, 105, 110, 115, 120, 125],
            [240, 250, 260, 270, 280, 290, 300, 310, 320, 330]
        )
        p = plot.Plot(md, pd)
        p.plot(fn)
        log.Console.debug(f"Image generated: {fn}.")

    def demoRunSingle(self) -> None:
        """Generate a single IOR benchmark plot."""
        ior_run = data.IorSummaryData(
            "/home/sbulut/src/archive.ISAMBARD/ior-base/outputs/ior-report.csv"
        )
        x_series, y_series = ior_run.time_series(False, 4, "64K")
        fn = "ior-write-4-64k.png"
        md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")
        pd = plot.PlotData("ior-base-4-64k", x_series, y_series)
        p = plot.Plot(md, pd)
        p.plot(fn)
        log.Console.debug(f"Image generated: {fn}.")

    def demoRunMulti(self) -> None:
        """Generate multiple IOR benchmark plots."""
        ior_run = data.IorSummaryData(
            "/home/sbulut/src/archive.ISAMBARD/ior-base/outputs/ior-report.csv"
        )
        fn = "ior-write-64k.png"
        md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")

        x_series, y_series = ior_run.time_series(False, 4, "64K")
        pda = plot.PlotData("ior-base-4-64k", x_series, y_series)
        x_series, y_series = ior_run.time_series(False, 16, "64K")
        pdb = plot.PlotData("ior-base-16-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb)
        p.plot(fn)
        log.Console.debug(f"Image generated: {fn}.")

    def run(self) -> None:
        """Execute demo mode with multiple plots."""
        return self.demoRunMulti()




class LatexMain(BaseMain):
    """LaTeX document generation mode for paper plots."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with HPC environment selection."""
        super(LatexMain, self).__init__()
        self.hpc = args[0]
        if self.hpc == "viking2":
            self._results_from_viking2()
        elif self.hpc == "isambard":
            self._results_from_isambard()
        else:  # "viking":
            self._results_from_viking()

    def _results_from_viking(self) -> None:
        """Set up paths for Viking HPC environment."""
        self.ior_data = env.ior_data
        self.lsmio_dir = env.lsmio_dir
        self.lsmio_data = env.lsmio_data
        self.plots_dir = env.plots_dir
        # If you need an ior_dir, construct it from lsmio_dir or add to JSON

    def _results_from_viking2(self) -> None:
        """Set up paths for Viking2 HPC environment."""
        self.ior_data = env.ior_data
        self.lsmio_dir = env.lsmio_dir
        self.lsmio_data = env.lsmio_data
        self.plots_dir = env.plots_dir
        # If you need an ior_dir, construct it from lsmio_dir or add to JSON

    def _results_from_isambard(self) -> None:
        """Set up paths for Isambard HPC environment."""
        self.ior_data = env.ior_data
        self.lsmio_dir = env.lsmio_dir
        self.lsmio_data = env.lsmio_data
        self.plots_dir = env.plots_dir
        # If you need an ior_dir, construct it from lsmio_dir or add to JSON

    def _gen_png_name(self, title: str, is_read: bool, num_stripes: int, stripe_size: str) -> str:
        """Generate PNG filename from plot parameters."""
        operation = "read" if is_read else "write"
        return f"{title}-{operation}-{num_stripes}-{stripe_size}.pdf"

    def _gen_png_path(self, file_name: str) -> str:
        """Generate full path for PNG file."""
        return os.path.join(self.plots_dir, file_name)

    def run_step_paper41(self) -> None:
        """Generate write performance plot for paper section 4.1."""
        ior_run = data.IorSummaryData(os.path.join(self.ior_dir, "ior-report.csv"))
        fn = self._gen_png_name("ior", False, 4, "64K")
        md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")

        x_series, y_series = ior_run.time_series(False, 4, "64K")
        pda = plot.PlotData("ior-base-4-64k", x_series, y_series)

        p = plot.Plot(md, pda)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper42(self) -> None:
        """Generate read performance plot for paper section 4.2."""
        hdf5_run = data.IorSummaryData(os.path.join(self.ior_dir, "hdf5", "ior-report.csv"))
        adios_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "adios", "lsm-report.csv"))
        lsmio_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv"))
        fn = self._gen_png_name("lsmio", True, 4, "64K")
        md = plot.PlotMetaData("HDF5 vs. ADIOS vs. LSMIO", "# of Nodes", "Max BW in MB")

        x_series, y_series = hdf5_run.time_series(True, 4, "64K")
        pda = plot.PlotData("hdf5-4-64k", x_series, y_series)
        x_series, y_series = adios_run.time_series(True, 4, "64K")
        pdb = plot.PlotData("adios-4-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(True, 4, "64K")
        pdc = plot.PlotData("lsmio-4-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper43(self) -> None:
        """Generate write performance plot for paper section 4.3."""
        adios_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "adios", "lsm-report.csv"))
        lsmio_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv"))
        plugin_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv"))
        fn = self._gen_png_name("lsmio", False, 4, "64K")
        md = plot.PlotMetaData("ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB")

        x_series, y_series = adios_run.time_series(False, 4, "64K")
        pda = plot.PlotData("adios-4-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(False, 4, "64K")
        pdb = plot.PlotData("lsmio-4-64k", x_series, y_series)
        x_series, y_series = plugin_run.time_series(False, 4, "64K")
        pdc = plot.PlotData("plugin-4-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper44(self) -> None:
        """Generate read performance plot for paper section 4.4."""
        adios_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "adios", "lsm-report.csv"))
        lsmio_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv"))
        plugin_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv"))
        fn = self._gen_png_name("lsmio", True, 16, "64K")
        md = plot.PlotMetaData("ADIOS vs. LSMIO vs. PLUGIN", "# of Nodes", "Max BW in MB")

        x_series, y_series = adios_run.time_series(True, 16, "64K")
        pda = plot.PlotData("adios-16-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(True, 16, "64K")
        pdb = plot.PlotData("lsmio-16-64k", x_series, y_series)
        x_series, y_series = plugin_run.time_series(True, 16, "64K")
        pdc = plot.PlotData("plugin-16-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper45(self) -> None:
        """Generate write performance plot for paper section 4.5."""
        ior_run = data.IorSummaryData(os.path.join(self.ior_dir, "ior-report.csv"))
        collective_run = data.IorSummaryData(os.path.join(self.ior_dir, "collective", "ior-report.csv"))
        hdf5_run = data.IorSummaryData(os.path.join(self.ior_dir, "hdf5", "ior-report.csv"))
        hdf5_collective_run = data.IorSummaryData(os.path.join(self.ior_dir, "hdf5-collective", "ior-report.csv"))
        lsmio_run = data.LsmioSummaryData(os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv"))
        fn = self._gen_png_name("lsmio", False, 4, "64K")
        md = plot.PlotMetaData("IOR vs. IOR-C vs. HDF5 vs. HDF5-C vs. LSMIO", "# of Nodes", "Max BW in MB")

        x_series, y_series = ior_run.time_series(False, 4, "64K")
        pda = plot.PlotData("ior-4-64k", x_series, y_series)
        x_series, y_series = collective_run.time_series(False, 4, "64K")
        pdb = plot.PlotData("ior-collective-4-64k", x_series, y_series)
        x_series, y_series = hdf5_run.time_series(False, 4, "64K")
        pdc = plot.PlotData("hdf5-4-64k", x_series, y_series)
        x_series, y_series = hdf5_collective_run.time_series(False, 4, "64K")
        pdd = plot.PlotData("hdf5-collective-4-64k", x_series, y_series)
        x_series, y_series = lsmio_run.time_series(False, 4, "64K")
        pde = plot.PlotData("lsmio-4-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper46(self) -> None:
        """Generate read performance plot for paper section 4.6."""
        # Load data from different I/O methods
        ior_run = data.IorSummaryData(os.path.join(self.ior_dir, "ior-report.csv"))
        collective_run = data.IorSummaryData(
            os.path.join(self.ior_dir, "collective", "ior-report.csv")
        )
        hdf5_run = data.IorSummaryData(
            os.path.join(self.ior_dir, "hdf5", "ior-report.csv")
        )
        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )

        fn = self._gen_png_name("comparison", True, 4, "64K")
        md = plot.PlotMetaData(
            "I/O Method Comparison (Read)",
            "# of Nodes",
            "Max BW in MB"
        )

        # Get data series for each method
        x_series, y_series = ior_run.time_series(True, 4, "64K")
        pda = plot.PlotData("ior-base-4-64k", x_series, y_series)

        x_series, y_series = collective_run.time_series(True, 4, "64K")
        pdb = plot.PlotData("ior-collective-4-64k", x_series, y_series)

        x_series, y_series = hdf5_run.time_series(True, 4, "64K")
        pdc = plot.PlotData("hdf5-4-64k", x_series, y_series)

        x_series, y_series = adios_run.time_series(True, 4, "64K")
        pdd = plot.PlotData("adios-4-64k", x_series, y_series)

        x_series, y_series = lsmio_run.time_series(True, 4, "64K")
        pde = plot.PlotData("lsmio-4-64k", x_series, y_series)

        x_series, y_series = plugin_run.time_series(True, 4, "64K")
        pdf = plot.PlotData("plugin-4-64k", x_series, y_series)

        p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper91(self) -> None:
        """Generate plot for paper section 9.1 (comparison plots)."""
        # Load data from different I/O methods
        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )

        # Generate comparison plots for 64K and 1M block sizes
        fn = self._gen_png_name("comparison", False, 4, "64K")
        md = plot.PlotMetaData(
            "ADIOS vs. LSMIO vs. PLUGIN Comparison",
            "# of Nodes",
            "Relative Performance"
        )

        # 64K comparisons
        ax_series, ay_series = adios_run.time_series(False, 4, "64K")
        px_series, py_series = plugin_run.time_series(False, 4, "64K")
        lx_series, ly_series = lsmio_run.time_series(False, 4, "64K")

        # Calculate relative performance ratios
        pda = plot.PlotData(
            "plugin/adios-4-64k",
            ax_series,
            np.array(py_series) / np.array(ay_series)
        )
        pdb = plot.PlotData(
            "lsmio/adios-4-64k",
            ax_series,
            np.array(ly_series) / np.array(ay_series)
        )
        pdc = plot.PlotData(
            "lsmio/plugin-4-64k",
            ax_series,
            np.array(ly_series) / np.array(py_series)
        )

        # 1M comparisons
        ax_series, ay_series = adios_run.time_series(False, 16, "1M")
        px_series, py_series = plugin_run.time_series(False, 16, "1M")
        lx_series, ly_series = lsmio_run.time_series(False, 16, "1M")

        # Calculate relative performance ratios
        pdd = plot.PlotData(
            "plugin/adios-16-1M",
            ax_series,
            np.array(py_series) / np.array(ay_series)
        )
        pde = plot.PlotData(
            "lsmio/adios-16-1M",
            ax_series,
            np.array(ly_series) / np.array(ay_series)
        )
        pdf = plot.PlotData(
            "lsmio/plugin-16-1M",
            ax_series,
            np.array(ly_series) / np.array(py_series)
        )

        # Create multi-plot and save to file
        p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper92(self) -> None:
        """Generate read performance comparison plots for paper section 9.2."""
        # Load data from different I/O methods
        adios_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "adios", "lsm-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )
        plugin_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "plugin", "lsm-report.csv")
        )

        # Generate comparison plots for read performance
        fn = self._gen_png_name("read-comparison", True, 4, "64K")
        md = plot.PlotMetaData(
            "Read Performance Comparison",
            "# of Nodes",
            "Max BW in MB"
        )

        # Get data series for each method
        x_series, y_series = adios_run.time_series(True, 4, "64K")
        pda = plot.PlotData("adios-4-64k", x_series, y_series)

        x_series, y_series = lsmio_run.time_series(True, 4, "64K")
        pdb = plot.PlotData("lsmio-4-64k", x_series, y_series)

        x_series, y_series = plugin_run.time_series(True, 4, "64K")
        pdc = plot.PlotData("plugin-4-64k", x_series, y_series)

        # Create multi-plot and save to file
        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper93(self) -> None:
        """Generate I/O method comparison plots for paper section 9.3."""
        # Load data from different I/O methods
        ior_run = data.IorSummaryData(
            os.path.join(self.ior_dir, "ior-report.csv")
        )
        hdf5_run = data.IorSummaryData(
            os.path.join(self.ior_dir, "hdf5", "ior-report.csv")
        )
        lsmio_run = data.LsmioSummaryData(
            os.path.join(self.lsmio_dir, "lsmio", "lsm-report.csv")
        )

        # Generate comparison plots
        fn = self._gen_png_name("method-comparison", False, 4, "64K")
        md = plot.PlotMetaData(
            "I/O Method Performance Comparison",
            "# of Nodes",
            "Max BW in MB"
        )

        # Get data series for each method
        x_series, y_series = ior_run.time_series(False, 4, "64K")
        pda = plot.PlotData("ior-4-64k", x_series, y_series)

        x_series, y_series = hdf5_run.time_series(False, 4, "64K")
        pdb = plot.PlotData("hdf5-4-64k", x_series, y_series)

        x_series, y_series = lsmio_run.time_series(False, 4, "64K")
        pdc = plot.PlotData("lsmio-4-64k", x_series, y_series)

        # Create multi-plot and save to file
        p = plot.MultiPlot(md, pda, pdb, pdc)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run_step_paper95(self) -> None:
        """Generate IOR comparison plots for paper section 9.5."""
        # Load data from IOR base and collective runs
        ior_run = data.IorSummaryData(
            os.path.join(self.ior_dir, "ior-report.csv")
        )
        collective_run = data.IorSummaryData(
            os.path.join(self.ior_dir, "collective", "ior-report.csv")
        )

        # Generate comparison plots
        fn = self._gen_png_name("ior-comparison", False, 4, "64K")
        md = plot.PlotMetaData(
            "IOR Base vs. Collective Comparison",
            "# of Nodes",
            "Max BW in MB"
        )

        # Get data series for read and write operations
        x_series, y_series = ior_run.time_series(False, 4, "64K")
        pda = plot.PlotData("ior-write-4-64k", x_series, y_series)

        x_series, y_series = ior_run.time_series(True, 4, "64K")
        pdb = plot.PlotData("ior-read-4-64k", x_series, y_series)

        x_series, y_series = collective_run.time_series(False, 4, "64K")
        pdc = plot.PlotData("ior-collective-write-4-64k", x_series, y_series)

        x_series, y_series = collective_run.time_series(True, 4, "64K")
        pdd = plot.PlotData("ior-collective-read-4-64k", x_series, y_series)

        # Create multi-plot and save to file
        p = plot.MultiPlot(md, pda, pdb, pdc, pdd)
        p.plot(self._gen_png_path(fn))
        log.Console.debug(f"Image generated: {fn}.")

    def run(self) -> None:
        """Generate all paper plots for the selected HPC environment."""
        print(f"Generating images for the environment: {self.hpc}.")
        self.run_step_paper41()
        self.run_step_paper42()
        self.run_step_paper43()
        self.run_step_paper44()
        self.run_step_paper45()
        self.run_step_paper46()
        self.run_step_paper91()
        self.run_step_paper92()
