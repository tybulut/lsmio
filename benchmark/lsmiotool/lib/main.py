import os, sys, signal, importlib
import numpy as np

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

  def __init__(self):
    super(LatexMain, self).__init__()
    self._resultsFromViking()
    #self._resultsFromIsambard()

  def _resultsFromViking(self):
    self.ior_dir = env.VIKING_IOR_DIR
    self.ior_data = env.VIKING_IOR_DATA
    self.lsmio_dir = env.VIKING_LSMIO_DIR
    self.lsmio_data = env.VIKING_LSMIO_DATA
    self.plots_dir = env.VIKING_PLOTS_DIR

  def _resultsFromIsambard(self):
    self.ior_dir = env.ISAMBARD_XCI_IOR_DIR
    self.ior_data = env.ISAMBARD_XCI_IOR_DATA
    self.lsmio_dir = env.ISAMBARD_XCI_LSMIO_DIR
    self.lsmio_data = env.ISAMBARD_XCI_LSMIO_DATA
    self.plots_dir = env.ISAMBARD_XCI_PLOTS_DIR

  def _genPNGName(self, title: str, isRead: bool, numStripes: int, stripeSize: str) -> str:
    operation = 'read' if isRead == True else 'write'
    fileName = title + '-' + operation + '-' + str(numStripes) + '-' + stripeSize + '.png'
    return fileName

  def _genPNGPath(self, fileName: str) -> str:
    return os.path.join(self.plots_dir, fileName)

  """
  41: write
  IOR 4/64K + 4/1M
  LSMIO 4/64K + 4/1M
  IOR 16/64K + 16/1M
  LSMIO 16/64K + 16/1M
  """
  def runVikingPaper41(self):
    dataFileList = [self.ior_data['base'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading IOR CSV file: ' + dataFile + '.')
    iorRun = data.IorData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('41-comparison-write-base.png')
    md = plot.PlotMetaData("IOR vs. LSMIO", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '64K')
    pda = plot.PlotData('ior-base-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '1M')
    pdb = plot.PlotData('ior-base-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '64K')
    pdc = plot.PlotData('lsmio-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '1M')
    pdd = plot.PlotData('lsmio-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = iorRun.timeSeries(False, 16, '64K')
    pde = plot.PlotData('ior-base-16-64K', xSeries, ySeries)
    (xSeries, ySeries) = iorRun.timeSeries(False, 16, '1M')
    pdf = plot.PlotData('ior-base-16-1M', xSeries, ySeries)

    (xSeries, ySeries) = lsmioRun.timeSeries(False, 16, '64K')
    pdg = plot.PlotData('lsmio-16-64K', xSeries, ySeries)
    (xSeries, ySeries) = lsmioRun.timeSeries(False, 16, '1M')
    pdh = plot.PlotData('lsmio-16-1M', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf, pdg, pdh)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  """
  42: write
  HDF5 4/64K + 4/1M
  ADIOS 4/64K + 4/1M
  LSMIO 4/64K + 4/1M
  """
  def runVikingPaper42(self):
    dataFileList = [self.ior_data['hdf5'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading IOR CSV file: ' + dataFile + '.')
    hdf5Run = data.IorData(dataFile)

    dataFileList = [self.lsmio_data['adios'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading ADIOS CSV file: ' + dataFile + '.')
    adiosRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('42-comparison-write-lsmio.png')
    md = plot.PlotMetaData("HDF5 vs. ADIOS vs. LSMIO", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = hdf5Run.timeSeries(False, 4, '64K')
    pda = plot.PlotData('ior-hdf5-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = hdf5Run.timeSeries(False, 4, '1M')
    pdb = plot.PlotData('ior-hdf5-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = adiosRun.timeSeries(False, 4, '64K')
    pdc = plot.PlotData('adios-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = adiosRun.timeSeries(False, 4, '1M')
    pdd = plot.PlotData('adios-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '64K')
    pde = plot.PlotData('lsmio-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '1M')
    pdf = plot.PlotData('lsmio-4-1M', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  """
  43: write
  ADIOS 4/64K + 4/1M
  LSMIO 4/64K + 4/1M
  PLUGIN 4/64K + 4/1M
  """
  def runVikingPaper43(self):
    dataFileList = [self.lsmio_data['adios'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading ADIOS CSV file: ' + dataFile + '.')
    adiosRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['plugin'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading PLUGIN CSV file: ' + dataFile + '.')
    pluginRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('43-comparison-write-plugin-4.png')
    md = plot.PlotMetaData("ADIOS vs. LSMIO", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = adiosRun.timeSeries(False, 4, '64K')
    pda = plot.PlotData('adios-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = adiosRun.timeSeries(False, 4, '1M')
    pdb = plot.PlotData('adios-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '64K')
    pdc = plot.PlotData('lsmio-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '1M')
    pdd = plot.PlotData('lsmio-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = pluginRun.timeSeries(False, 4, '64K')
    pde = plot.PlotData('plugin-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = pluginRun.timeSeries(False, 4, '1M')
    pdf = plot.PlotData('plugin-4-1M', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  """
  44: write
  ADIOS 4/64K + 16/64K
  LSMIO 4/64K + 16/64K
  PLUGIN 4/64K + 16/64K
  """
  def runVikingPaper44(self):
    dataFileList = [self.lsmio_data['adios'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading ADIOS CSV file: ' + dataFile + '.')
    adiosRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['plugin'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading PLUGIN CSV file: ' + dataFile + '.')
    pluginRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('44-comparison-write-plugin-16.png')
    md = plot.PlotMetaData("ADIOS vs. LSMIO", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = adiosRun.timeSeries(False, 4, '64K')
    pda = plot.PlotData('adios-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = adiosRun.timeSeries(False, 16, '64K')
    pdb = plot.PlotData('adios-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '64K')
    pdc = plot.PlotData('lsmio-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = lsmioRun.timeSeries(False, 16, '64K')
    pdd = plot.PlotData('lsmio-4-1M', xSeries, ySeries)

    (xSeries, ySeries) = pluginRun.timeSeries(False, 4, '64K')
    pde = plot.PlotData('plugin-4-64K', xSeries, ySeries)
    (xSeries, ySeries) = pluginRun.timeSeries(False, 16, '64K')
    pdf = plot.PlotData('plugin-4-1M', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  """
  45: write
  IOR 4/64K
  IOR-C 4/64K
  HDF5 4/64K
  HDF5-C 4/64K
  LSMIO 4/64K
  """
  def runVikingPaper45(self):
    dataFileList = [self.ior_data['base'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading IOR CSV file: ' + dataFile + '.')
    iorRun = data.IorData(dataFile)

    dataFileList = [self.ior_data['collective'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading IOR-collective CSV file: ' + dataFile + '.')
    collectiveRun = data.IorData(dataFile)

    dataFileList = [self.ior_data['hdf5'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading HDF5 CSV file: ' + dataFile + '.')
    hdf5Run = data.IorData(dataFile)

    dataFileList = [self.ior_data['hdf5-collective'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading HDF5-collective CSV file: ' + dataFile + '.')
    hdf5cRun = data.IorData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('45-comparison-collective.png')
    md = plot.PlotMetaData("IOR vs. LSMIO", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = iorRun.timeSeries(False, 4, '64K')
    pda = plot.PlotData('ior-base-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = collectiveRun.timeSeries(False, 4, '64K')
    pdb = plot.PlotData('ior-collective-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = hdf5Run.timeSeries(False, 4, '64K')
    pdc = plot.PlotData('ior-hdf5-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = hdf5cRun.timeSeries(False, 4, '64K')
    pdd = plot.PlotData('ior-hdf5-c-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = lsmioRun.timeSeries(False, 4, '64K')
    pde = plot.PlotData('lsmio-4-64K', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')

  """
  46: read
  IOR 4/64K
  IOR-C 4/64K
  HDF5 4/64K
  ADIOS 4/64K
  LSMIO 4/64K
  PLUGIN 4/64K
  """
  def runVikingPaper46(self):
    dataFileList = [self.ior_data['base'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading IOR CSV file: ' + dataFile + '.')
    iorRun = data.IorData(dataFile)

    dataFileList = [self.ior_data['collective'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading IOR-collective CSV file: ' + dataFile + '.')
    collectiveRun = data.IorData(dataFile)

    dataFileList = [self.ior_data['hdf5'], 'ior-report.csv']
    dataFile = os.path.join(self.ior_dir, *dataFileList)
    log.Console.error('Reading HDF5 CSV file: ' + dataFile + '.')
    hdf5Run = data.IorData(dataFile)

    dataFileList = [self.lsmio_data['adios'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading ADIOS CSV file: ' + dataFile + '.')
    adiosRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['plugin'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading PLUGIN CSV file: ' + dataFile + '.')
    pluginRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('46-comparison-read-base.png')
    md = plot.PlotMetaData("IOR vs. LSMIO", "# of Nodes", "Max BW in MB")

    (xSeries, ySeries) = iorRun.timeSeries(True, 4, '64K')
    pda = plot.PlotData('ior-base-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = collectiveRun.timeSeries(True, 4, '64K')
    pdb = plot.PlotData('ior-collective-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = hdf5Run.timeSeries(True, 4, '64K')
    pdc = plot.PlotData('ior-hdf5-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = adiosRun.timeSeries(True, 4, '64K')
    pdd = plot.PlotData('adios-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = lsmioRun.timeSeries(True, 4, '64K')
    pde = plot.PlotData('lsmio-4-64K', xSeries, ySeries)

    (xSeries, ySeries) = pluginRun.timeSeries(True, 4, '64K')
    pdf = plot.PlotData('plugin-4-64K', xSeries, ySeries)

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')


  """
  Write/64K, Write/1M
  adios/plugin
  adios/lsmio
  lsmio/plugin
  """
  def runVikingPaper91(self):
    dataFileList = [self.lsmio_data['adios'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading ADIOS CSV file: ' + dataFile + '.')
    adiosRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['plugin'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading PLUGIN CSV file: ' + dataFile + '.')
    pluginRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('91-comparison-adios-plugin-lsmio.png')
    md = plot.PlotMetaData("Write: ADIOS vs. PLUGIN vs. LSMIO", "# of Nodes", "Max BW in MB")

    (AxSeries, AySeries) = adiosRun.timeSeries(False, 4, '64K')
    (PxSeries, PySeries) = pluginRun.timeSeries(False, 4, '64K')
    (LxSeries, LySeries) = lsmioRun.timeSeries(False, 4, '64K')
    pda = plot.PlotData('plugin-adios-4-64K',
                        AxSeries, np.array(PySeries) / np.array(AySeries))
    pdb = plot.PlotData('lsmio-adios-4-64K',
                        AxSeries, np.array(LySeries) / np.array(AySeries))
    pdc = plot.PlotData('lsmio-plugin-4-64K',
                        AxSeries, np.array(LySeries) / np.array(PySeries))

    (AxSeries, AySeries) = adiosRun.timeSeries(False, 16, '1M')
    (PxSeries, PySeries) = pluginRun.timeSeries(False, 16, '1M')
    (LxSeries, LySeries) = lsmioRun.timeSeries(False, 16, '1M')
    pdd = plot.PlotData('plugin-adios-16-1M',
                        AxSeries, np.array(PySeries) / np.array(AySeries))
    pde = plot.PlotData('lsmio-adios-16-1M',
                        AxSeries, np.array(LySeries) / np.array(AySeries))
    pdf = plot.PlotData('lsmio-plugin-16-1M',
                        AxSeries, np.array(LySeries) / np.array(PySeries))

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')


  """
  Read/64K, Reae/1M
  adios/plugin
  adios/lsmio
  lsmio/plugin
  """
  def runVikingPaper92(self):
    dataFileList = [self.lsmio_data['adios'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading ADIOS CSV file: ' + dataFile + '.')
    adiosRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['lsmio'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading LSMIO CSV file: ' + dataFile + '.')
    lsmioRun = data.LsmioData(dataFile)

    dataFileList = [self.lsmio_data['plugin'], 'lsm-report.csv']
    dataFile = os.path.join(self.lsmio_dir, *dataFileList)
    log.Console.error('Reading PLUGIN CSV file: ' + dataFile + '.')
    pluginRun = data.LsmioData(dataFile)

    fn = self._genPNGPath('92-comparison-adios-plugin-lsmio.png')
    md = plot.PlotMetaData("Read: ADIOS vs. PLUGIN vs. LSMIO", "# of Nodes", "Max BW in MB")

    (AxSeries, AySeries) = adiosRun.timeSeries(True, 4, '64K')
    (PxSeries, PySeries) = pluginRun.timeSeries(True, 4, '64K')
    (LxSeries, LySeries) = lsmioRun.timeSeries(True, 4, '64K')
    pda = plot.PlotData('plugin-adios-4-64K',
                        AxSeries, np.array(PySeries) / np.array(AySeries))
    pdb = plot.PlotData('lsmio-adios-4-64K',
                        AxSeries, np.array(LySeries) / np.array(AySeries))
    pdc = plot.PlotData('lsmio-plugin-4-64K',
                        AxSeries, np.array(LySeries) / np.array(PySeries))

    (AxSeries, AySeries) = adiosRun.timeSeries(True, 16, '1M')
    (PxSeries, PySeries) = pluginRun.timeSeries(True, 16, '1M')
    (LxSeries, LySeries) = lsmioRun.timeSeries(True, 16, '1M')
    pdd = plot.PlotData('plugin-adios-16-1M',
                        AxSeries, np.array(PySeries) / np.array(AySeries))
    pde = plot.PlotData('lsmio-adios-16-1M',
                        AxSeries, np.array(LySeries) / np.array(AySeries))
    pdf = plot.PlotData('lsmio-plugin-16-1M',
                        AxSeries, np.array(LySeries) / np.array(PySeries))

    p = plot.MultiPlot(md, pda, pdb, pdc, pdd, pde, pdf)
    p.plot(fn)
    log.Console.error('Image generated: ' + fn + '.')


  """
  Read/64K, Write/64K, Write/1M
  lsmio/ior
  lsmio/hdf5
  ior/hdf5
  """
  def runVikingPaper93(self):
    pass

  """
  Read/64K, Write/64K, Write/1M
  ior/ior-c
  """
  def runVikingPaper95(self):
    pass

  def run(self):
    self.runVikingPaper41()
    self.runVikingPaper42()
    self.runVikingPaper43()
    self.runVikingPaper44()
    self.runVikingPaper45()
    self.runVikingPaper46()
    self.runVikingPaper91()
    self.runVikingPaper92()


