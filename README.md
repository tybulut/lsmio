# main/lsmio



## Getting Started

Download links:
```
SSH clone URL: git@github.com:tybulut/lsmio.git
HTTPS clone URL: https://github.com/tybulut/lsmio.git
```

These instructions will get you a copy of the project.


## Prerequisites: Linux/Debian

What packages to install and how to install them.

### OS:
```
DEBIAN-x86-64-12.4
```

### Packages:
```
build-essential
cmake autoconf automake gdb git
cpplint libgoogle-glog-dev
libgtest-dev googletest-tools googletest
libgmock-dev google-mock
libbz2-dev libpython3-dev libfmt-dev
libboost-program-options-dev libboost-filesystem-dev
libopenmpi-dev libmpich-dev mpi-default-dev libomp-dev 
openmpi-bin openmpi-common openmpi-doc mpi-default-dev
libhdf5-dev libhdf5-mpi-dev libhdf5-mpich-dev libhdf5-openmpi-dev
libkyotocabinet-dev kyotocabinet-utils
libsnappy-dev sqlite3 libsqlite3-dev
texlive-latex-base texlive-font-utils
texlive-latex-base  texlive-latex-extra texlive-science
libchart-gnuplot-perl libpng-dev
libpod-parser-perl libpod-latex-perl
```

### Optional Packages:
```
screen vim wget curl rdate rsync
```

### Other Dependencies:
Some versions are out-of-date on the current stable Debian. Hence
it is better for some of them to be installed fresh.
```
By default all the packages should be installed with the prefix: $HOME/src
- doc/dependencies/02-gtest
- doc/dependencies/11-darshan
- doc/dependencies/21-adios2
- doc/dependencies/22-leveldb
- doc/dependencies/23-rocksdb 
```

## Prerequisites: HPC

### OS:
```
Rocky Linux release 8
```

### Modules:
```
./benchmark/scripts/bm.sh load-modules
```

### Other dependencies:
Not all dependencies are available as modules on Viking cluster. Hence we need
to manually maintain the following dependencies.
```
By default all the packages will be installed with the prefix: $HOME/src
The packages that are listed in doc/dependencies/ directory have the installation 
instructions listed in their respective shell scripts.
In the same directory the dependencies starting with 9 are optional.
```


## Building 

Run build sript:
```
./build.sh <debug|release> [<test|install>]
```

This will create a build in one of the directories below depending on your choice:
```
./build/debug
./build/release
```


### Testing

After building, to Run the unit tests from the debug build:
```
cd build/debug
ctest -j8 ..  # to run 8 tests in parallel
```

After building, to run the unit tests from the release build:
```
cd build/release
ctest -j8 ..  # to run 8 tests in parallel
```

Alternatively you can build and test together
```
./build.sh <debug|release> test
```

Recommended mount options for testing on a local HDD:
```
mount -o noatime,nodiratime /dev/sda2 /media/400GB
```

## Deployment

Build script makes assumptions on where to install. 
```
./build.sh <debug|release> install
```

If you want to remove the previous files and then install a release version of it
```
./build.sh clean install
```

These instructions will get your copy of the project up and ready to use on your local
machine in $HOME/src prefix directory for development and testing purposes.

### Benchmarks

Set the environment variables
```
export SB_EMAIL="your email address"
export SB_ACCOUNT="your account ID for HPC credentails"
```

Benchmark script usage:
```
cd benchmark/scripts
./bm.sh  run <ior|lsmio|lmp> <local|bake|small|large> [<--ssd>]
./bm.sh  parse <ior|lsmio|lmp> <local|bake|small|large> [<--ssd>]
./bm.sh  load-modules
```

Run the IOR benchmarks for upto 48 parallel jobs:
```
cd benchmark/scripts
./bm.sh run ior small
```

Run the LSMIO benchmarks for upto 48 parallel jobs:
```
cd benchmark/scripts
./bm.sh run lsmio small
```

Parse the IOR benchmarks results for the latest run
```
cd benchmark/scripts
./bm.sh parse ior small
```

To clean the benchmark folder between runs and after parsing:
```
rm -rf $HOME/scratch/benchmark/data/*
rm -rf $HOME/scratch/benchmark/ior/*
rm -rf $HOME/scratch/benchmark/lsmio/*
```

## Using LSMIO in a Project

To include LSMIO in your package using a CMAKE project:
```
find_package(lsmio REQUIRED)
target_include_directories(... PUBLIC ${LSMIO_INCLUDE_DIRS})
target_link_libraries(... PUBLIC lsmio_store)
```
Substitute the ... with your target name.

A simple example is follows:
```
...
#include <lsmio/lsmio.hpp>
#include <lsmio/manager/manager.hpp>
...

...
  initLSMIORelease(argv[0]);

  lsmio::LSMIOManager lm("test_data", "/tmp/mydir");

  success = lm.put(key1, value1, true);
  success = lm.get(key1, &value);
...

```


## Resources

External resources for this project:
- Bug tracker: https://github.com/tybulut/lsmio/issues
- CI server: TBA

## How to reference

ACM format:
```
Serdar Bulut and Steven A. Wright. 2023. Optimizing Write Performance for Checkpointing to Parallel File Systems Using LSM-Trees. In Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis (SC-W '23). Association for Computing Machinery, New York, NY, USA, 492–501. https://doi.org/10.1145/3624062.3624118
```

BibTex format:
```
@inproceedings{10.1145/3624062.3624118,
author = {Bulut, Serdar and Wright, Steven A.},
title = {Optimizing Write Performance for Checkpointing to Parallel File Systems Using LSM-Trees},
year = {2023},
isbn = {9798400707858},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3624062.3624118},
doi = {10.1145/3624062.3624118},
abstract = {The widening gap between compute performance and I/O performance on modern HPC systems means that writing checkpoints to a parallel file system for fault tolerance is fast becoming a bottleneck to high-performance. It is therefore vital that software is engineered such that it can achieve the highest proportion of available performance on the underlying hardware; and this is a burden often carried by I/O middleware libraries. In this paper, we outline such an I/O library based on a Log-structured Merge Tree (LSM-Tree), not just for metadata, but also scientific data. We benchmark its performance using the IOR benchmark, demonstrating 2.4 to 76.7 \texttimes{} better performance than alternative file formats, such as ADIOS2, HDF5, and IOR baseline when running on a Lustre Parallel File System. We further demonstrate that when our LSM-Tree I/O library is used as a storage layer for ADIOS2, the resulting I/O library still outperforms the default ADIOS2 implementation by 1.5 \texttimes{}.},
booktitle = {Proceedings of the SC '23 Workshops of The International Conference on High Performance Computing, Network, Storage, and Analysis},
pages = {492–501},
numpages = {10},
keywords = {MPI, checkpointing, distributed storage, high performance computing, input/output},
location = {<conf-loc>, <city>Denver</city>, <state>CO</state>, <country>USA</country>, </conf-loc>},
series = {SC-W '23}
}
```


