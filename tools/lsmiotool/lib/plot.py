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

import numpy as np
from typing import List, Union, Any
from numpy.typing import NDArray
from matplotlib import pyplot

class PlotMetaData(object):
    def __init__(self, title: str, xLabel: str, yLabel: str) -> None:
        self.title: str = title
        self.xLabel: str = xLabel
        self.yLabel: str = yLabel


class PlotData(object):
    def __init__(self, legend: str, xSeries: List[Union[int, str]], ySeries: List[float]) -> None:
        self.legend: str = legend
        self.xSeries: NDArray[Any] = np.array(xSeries)
        self.ySeries: NDArray[np.float64] = np.array(ySeries)


class Plot(object):
    def __init__(self, metaData: PlotMetaData, plotData: PlotData) -> None:
        self.metaData: PlotMetaData = metaData
        self.plotData: PlotData = plotData

    def plot(self, fileName: str) -> None:
        # Metadata
        pyplot.title(self.metaData.title)
        pyplot.xlabel(self.metaData.xLabel)
        pyplot.ylabel(self.metaData.yLabel)
        # Plotdata
        pyplot.plot(self.plotData.xSeries, self.plotData.ySeries)
        # Image
        pyplot.grid()
        pyplot.savefig(fileName)
        pyplot.close()


class MultiPlot(object):
    def __init__(self, metaData: PlotMetaData, *pdArgs: PlotData) -> None:
        self.metaData: PlotMetaData = metaData
        self.plotDataList: List[PlotData] = []
        for plotData in pdArgs:
            self.plotDataList.append(plotData)

    def plot(self, fileName: str) -> None:
        # Metadata
        pyplot.title(self.metaData.title)
        pyplot.xlabel(self.metaData.xLabel)
        pyplot.ylabel(self.metaData.yLabel)
        # Plotdata
        for plotData in self.plotDataList:
            pyplot.plot(plotData.xSeries, plotData.ySeries, label=plotData.legend)
        # Image
        pyplot.grid()
        pyplot.legend()
        pyplot.savefig(fileName)
        pyplot.close()
