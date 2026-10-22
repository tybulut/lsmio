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

#ifndef _LSMIO_MEMTABLE_ORDERED_HPP_
#define _LSMIO_MEMTABLE_ORDERED_HPP_

#include <map>
#include <string>
#include <utility>

#include "IMemtable.hpp"

namespace lsmio {

// MapT: an ordered map with try_emplace, such as std::map (the B+ tree is MemtableBTree)
template <typename MapT>
class MemtableOrdered : public IMemtable {
  public:
    MemtableOrdered() : m_size_bytes(0) {}

    // try_emplace copies or moves the value only when the key is new (an existing key leaves
    // f_value untouched), so the value is copied once on either path
    void add(const std::string& f_key, const std::string& f_value) override {
        auto [it, inserted] = m_data.try_emplace(f_key, f_value);
        if (inserted) {
            m_size_bytes += f_key.size() + f_value.size();
        } else {
            m_size_bytes -= it->second.size();
            m_size_bytes += f_value.size();
            it->second = f_value;
        }
    }

    void add(const std::string& f_key, std::string&& f_value) override {
        const size_t val_bytes = f_value.size();
        auto [it, inserted] = m_data.try_emplace(f_key, std::move(f_value));
        if (inserted) {
            m_size_bytes += f_key.size() + val_bytes;
        } else {
            m_size_bytes -= it->second.size();
            m_size_bytes += val_bytes;
            it->second = std::move(f_value);
        }
    }

    bool get(const std::string& f_key, std::string& f_value) const override {
        auto it = m_data.find(f_key);
        if (it != m_data.end()) {
            f_value = it->second;
            return true;
        }
        return false;
    }

    void scan(const std::string& f_prefix, std::map<std::string, std::string>& f_results,
              std::set<std::string>& f_deleted_keys) const override {
        auto it = m_data.lower_bound(f_prefix);
        for (; it != m_data.end(); ++it) {
            if (it->first.compare(0, f_prefix.size(), f_prefix) != 0) {
                break;
            }
            applyScanEntry(it->first, it->second, f_results, f_deleted_keys);
        }
    }

    size_t sizeBytes() const override {
        return m_size_bytes;
    }

    bool empty() const override {
        return m_data.empty();
    }

    size_t count() const override {
        return m_data.size();
    }

    void forEach(std::function<void(const std::string& f_key, const std::string& f_value)>
                     f_callback) const override {
        for (const auto& pair : m_data) {
            f_callback(pair.first, pair.second);
        }
    }

  private:
    MapT m_data;
    size_t m_size_bytes;
};

}  // namespace lsmio

#endif
