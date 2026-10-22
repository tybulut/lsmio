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

// Copy-once: a put copies its value once, into C0, and makes no other copy on the way. Every
// allocation of at least the value's size made by the putting thread is counted (the store's own
// threads, e.g. the flush thread, are not)

#include <gtest/gtest.h>

#include <cstdlib>
#include <filesystem>
#include <lsmio/manager/manager.hpp>
#include <lsmio/manager/store/native/StoreNative.hpp>
#include <new>
#include <string>
#include <string_view>
#include <vector>

namespace {
thread_local bool tl_counting = false;
thread_local bool tl_fail_large = false;
thread_local long tl_fail_at = -1;  // >= 0: the allocation that many allocations from now throws
thread_local size_t tl_large_allocs = 0;
constexpr size_t VALUE_SIZE = 1024 * 1024;
}  // namespace

void* operator new(std::size_t f_size) {
    if (tl_counting && f_size >= VALUE_SIZE) ++tl_large_allocs;
    if (tl_fail_large && f_size >= VALUE_SIZE) throw std::bad_alloc();
    if (tl_fail_at >= 0 && tl_fail_at-- == 0) throw std::bad_alloc();
    if (void* p = std::malloc(f_size ? f_size : 1)) return p;
    throw std::bad_alloc();
}

void operator delete(void* f_ptr) noexcept {
    std::free(f_ptr);
}

void operator delete(void* f_ptr, std::size_t) noexcept {
    std::free(f_ptr);
}

namespace {

// The allocations of at least VALUE_SIZE bytes that f makes on this thread
template <typename F>
size_t largeAllocs(F f) {
    tl_large_allocs = 0;
    tl_counting = true;
    f();
    tl_counting = false;
    return tl_large_allocs;
}

// Arms the fault injection for its scope, and disarms it even if the put throws. A store whose
// add threw leaks the memtable on purpose (see LSMIOStoreNative::dropActiveMemtable): run these
// tests under AddressSanitizer with detect_leaks=0
class FailGuard {
  public:
    explicit FailGuard(long f_fail_at) {
        if (f_fail_at < 0) {
            tl_fail_large = true;
        } else {
            tl_fail_at = f_fail_at;
        }
    }
    ~FailGuard() {
        tl_fail_large = false;
        tl_fail_at = -1;
    }
};

std::string value(char c) {
    return std::string(VALUE_SIZE, c);
}

class CopyOnceTest : public ::testing::Test {
  protected:
    lsmio::LSMIOConfig m_backup_config;

    void SetUp() override {
        m_backup_config = lsmio::gConfigLSMIO;
    }

    void TearDown() override {
        lsmio::gConfigLSMIO = m_backup_config;
    }
};

}  // namespace

TEST_F(CopyOnceTest, NativeStorePuts) {
    const lsmio::MemtableType memtables[] = {lsmio::MemtableType::VectorNoSort,
                                             lsmio::MemtableType::VectorSort,
                                             lsmio::MemtableType::Map, lsmio::MemtableType::BTree};
    for (lsmio::MemtableType memtable : memtables) {
        SCOPED_TRACE(static_cast<int>(memtable));
        lsmio::gConfigLSMIO.memtable = memtable;
        const std::string dbPath = "test-copy-once-native.db";
        std::filesystem::remove_all(dbPath);
        {
            lsmio::LSMIOStoreNative store(dbPath, true);
            const std::string a = value('a');
            const std::string b = value('b');
            std::string moved = value('c');

            EXPECT_EQ(largeAllocs([&] { EXPECT_TRUE(store.putBytes("bytes", a)); }), 1u);
            EXPECT_EQ(largeAllocs([&] { EXPECT_TRUE(store.putBytes("bytes", b)); }), 1u);
            EXPECT_EQ(largeAllocs([&] { EXPECT_TRUE(store.put("ref", a)); }), 1u);
            // an overwrite may reuse the slot's capacity
            EXPECT_LE(largeAllocs([&] { EXPECT_TRUE(store.put("ref", b)); }), 1u);
            EXPECT_EQ(largeAllocs([&] { EXPECT_TRUE(store.put("moved", std::move(moved))); }), 0u);

            std::string out;
            EXPECT_TRUE(store.get("bytes", &out));
            EXPECT_EQ(out, b);
            EXPECT_TRUE(store.get("ref", &out));
            EXPECT_EQ(out, b);
            EXPECT_TRUE(store.get("moved", &out));
            EXPECT_EQ(out, value('c'));
        }
        std::filesystem::remove_all(dbPath);
    }
}

// A put the store refuses copies nothing
TEST_F(CopyOnceTest, NativeStoreRefusedPutBytes) {
    lsmio::gConfigLSMIO.writeBufferSize = 2 * 1024 * 1024;
    lsmio::gConfigLSMIO.maxKeyLen = 256;
    const std::string dbPath = "test-copy-once-refused.db";
    std::filesystem::remove_all(dbPath);
    {
        lsmio::LSMIOStoreNative store(dbPath, true);
        const std::string oversize(lsmio::gConfigLSMIO.getMaxValueLen() + 1, 'v');
        EXPECT_EQ(largeAllocs([&] { EXPECT_FALSE(store.putBytes("key", oversize)); }), 0u);
    }
    std::filesystem::remove_all(dbPath);
}

// An add that throws inside the memtable fails the put and the store; the memtable is dropped,
// so close() neither flushes nor hangs on it
TEST_F(CopyOnceTest, NativeStoreAddThatThrows) {
    const lsmio::MemtableType memtables[] = {lsmio::MemtableType::VectorNoSort,
                                             lsmio::MemtableType::VectorSort,
                                             lsmio::MemtableType::Map, lsmio::MemtableType::BTree};
    for (lsmio::MemtableType memtable : memtables) {
        SCOPED_TRACE(static_cast<int>(memtable));
        lsmio::gConfigLSMIO.memtable = memtable;
        const std::string dbPath = "test-copy-once-throw.db";
        std::filesystem::remove_all(dbPath);
        {
            lsmio::LSMIOStoreNative store(dbPath, true);
            EXPECT_TRUE(store.put("small", "value"));
            const std::string big = value('b');
            bool ok;
            {
                FailGuard fail(-1);
                ok = store.put("big", big);  // the memtable's copy of big throws
            }
            EXPECT_FALSE(ok);
            EXPECT_FALSE(store.put("after", "value"));
            EXPECT_FALSE(store.writeBarrier());
            store.close();
        }
        {
            // the dropped memtable was not flushed
            lsmio::LSMIOStoreNative store(dbPath, false);
            std::string out;
            EXPECT_FALSE(store.get("small", &out));
        }
        std::filesystem::remove_all(dbPath);
    }
}

// A throw inside the B+ tree's own insert (a node or key allocation) can leave the tree
// inconsistent, so that destroying it frees a node twice; the store drops that memtable without
// flushing or destroying it. The k-th allocation of the put throws, for every k until the put no
// longer throws. The keys and the new key were found by searching for an insert that splits
// nodes such that, with tlx 0.6.1, destroying the tree after one of these throws is a
// use-after-free (AddressSanitizer reports it when the drop destroys the memtable)
TEST_F(CopyOnceTest, NativeStoreBTreeInsertThatThrows) {
    lsmio::gConfigLSMIO.memtable = lsmio::MemtableType::BTree;
    lsmio::gConfigLSMIO.filePoolSize = 1;
    const std::string dbPath = "test-copy-once-btree-throw.db";
    std::vector<std::string> keys;
    for (int i = 0; i < 350; ++i) {
        keys.push_back(std::string(16 + (i * 37) % 120, static_cast<char>('a' + (i * 7) % 26)) +
                       std::to_string(i * 7919));
    }
    const std::string newKey = std::string(20, 'd') + "z";
    size_t throws = 0;
    for (long k = 0; k < 200; ++k) {
        std::filesystem::remove_all(dbPath);
        bool ok;
        {
            lsmio::LSMIOStoreNative store(dbPath, true);
            for (const auto& key : keys) ASSERT_TRUE(store.put(key, "v"));
            {
                FailGuard fail(k);
                ok = store.put(newKey, "x");
            }
            if (!ok) {
                ++throws;
                EXPECT_FALSE(store.put("after", "value"));
                EXPECT_FALSE(store.writeBarrier());
            }
            store.close();
        }
        if (ok) break;
    }
    std::filesystem::remove_all(dbPath);
    EXPECT_GT(throws, 0u);
}

TEST_F(CopyOnceTest, ManagerRawPuts) {
    const std::string dbName = "test-copy-once-manager.db";
    std::filesystem::remove_all(dbName);
    {
        lsmio::LSMIOManager lm(dbName, "");
        const std::string a = value('a');
        const std::vector<char> raw(VALUE_SIZE, 'r');

        EXPECT_EQ(
            largeAllocs([&] {
                EXPECT_TRUE(lm.put("char", raw.data(), static_cast<std::streamsize>(raw.size())));
            }),
            1u);
        EXPECT_EQ(
            largeAllocs([&] {
                EXPECT_TRUE(lm.put("void", static_cast<const void*>(raw.data()), 1, raw.size()));
            }),
            1u);
        EXPECT_EQ(largeAllocs([&] { EXPECT_TRUE(lm.putBytes("bytes", a, true)); }), 1u);
        EXPECT_EQ(largeAllocs([&] { EXPECT_TRUE(lm.put("ref", a, true)); }), 1u);
        EXPECT_FALSE(lm.put("negative", raw.data(), -1));

        std::string out;
        EXPECT_TRUE(lm.get("char", &out));
        EXPECT_EQ(out, std::string(raw.begin(), raw.end()));
        EXPECT_TRUE(lm.get("bytes", &out));
        EXPECT_EQ(out, a);
    }
    std::filesystem::remove_all(dbName);
}

int main(int argc, char** argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
