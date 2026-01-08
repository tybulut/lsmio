#!/bin/bash

# Default values
ITER=5
BM_DIR="/media/400GB/benchmark"
RUN_ADIOS=false
RUN_PLUGIN=false
RUN_ROCKSDB=false
RUN_LEVELDB=false
RUN_NATIVE=false
TARGETS_SELECTED=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        adios)
            RUN_ADIOS=true
            TARGETS_SELECTED=true
            shift
            ;;
        plugin)
            RUN_PLUGIN=true
            TARGETS_SELECTED=true
            shift
            ;;
        rocksdb)
            RUN_ROCKSDB=true
            TARGETS_SELECTED=true
            shift
            ;;
        leveldb)
            RUN_LEVELDB=true
            TARGETS_SELECTED=true
            shift
            ;;
        native)
            RUN_NATIVE=true
            TARGETS_SELECTED=true
            shift
            ;;
        -i|--iterations)
            ITER="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [adios] [plugin] [rocksdb] [leveldb] [native] [-i iterations]"
            exit 1
            ;;
    esac
done

if [ "$TARGETS_SELECTED" = false ]; then
    echo "No benchmarks selected."
    echo "Usage: $0 [adios] [plugin] [rocksdb] [leveldb] [native] [-i iterations]"
    exit 1
fi

# Change to the build directory relative to the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

if [ ! -d "$BUILD_DIR" ]; then
    echo "Error: Build directory not found at $BUILD_DIR"
    exit 1
fi

cd "$BUILD_DIR" || exit 1

# Build and install once
make -j8 install || exit 1

if [ "$RUN_ADIOS" = true ]; then
    echo "Running ADIOS benchmark..."
    ~/src/usr/bin/bm_adios \
        --lsmio-ts 1024 --lsmio-bs 1024 --key-count 2048 -i "$ITER" \
        -v -g -o ${BM_DIR}/lsmio-adios.db
fi

if [ "$RUN_PLUGIN" = true ]; then
    echo "Running ADIOS Plugin benchmark..."
    ~/src/usr/bin/bm_adios \
        --lsmio-plugin \
        -v -g -o ${BM_DIR}/lsmio-adios-plugin.db \
        --lsmio-ts 1024 --lsmio-bs 1024 --key-count 2048 -i "$ITER"
fi

if [ "$RUN_ROCKSDB" = true ]; then
    echo "Running RocksDB benchmark..."
    ~/src/usr/bin/bm_rocksdb \
        -v -g -o ${BM_DIR}/lsmio-rocksdb-m.db \
        --lsmio-ts 1024 --lsmio-bs 1024 --key-count 2048 -i "$ITER"
#        --lsmio-batch-size 1 \
fi

if [ "$RUN_LEVELDB" = true ]; then
    echo "Running LevelDB benchmark..."
    ~/src/usr/bin/bm_leveldb \
        -v -g -o ${BM_DIR}/lsmio-leveldb-m.db \
        --lsmio-ts 1024 --lsmio-bs 1024 --key-count 2048 -i "$ITER"
#        --lsmio-batch-size 1 \
fi

if [ "$RUN_NATIVE" = true ]; then
    echo "Running Native benchmark..."
    ~/src/usr/bin/bm_native \
        -v -g -o ${BM_DIR}/lsmio-native-m.db \
        --lsmio-ts 1024 --lsmio-bs 1024 --key-count 2048 -i "$ITER"
fi
