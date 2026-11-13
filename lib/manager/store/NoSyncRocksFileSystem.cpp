/*
 * Copyright 2023 Serdar Bulut
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its
 *    contributors may be used to endorse or promote products derived from
 *    this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

#include "NoSyncRocksFileSystem.hpp"

#include <atomic>

#if LSMIO_ROCKSDB_NOSYNC_FS
#include <memory>
#include <string>
#include <utility>
#endif

namespace lsmio {

#if LSMIO_ROCKSDB_NOSYNC_FS

namespace {

std::atomic<std::uint64_t> g_intercepted_syncs{0};

void countIntercept() {
    g_intercepted_syncs.fetch_add(1, std::memory_order_relaxed);
}

// A writable file whose Sync/Fsync are a Flush and whose RangeSync is a no-op: the data has been
// handed to the OS, nothing is dropped and no fsync/fdatasync is issued (INV-17). It owns the
// file it wraps. No override throws: they only forward (RocksDB is not exception-safe).
class NoSyncWritableFile : public rocksdb::FSWritableFileOwnerWrapper {
  public:
    explicit NoSyncWritableFile(std::unique_ptr<rocksdb::FSWritableFile>&& f_target)
        : rocksdb::FSWritableFileOwnerWrapper(std::move(f_target)) {}

    rocksdb::IOStatus Sync(const rocksdb::IOOptions& f_options,
                           rocksdb::IODebugContext* f_dbg) override {
        countIntercept();
        return target()->Flush(f_options, f_dbg);
    }

    rocksdb::IOStatus Fsync(const rocksdb::IOOptions& f_options,
                            rocksdb::IODebugContext* f_dbg) override {
        countIntercept();
        return target()->Flush(f_options, f_dbg);
    }

    // RangeSync only starts write-out, which the page cache does on its own.
    rocksdb::IOStatus RangeSync(uint64_t /*f_offset*/, uint64_t /*f_nbytes*/,
                                const rocksdb::IOOptions& /*f_options*/,
                                rocksdb::IODebugContext* /*f_dbg*/) override {
        countIntercept();
        return rocksdb::IOStatus::OK();
    }
};

// A random-RW file whose Sync and Fsync are a Flush of the target (INV-17).
class NoSyncRandomRWFile : public rocksdb::FSRandomRWFileOwnerWrapper {
  public:
    explicit NoSyncRandomRWFile(std::unique_ptr<rocksdb::FSRandomRWFile>&& f_target)
        : rocksdb::FSRandomRWFileOwnerWrapper(std::move(f_target)) {}

    rocksdb::IOStatus Sync(const rocksdb::IOOptions& f_options,
                           rocksdb::IODebugContext* f_dbg) override {
        countIntercept();
        return target()->Flush(f_options, f_dbg);
    }

    rocksdb::IOStatus Fsync(const rocksdb::IOOptions& f_options,
                            rocksdb::IODebugContext* f_dbg) override {
        countIntercept();
        return target()->Flush(f_options, f_dbg);
    }
};

// A directory whose Fsync is a no-op that reports success (INV-17).
class NoSyncDirectory : public rocksdb::FSDirectoryWrapper {
  public:
    explicit NoSyncDirectory(std::unique_ptr<rocksdb::FSDirectory>&& f_target)
        : rocksdb::FSDirectoryWrapper(std::move(f_target)) {}

    rocksdb::IOStatus Fsync(const rocksdb::IOOptions& /*f_options*/,
                            rocksdb::IODebugContext* /*f_dbg*/) override {
        countIntercept();
        return rocksdb::IOStatus::OK();
    }

    rocksdb::IOStatus FsyncWithDirOptions(const rocksdb::IOOptions& /*f_options*/,
                                          rocksdb::IODebugContext* /*f_dbg*/,
                                          const rocksdb::DirFsyncOptions& /*f_dir_options*/) override {
        countIntercept();
        return rocksdb::IOStatus::OK();
    }
};

// On success replace the target's writable file by the no-sync file that owns it; on failure
// return the status unchanged (the result is left as the target set it). All three writable
// factories go through this one helper.
rocksdb::IOStatus wrapWritable(rocksdb::IOStatus f_status,
                               std::unique_ptr<rocksdb::FSWritableFile>* f_result) {
    if (f_status.ok()) {
        *f_result = std::make_unique<NoSyncWritableFile>(std::move(*f_result));
    }
    return f_status;
}

class NoSyncFileSystem : public rocksdb::FileSystemWrapper {
  public:
    explicit NoSyncFileSystem(const std::shared_ptr<rocksdb::FileSystem>& f_target)
        : rocksdb::FileSystemWrapper(f_target) {}

    static const char* kClassName() {
        return "LsmioNoSyncFileSystem";
    }

    const char* Name() const override {
        return kClassName();
    }

    rocksdb::IOStatus NewWritableFile(const std::string& f_name,
                                      const rocksdb::FileOptions& f_options,
                                      std::unique_ptr<rocksdb::FSWritableFile>* f_result,
                                      rocksdb::IODebugContext* f_dbg) override {
        return wrapWritable(target()->NewWritableFile(f_name, f_options, f_result, f_dbg),
                            f_result);
    }

    rocksdb::IOStatus ReopenWritableFile(const std::string& f_name,
                                         const rocksdb::FileOptions& f_options,
                                         std::unique_ptr<rocksdb::FSWritableFile>* f_result,
                                         rocksdb::IODebugContext* f_dbg) override {
        return wrapWritable(target()->ReopenWritableFile(f_name, f_options, f_result, f_dbg),
                            f_result);
    }

    rocksdb::IOStatus ReuseWritableFile(const std::string& f_name, const std::string& f_old_name,
                                        const rocksdb::FileOptions& f_options,
                                        std::unique_ptr<rocksdb::FSWritableFile>* f_result,
                                        rocksdb::IODebugContext* f_dbg) override {
        return wrapWritable(
            target()->ReuseWritableFile(f_name, f_old_name, f_options, f_result, f_dbg), f_result);
    }

    rocksdb::IOStatus NewRandomRWFile(const std::string& f_name,
                                      const rocksdb::FileOptions& f_options,
                                      std::unique_ptr<rocksdb::FSRandomRWFile>* f_result,
                                      rocksdb::IODebugContext* f_dbg) override {
        rocksdb::IOStatus status = target()->NewRandomRWFile(f_name, f_options, f_result, f_dbg);
        if (status.ok()) {
            *f_result = std::make_unique<NoSyncRandomRWFile>(std::move(*f_result));
        }
        return status;
    }

    rocksdb::IOStatus NewDirectory(const std::string& f_name, const rocksdb::IOOptions& f_options,
                                   std::unique_ptr<rocksdb::FSDirectory>* f_result,
                                   rocksdb::IODebugContext* f_dbg) override {
        rocksdb::IOStatus status = target()->NewDirectory(f_name, f_options, f_result, f_dbg);
        if (status.ok()) {
            *f_result = std::make_unique<NoSyncDirectory>(std::move(*f_result));
        }
        return status;
    }
};

}  // namespace

std::shared_ptr<rocksdb::FileSystem> noSyncRocksFileSystem() {
    // Heap object behind a function-local static pointer, never deleted (INV-19).
    static const std::shared_ptr<rocksdb::FileSystem>* const fs =
        new std::shared_ptr<rocksdb::FileSystem>(
            std::make_shared<NoSyncFileSystem>(rocksdb::FileSystem::Default()));
    return *fs;
}

rocksdb::Env* noSyncRocksEnv() {
    // Heap object behind a function-local static pointer, never deleted (INV-19).
    static rocksdb::Env* const env = rocksdb::NewCompositeEnv(noSyncRocksFileSystem()).release();
    return env;
}

std::uint64_t interceptedRocksDBSyncCount() {
    return g_intercepted_syncs.load(std::memory_order_relaxed);
}

#else

std::uint64_t interceptedRocksDBSyncCount() {
    return 0;
}

#endif

}  // namespace lsmio
