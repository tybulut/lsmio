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
#include <lsmio/manager/store/native/MemtableVectorNoSort.hpp>
#include <numeric>

namespace lsmio {


MemtableVectorNoSort::MemtableVectorNoSort() : m_size_bytes(0) {}

void MemtableVectorNoSort::add(const std::string& f_key, const std::string& f_value) {
    m_data.emplace_back(f_key, f_value);
    m_size_bytes += f_key.size() + f_value.size();
}

bool MemtableVectorNoSort::get(const std::string& f_key, std::string& f_value) const {
    // Reverse scan (newest first)
    for (auto it = m_data.rbegin(); it != m_data.rend(); ++it) {
        if (it->first == f_key) {
            f_value = it->second;
            return true;
        }
    }
    return false;
}

void MemtableVectorNoSort::scan(const std::string& f_prefix, std::map<std::string, std::string>& f_results,
                    std::set<std::string>& f_deleted_keys) const {
    // Linear scan
    for (const auto& entry : m_data) {
        if (entry.first.compare(0, f_prefix.size(), f_prefix) == 0) {
            applyScanEntry(entry.first, entry.second, f_results, f_deleted_keys);
        }
    }
}

size_t MemtableVectorNoSort::sizeBytes() const {
    return m_size_bytes;
}

bool MemtableVectorNoSort::empty() const {
    return m_data.empty();
}

size_t MemtableVectorNoSort::count() const {
    return m_data.size();
}

void MemtableVectorNoSort::forEach(std::function<void(const std::string& f_key, const std::string& f_value)> f_callback) const {
    std::vector<size_t> indices(m_data.size());
    std::iota(indices.begin(), indices.end(), 0);
    
    // Stable sort by key to retain insertion order for duplicates (which means newer elements stay after older ones)
    std::stable_sort(indices.begin(), indices.end(),
                     [this](size_t a, size_t b) {
                         return m_data[a].first < m_data[b].first;
                     });

    // explicitly deduplicate the sorted copy (ensuring only the latest inserted value for each key is retained)
    for (size_t i = 0; i < indices.size(); ++i) {
        if (i < indices.size() - 1 && m_data[indices[i]].first == m_data[indices[i+1]].first) {
            continue; // Skip because a newer one is coming
        }
        f_callback(m_data[indices[i]].first, m_data[indices[i]].second);
    }
}

}  // namespace lsmio
