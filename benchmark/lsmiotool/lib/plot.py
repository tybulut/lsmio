import numpy as np
from matplotlib import pyplot

class PlotMetaData(object):
  def __init__(self, title: str, xLabel: str, yLabel: str):
    self.title = title
    self.xLabel = xLabel
    self.yLabel = yLabel


class PlotData(object):
  def __init__(self, legend: str, xSeries: list[int], ySeries: list[float]):
    self.legend = legend
    self.xSeries = np.array(xSeries)
    self.ySeries = np.array(ySeries)


class Plot(object):
  def __init__(self, metaData, plotData):
    self.metaData = metaData
    self.plotData = plotData

  def plot(self, fileName: str):
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
  def __init__(self, metaData, *pdArgs):
    self.metaData = metaData
    self.plotDataList = []
    for plotData in pdArgs:
      self.plotDataList.append(plotData)

  def plot(self, fileName: str):
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




