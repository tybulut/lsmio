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

#ifndef _LSMIO_MEMTABLE_BTREE_HPP_
#define _LSMIO_MEMTABLE_BTREE_HPP_

#include <functional>
#include <map>
#include <set>
#include <string>
#include <tlx/container/btree_map.hpp>
#include <utility>
#include <vector>

#include "IMemtable.hpp"

namespace lsmio {

/// B+ tree memtable. The tree maps each key to a slot of m_values: tlx inserts by copy and
/// shifts slots with std::copy, so the values stay out of it and are copied once, into their
/// slot (or moved there); a growing m_values moves its strings
class MemtableBTree : public IMemtable {
  public:
    MemtableBTree() : m_size_bytes(0) {}

    void add(const std::string& f_key, const std::string& f_value) override {
        m_values.push_back(f_value);
        place(f_key);
    }

    void add(const std::string& f_key, std::string&& f_value) override {
        m_values.push_back(std::move(f_value));
        place(f_key);
    }

    bool get(const std::string& f_key, std::string& f_value) const override {
        auto it = m_index.find(f_key);
        if (it != m_index.end()) {
            f_value = m_values[it->second];
            return true;
        }
        return false;
    }

    void scan(const std::string& f_prefix, std::map<std::string, std::string>& f_results,
              std::set<std::string>& f_deleted_keys) const override {
        auto it = m_index.lower_bound(f_prefix);
        for (; it != m_index.end(); ++it) {
            if (it->first.compare(0, f_prefix.size(), f_prefix) != 0) {
                break;
            }
            applyScanEntry(it->first, m_values[it->second], f_results, f_deleted_keys);
        }
    }

    size_t sizeBytes() const override {
        return m_size_bytes;
    }

    bool empty() const override {
        return m_index.empty();
    }

    size_t count() const override {
        return m_index.size();
    }

    void forEach(std::function<void(const std::string& f_key, const std::string& f_value)>
                     f_callback) const override {
        for (const auto& pair : m_index) {
            f_callback(pair.first, m_values[pair.second]);
        }
    }

  private:
    // The value is already in the last slot: one descent finds or adds the key. An existing key
    // takes the value into its own slot and the last one goes. tlx gives no exception guarantee:
    // after insert2 throws (bad_alloc copying a key or allocating a node) the tree may be
    // inconsistent (destroying it can free a node twice), and LSMIOStoreNative drops the
    // memtable without destroying it. The last slot is kept then, so no key refers past
    // m_values
    void place(const std::string& f_key) {
        const size_t slot = m_values.size() - 1;
        auto result = m_index.insert2(f_key, slot);
        const size_t val_bytes = m_values.back().size();
        if (result.second) {
            m_size_bytes += f_key.size() + val_bytes;
        } else {
            std::string& existing = m_values[result.first->second];
            m_size_bytes -= existing.size();
            m_size_bytes += val_bytes;
            existing = std::move(m_values.back());
            m_values.pop_back();
        }
    }

    tlx::btree_map<std::string, size_t> m_index;
    std::vector<std::string> m_values;
    size_t m_size_bytes;
};

}  // namespace lsmio

#endif
