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

#ifndef _LSMIO_IMEMTABLE_HPP_
#define _LSMIO_IMEMTABLE_HPP_

#include <functional>
#include <map>
#include <set>
#include <string>

namespace lsmio {

extern const std::string MEMTABLE_TOMBSTONE;

/// Merges one scanned entry into the prefix-scan result sets, applying the
/// tombstone semantics shared by every memtable implementation: a tombstone
/// marks the key deleted (and retracts any older live value already merged),
/// a live value re-adds the key (and retracts any older deletion).
inline void applyScanEntry(const std::string& f_key, const std::string& f_value,
                           std::map<std::string, std::string>& f_results,
                           std::set<std::string>& f_deleted_keys) {
    if (f_value == MEMTABLE_TOMBSTONE) {
        f_deleted_keys.insert(f_key);
        f_results.erase(f_key);
    } else {
        f_results[f_key] = f_value;
        f_deleted_keys.erase(f_key);
    }
}

class IMemtable {
  public:
    virtual ~IMemtable() = default;

    virtual void add(const std::string& f_key, const std::string& f_value) = 0;
    virtual bool get(const std::string& f_key, std::string& f_value) const = 0;
    virtual void scan(const std::string& f_prefix, std::map<std::string, std::string>& f_results,
                      std::set<std::string>& f_deleted_keys) const = 0;
    virtual size_t sizeBytes() const = 0;
    virtual bool empty() const = 0;
    virtual size_t count() const = 0;
    virtual void forEach(std::function<void(const std::string& f_key, const std::string& f_value)>
                             f_callback) const = 0;
};

}  // namespace lsmio

#endif
