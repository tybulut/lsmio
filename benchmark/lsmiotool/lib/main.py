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

  def run(self):
    from lsmiotool.lib import plot
    fn = 'plant.png'
    md = plot.PlotMetaData("Sports Watch Data", "Average Pulse", "Calorie Burnage")
    pd = plot.PlotData(
            [80, 85, 90, 95, 100, 105, 110, 115, 120, 125],
            [240, 250, 260, 270, 280, 290, 300, 310, 320, 330]
         )
    p = plot.Plot(md, pd)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')



