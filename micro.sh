#!/bin/bash

# Default values
ITER=5
BM_DIR="$HOME/benchmark"
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

mkdir -p "${BM_DIR}"

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
    ~/src/usr/bin/bm_adios -o ${BM_DIR}/lsmio-adios.db \
        -v -g -i "$ITER" \
        --lsmio-ts 1024 --lsmio-bs 1024 \
        --value-size 262140 --key-count 2048
fi

if [ "$RUN_PLUGIN" = true ]; then
    echo "Running ADIOS Plugin benchmark..."
    ~/src/usr/bin/bm_adios -o ${BM_DIR}/lsmio-adios-plugin.db \
        -v -g -i "$ITER" \
        --lsmio-ts 1024 --lsmio-bs 1024 \
        --value-size 262140 --key-count 2048
fi

if [ "$RUN_ROCKSDB" = true ]; then
    echo "Running RocksDB benchmark..."
    ~/src/usr/bin/bm_rocksdb -o ${BM_DIR}/lsmio-rocksdb.db \
        -v -g -i "$ITER" \
        --lsmio-ts 1024 --lsmio-bs 1024 \
        --value-size 262140 --key-count 2048
fi

if [ "$RUN_LEVELDB" = true ]; then
    echo "Running LevelDB benchmark..."
    ~/src/usr/bin/bm_leveldb -o ${BM_DIR}/lsmio-leveldb.db \
        -v -g -i "$ITER" \
        --lsmio-ts 1024 --lsmio-bs 1024 \
        --value-size 262140 --key-count 2048
fi

if [ "$RUN_NATIVE" = true ]; then
    echo "Running Native benchmark..."
    ~/src/usr/bin/bm_native -o ${BM_DIR}/lsmio-native.db \
        -v -g -i "$ITER" \
        --lsmio-ts 1024 --lsmio-bs 1024 \
        --value-size 262140 --key-count 2048
fi
