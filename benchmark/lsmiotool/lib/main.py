import os, sys, signal, importlib

from lsmiotool import settings
from lsmiotool.lib import env, log, debuggable, plot

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


class LatexMain(BaseMain):

  def demoRunDummy(self):
    from lsmiotool.lib import plot
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
    from lsmiotool.lib import plot, data
    iorRun = data.IorData('/home/sbulut/src/archive.ISAMBARD/ior-base/outputs/ior-report.csv')
    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '64K')
    fn = 'ior-write-4-64k.png'
    md = plot.PlotMetaData("IOR Data", "# of Nodes", "Max BW in MB")
    pd = plot.PlotData('ior-base-4-64k', xSeries, ySeries)
    p = plot.Plot(md, pd)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  def demoRunMulti(self):
    from lsmiotool.lib import plot, data
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
