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

#include <algorithm>
#include <lsmio/manager/store/native/MemtableVectorSort.hpp>

namespace {

// Comparator for lower_bound over the key-sorted entry vector.
struct EntryKeyLess {
    bool operator()(const std::pair<std::string, std::string>& f_entry,
                    const std::string& f_key) const {
        return f_entry.first < f_key;
    }
};

}  // namespace

namespace lsmio {

MemtableVectorSort::MemtableVectorSort() : m_size_bytes(0) {}

void MemtableVectorSort::add(const std::string& f_key, const std::string& f_value) {
    auto it = std::lower_bound(m_data.begin(), m_data.end(), f_key, EntryKeyLess{});

    if (it != m_data.end() && it->first == f_key) {
        // Key exists, overwrite and update size bytes
        m_size_bytes -= it->second.size();
        m_size_bytes += f_value.size();
        it->second = f_value;
    } else {
        // New key
        m_data.insert(it, {f_key, f_value});
        m_size_bytes += f_key.size() + f_value.size();
    }
}

bool MemtableVectorSort::get(const std::string& f_key, std::string& f_value) const {
    auto it = std::lower_bound(m_data.begin(), m_data.end(), f_key, EntryKeyLess{});

    if (it != m_data.end() && it->first == f_key) {
        f_value = it->second;
        return true;
    }
    return false;
}

void MemtableVectorSort::scan(const std::string& f_prefix, std::map<std::string, std::string>& f_results,
                    std::set<std::string>& f_deleted_keys) const {
    auto it = std::lower_bound(m_data.begin(), m_data.end(), f_prefix, EntryKeyLess{});

    for (; it != m_data.end(); ++it) {
        if (it->first.compare(0, f_prefix.size(), f_prefix) != 0) {
            break; // Stop scanning once we're past the prefix
        }
        applyScanEntry(it->first, it->second, f_results, f_deleted_keys);
    }
}

size_t MemtableVectorSort::sizeBytes() const {
    return m_size_bytes;
}

bool MemtableVectorSort::empty() const {
    return m_data.empty();
}

size_t MemtableVectorSort::count() const {
    return m_data.size();
}

void MemtableVectorSort::forEach(std::function<void(const std::string& f_key, const std::string& f_value)> f_callback) const {
    for (const auto& pair : m_data) {
        f_callback(pair.first, pair.second);
    }
}

}  // namespace lsmio
