import os, sys, signal, importlib

from lsmiotool import settings
from lsmiotool.lib import env, log, debuggable, plot
from lsmiotool.lib import plot, data

# Catch CTRL-C
signal.signal(signal.SIGINT, signal.SIG_DFL)

class BaseMain(debuggable.DebuggableObject):

  def __init__(self):
    super(BaseMain, self).__init__()


class TestMain(BaseMain):

  def run(self):
    from lsmiotool import test
    test.run_and_report()


class ShellMain(BaseMain):

  def run(self):
    import code
    code.interact(local=dict(globals(), **locals()))


class NotImplemented(BaseMain):

  def run(self):
    log.Console.error('Not Implemented')
    sys.exit(1)


class DemoMain(BaseMain):

  def demoRunDummy(self):
    fn = 'demo.png'
    md = plot.PlotMetaData("Sports Watch Data", "Average Pulse", "Calorie Burnage")
    pd = plot.PlotData(
            [80, 85, 90, 95, 100, 105, 110, 115, 120, 125],
            [240, 250, 260, 270, 280, 290, 300, 310, 320, 330]
         )
    p = plot.Plot(md, pd)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  def demoRunSingle(self):
    iorRun = data.IorData('/home/sbulut/src/archive.ISAMBARD/ior-base/outputs/ior-report.csv')
    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '64K')
    fn = 'ior-write-4-64k.png'
    md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")
    pd = plot.PlotData('ior-base-4-64k', xSeries, ySeries)
    p = plot.Plot(md, pd)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  def demoRunMulti(self):
    iorRun = data.IorData('/home/sbulut/src/archive.ISAMBARD/ior-base/outputs/ior-report.csv')
    fn = 'ior-write-64k.png'
    md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '64K')
    pda = plot.PlotData('ior-base-4-64k', xSeries, ySeries)
    (xSeries, ySeries) = iorRun.timeSeries(False, 16, '64K')
    pdb = plot.PlotData('ior-base-16-64k', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  def run(self):
    return self.demoRunMulti()


class LatexMain(BaseMain):

  """

42: write
HDF5 4/64K + 4/1M
ADIOS 4/64K + 4/1M
LSMIO 4/64K + 4/1M

43: write
ADIOS 4/64K + 4/1M
LSMIO 4/64K + 4/1M
PLUGIN 4/64K + 4/1M

44: write
ADIOS 4/64K + 16/64K
LSMIO 4/64K + 16/64K
PLUGIN 4/64K + 16/64K

45: write
IOR 4/64K
IOR-C 4/64K
HDF5 4/64K
HDF5-C 4/64K
LSMIO 4/64K

46: read
IOR 4/64K
IOR-C 4/64K
HDF5 4/64K
ADIOS 4/64K
LSMIO 4/64K
PLUGIN 4/64K

Read/64K, Write/64K, Write/1M
ior/hdf5
ior/ior-c
adios/ior
adios/lsmio
lsmio/ior
lsmio/hdf5

  """

  def genPNGpath(self, title: str, isRead: bool, numStripes: int, stripeSize: str):
    operation = 'read' if isRead == True else 'write'
    fileName = title + '-' + operation + '-' + str(numStripes) + '-' + stripeSize + '.png'
    return fileName

  """
  41: write
  IOR 4/64K + 4/1M
  LSMIO 4/64K + 4/1M
  IOR 16/64K + 16/1M
  LSMIO 16/64K + 16/1M
  """
  def runVikingPaper41(self):
    dataFileList = [env.VIKING_IOR_DATA['base'], 'ior-report.txt']
    dataFile = os.path.join(env.VIKING_IOR_DIR, *dataFileList)
    iorRun = data.IorData(dataFile)

    fn = '41-comparison-write-base.png'
    md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '64K')
    pda = plot.PlotData('ior-base-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '1M')
    pdb = plot.PlotData('ior-base-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = iorRun.timeSeries(False, 16, '64K')
    pdc = plot.PlotData('ior-base-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = iorRun.timeSeries(False, 16, '1M')
    pdd = plot.PlotData('ior-base-4-1M', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')


  def run(self):
    return self.runVikingPaper41()


