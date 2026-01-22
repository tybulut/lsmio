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

#ifndef _LSMIO_MEMTABLE_HPP_
#define _LSMIO_MEMTABLE_HPP_

#include <map>
#include <set>
#include <string>
#include <vector>

namespace lsmio {

// Define the tombstone value constant to be shared
const std::string MEMTABLE_TOMBSTONE = "__LSM_TOMBSTONE_v1__";

class Memtable {
  public:
    Memtable();
    ~Memtable() = default;

    // Add a key-value pair. If value is MEMTABLE_TOMBSTONE, it represents a deletion.
    void add(const std::string& key, const std::string& value);

    // Look up a key. Returns true if found (even if it's a tombstone).
    // The value is populated if found.
    bool get(const std::string& key, std::string& value) const;

    // Scan for keys with a specific prefix.
    // Results are added to the map. Tombstones are added to deleted_keys.
    void scan(const std::string& prefix, std::map<std::string, std::string>& results,
              std::set<std::string>& deleted_keys) const;

    // Current estimated size in bytes
    size_t sizeBytes() const;

    bool empty() const;
    size_t count() const;

    // Access to underlying data for flushing
    const std::vector<std::pair<std::string, std::string>>& getData() const;

  private:
    std::vector<std::pair<std::string, std::string>> _data;
    size_t _size_bytes;
};

}  // namespace lsmio

#endif
