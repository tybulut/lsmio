import numpy as np
from matplotlib import pyplot

class PlotMetaData(object):
  def __init__(self, title, xLabel, yLabel):
    self.title = title
    self.xLabel = xLabel
    self.yLabel = yLabel


class PlotData(object):
  def __init__(self, xSeries, ySeries):
    self.xSeries = np.array(xSeries)
    self.ySeries = np.array(ySeries)


class Plot(object):
  def __init__(self, metaData, plotData):
    self.metaData = metaData
    self.plotData = plotData

  def plot(self, fileName):
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


