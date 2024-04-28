import csv


class IorData(object):
  def __init__(self, fileName):
    self.fileName = fileName
    self.iorData = {
      # operation -> numStripes -> stripeSize -> numNodes
    }
    # 1,16,8M,read,5353.38,5160.61,5293.08,49.88,66...
    # N,Stripes,BlockSize,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,...
    with open(fileName, newline='') as csvfile:
      csvReader = csv.reader(csvfile, delimiter=',', quotechar='|')
      for row in csvReader:
        operation = row[3]
        if operation not in self.iorData:
          self.iorData[operation] = {}
        numStripes = int(row[1])
        if numStripes not in self.iorData[operation]:
          self.iorData[operation][numStripes] = {}
        stripeSize = row[2]
        if stripeSize not in self.iorData[operation][numStripes]:
          self.iorData[operation][numStripes][stripeSize] = {}
        numNodes = int(row[0])
        if numNodes not in self.iorData[operation][numStripes][stripeSize]:
          self.iorData[operation][numStripes][stripeSize][numNodes] = {}
        partData = {
          'maxMB': float(row[4]),
          'minMB': float(row[5]),
          'meanMB': float(row[6]),
        }
        self.iorData[operation][numStripes][stripeSize][numNodes] = partData

  def timeSeries(self, isRead: bool, numStripes: int, stripeSize: str):
    operation = 'read' if isRead == True else 'write'
    partData = self.iorData[operation][numStripes][stripeSize]
    xSeries = []
    ySeries = []
    for node in sorted(partData):
      xSeries.append(node)
      ySeries.append(partData[node]['maxMB'])
    return (xSeries, ySeries)
