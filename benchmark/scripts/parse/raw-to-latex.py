#!/usr/bin/python3

import sys
import getopt
import csv

IOR_HEADER = "Concurrency,Replication,Block Size,Operation,Max(MiB),Min(MiB),Mean(MiB),StdDev,Max(OPs),Min(OPs),Mean(OPs),StdDev,Mean(s),Stonewall(s),Stonewall(MiB),Test#,#Tasks,tPN,reps,fPP,reord,reordoff,reordrand,seed,segcnt,blksiz,xsize,aggs(MiB),API,RefNum"
LSM_HEADER = "Concurrency,Replication,Block size,Access,Max (MiBs),Min (MiB/s),Mean (MiB/s),Total (MiB),Total (Ops),Iterations"

HELP_TEXT = "-t <ior|lsmio> -i <inputfile> -o <outputfile>"

def parse(csv_type, input_file, output_file):
  rows = []
  with open(input_file, newline='') as csvfile:
    csv_reader = csv.reader(csvfile, delimiter=',')
    for row in csv_reader:
      rows.append(row)

  # 32,4,8M,read,9536.39,3869.41
  rows_sorted_a = sorted(rows, key=lambda x: int(x[0]), reverse=False)
  rows_sorted_b = sorted(rows_sorted_a, key=lambda x: int(x[1]), reverse=False)
  rows_sorted_c = sorted(rows_sorted_b, key=lambda x: x[2], reverse=False)
  rows_sorted_d = sorted(rows_sorted_c, key=lambda x: x[3], reverse=False)

  with open(output_file, 'w', newline='') as csvfile:
    csvfile.write(IOR_HEADER + "\n")
    csv_writer = csv.writer(csvfile, delimiter=',', quoting=csv.QUOTE_MINIMAL)
    for row in rows_sorted_d:
      csv_writer.writerow(row)
      print(', '.join(row))


if __name__ == "__main__":
  inputfile = ''
  outputfile = ''
  csvtype = 'ior'

  try:
    opts, args = getopt.getopt(sys.argv[1:],"hi:o:t:",["ifile=","ofile=","type="])
  except getopt.GetoptError:
    print(sys.argv[0] + " " + HELP_TEXT)
    sys.exit(2)

  for opt, arg in opts:
    if opt == '-h':
      print(sys.argv[0] + " " + HELP_TEXT)
      sys.exit(1)
    elif opt in ("-i", "--ifile"):
      inputfile = arg
    elif opt in ("-o", "--ofile"):
      outputfile = arg
    elif opt in ("-t", "--type"):
      csvtype = arg

  print('Input file: "', inputfile)
  print('Output file: "', outputfile)

  if inputfile == '' or outputfile == '':
    print(sys.argv[0] + " " + HELP_TEXT)
    sys.exit(3)

  parse(csvtype, inputfile, outputfile)

