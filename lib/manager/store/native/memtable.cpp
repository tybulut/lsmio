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

#include <lsmio/manager/store/native/memtable.hpp>

namespace lsmio {

Memtable::Memtable() : _size_bytes(0) {}

void Memtable::add(const std::string& key, const std::string& value) {
    _data.emplace_back(key, value);
    _size_bytes += key.size() + value.size();
}

bool Memtable::get(const std::string& key, std::string& value) const {
    // Reverse scan (newest first)
    for (auto it = _data.rbegin(); it != _data.rend(); ++it) {
        if (it->first == key) {
            value = it->second;
            return true;
        }
    }
    return false;
}

void Memtable::scan(const std::string& prefix, std::map<std::string, std::string>& results,
                    std::set<std::string>& deleted_keys) const {
    // Linear scan
    for (const auto& entry : _data) {
        if (entry.first.compare(0, prefix.size(), prefix) == 0) {
            if (entry.second == MEMTABLE_TOMBSTONE) {
                deleted_keys.insert(entry.first);
                results.erase(entry.first);
            } else {
                results[entry.first] = entry.second;
                deleted_keys.erase(entry.first);
            }
        }
    }
}

size_t Memtable::sizeBytes() const {
    return _size_bytes;
}

bool Memtable::empty() const {
    return _data.empty();
}

size_t Memtable::count() const {
    return _data.size();
}

const std::vector<std::pair<std::string, std::string>>& Memtable::getData() const {
    return _data;
}

}  // namespace lsmio
