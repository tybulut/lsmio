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

#include "NoSyncLevelDBEnv.hpp"

#include <atomic>
#include <memory>
#include <string>

namespace lsmio {

namespace {

std::atomic<std::uint64_t> g_intercepted_syncs{0};

// A WritableFile whose Sync() is a Flush(): the data has been handed to the OS, nothing is
// dropped and no fsync/fdatasync is issued (INV-17). It owns the file it wraps.
class NoSyncWritableFile : public leveldb::WritableFile {
  public:
    explicit NoSyncWritableFile(leveldb::WritableFile* f_target) : m_target(f_target) {}

    leveldb::Status Append(const leveldb::Slice& f_data) override {
        return m_target->Append(f_data);
    }
    leveldb::Status Close() override {
        return m_target->Close();
    }
    leveldb::Status Flush() override {
        return m_target->Flush();
    }
    leveldb::Status Sync() override {
        g_intercepted_syncs.fetch_add(1, std::memory_order_relaxed);
        return m_target->Flush();
    }

  private:
    std::unique_ptr<leveldb::WritableFile> m_target;
};

class NoSyncEnv : public leveldb::EnvWrapper {
  public:
    explicit NoSyncEnv(leveldb::Env* f_target) : leveldb::EnvWrapper(f_target) {}

    leveldb::Status NewWritableFile(const std::string& f_name,
                                    leveldb::WritableFile** f_result) override {
        return wrap(target()->NewWritableFile(f_name, f_result), f_result);
    }

    leveldb::Status NewAppendableFile(const std::string& f_name,
                                      leveldb::WritableFile** f_result) override {
        return wrap(target()->NewAppendableFile(f_name, f_result), f_result);
    }

  private:
    // On success replace the target's file by the no-sync file that owns it; on failure leave
    // the status and the result pointer exactly as the target set them.
    static leveldb::Status wrap(leveldb::Status f_status, leveldb::WritableFile** f_result) {
        if (f_status.ok()) {
            *f_result = new NoSyncWritableFile(*f_result);
        }
        return f_status;
    }
};

}  // namespace

leveldb::Env* noSyncLevelDBEnv() {
    // Heap object behind a function-local static pointer, never deleted (INV-19).
    static leveldb::Env* const env = new NoSyncEnv(leveldb::Env::Default());
    return env;
}

std::uint64_t interceptedLevelDBSyncCount() {
    return g_intercepted_syncs.load(std::memory_order_relaxed);
}

}  // namespace lsmio
