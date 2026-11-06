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

#ifndef _LSMIO_PLUGIN_TCC_
#define _LSMIO_PLUGIN_TCC_

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>

#include "lsmio_plugin.hpp"

namespace lsmio {

template <typename T>
void LsmioPlugin::AddVariable(const std::string &name, Dims shape, Dims start, Dims count) {
    LOG(INFO) << "LsmioPlugin::AddVariable<T>: " << name << std::endl;

    core::Variable<T> *v = m_IO.InquireVariable<T>(name);
    if (!v) {
        m_IO.DefineVariable<T>(name, shape, start, count);
    }
}

// Attribute values are stored as raw bytes (strings: a length-prefixed string per element)
template <typename T>
void LsmioPlugin::EncodeAttribute(std::string &entry, const core::AttributeBase &attribute) {
    const auto &a = static_cast<const core::Attribute<T> &>(attribute);
    const T *data = a.m_IsSingleValue ? &a.m_DataSingleValue : a.m_DataArray.data();
    entry.append(reinterpret_cast<const char *>(data), a.m_Elements * sizeof(T));
}

template <>
inline void LsmioPlugin::EncodeAttribute<std::string>(std::string &entry,
                                                      const core::AttributeBase &attribute) {
    const auto &a = static_cast<const core::Attribute<std::string> &>(attribute);
    const std::string *data = a.m_IsSingleValue ? &a.m_DataSingleValue : a.m_DataArray.data();
    for (size_t i = 0; i < a.m_Elements; ++i) {
        const uint64_t len = data[i].size();
        entry.append(reinterpret_cast<const char *>(&len), sizeof(len));
        entry.append(data[i]);
    }
}

template <typename T>
void LsmioPlugin::DefineAttribute(const std::string &name, bool singleValue, size_t elements,
                                  const char *data, size_t size) {
    // elements is checked by division first: a corrupt count must not overflow the product
    if (elements > size / sizeof(T) || size != elements * sizeof(T) ||
        (singleValue && elements != 1)) {
        throw std::runtime_error("ERROR: LsmioPlugin: corrupt metadata for attribute " + name);
    }
    std::vector<T> values(elements);
    if (size) std::memcpy(values.data(), data, size);
    if (singleValue) {
        m_IO.DefineAttribute<T>(name, values.at(0), "", "/", true);
    } else {
        m_IO.DefineAttribute<T>(name, values.data(), elements, "", "/", true);
    }
}

template <>
inline void LsmioPlugin::DefineAttribute<std::string>(const std::string &name, bool singleValue,
                                                      size_t elements, const char *data,
                                                      size_t size) {
    std::vector<std::string> values;
    size_t pos = 0;
    for (size_t i = 0; i < elements; ++i) {
        uint64_t len = 0;
        if (size - pos < sizeof(len)) break;
        std::memcpy(&len, data + pos, sizeof(len));
        pos += sizeof(len);
        if (size - pos < len) break;
        values.emplace_back(data + pos, len);
        pos += len;
    }
    if (values.size() != elements || pos != size || (singleValue && elements != 1)) {
        throw std::runtime_error("ERROR: LsmioPlugin: corrupt metadata for attribute " + name);
    }
    if (singleValue) {
        m_IO.DefineAttribute<std::string>(name, values.at(0), "", "/", true);
    } else {
        m_IO.DefineAttribute<std::string>(name, values.data(), elements, "", "/", true);
    }
}

// Values are stored as the raw bytes of the selection, in the writer's byte order (a long
// double keeps its ABI padding bytes, as BP5 does)
template <class T>
inline void LsmioPlugin::ReadVariable(core::Variable<T> &variable, T *values) {
    LOG(INFO) << "LsmioPlugin::ReadVariable<T>: " << variable.m_Name << std::endl;
    CheckMemorySelection(variable);
    CheckSelection(variable);

    std::string bytes;
    if (!_lm->get(variable.m_Name, &bytes)) {
        throw std::runtime_error("ERROR: LsmioPlugin: could not read variable " + variable.m_Name);
    }

    const size_t size = variable.SelectionSize() * sizeof(T);
    if (bytes.size() != size) {
        throw std::runtime_error("ERROR: LsmioPlugin: variable " + variable.m_Name + " holds " +
                                 std::to_string(bytes.size()) + " bytes, the selection needs " +
                                 std::to_string(size));
    }
    if (size) std::memcpy(values, bytes.data(), size);
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<std::string> &variable, std::string *values) {
    LOG(INFO) << "LsmioPlugin::ReadVariable<string>: " << variable.m_Name << std::endl;
    if (!_lm->get(variable.m_Name, &(values[0]))) {
        throw std::runtime_error("ERROR: LsmioPlugin: could not read variable " + variable.m_Name);
    }
}

template <typename T>
inline void LsmioPlugin::WriteVariable(core::Variable<T> &variable, const T *values,
                                       const Mode launch) {
    bool isSync = (launch == Mode::Sync) ? true : false;
    CheckMemorySelection(variable);
    // Sync and Deferred alike: the bytes are copied before the put returns (by the native store
    // once, into C0; for a client of an aggregator, into the MPI message), so the caller's memory
    // is free again on return
    const std::string_view bytes(reinterpret_cast<const char *>(values),
                                 variable.SelectionSize() * sizeof(T));

    LOG(INFO) << "LsmioPlugin::WriteVariable<T>: key: " << variable.m_Name
              << " bytes: " << bytes.size() << std::endl;

    // A failed put (e.g. a value over LSMIO's maximum value length) must not be lost silently
    if (!_lm->putBytes(variable.m_Name, bytes, isSync)) {
        throw std::runtime_error("ERROR: LsmioPlugin: could not write variable " + variable.m_Name);
    }
    RecordVariable(variable);
}

template <>
inline void LsmioPlugin::WriteVariable(core::Variable<std::string> &variable,
                                       const std::string *values, const Mode launch) {
    bool isSync = (launch == Mode::Sync) ? true : false;
    LOG(INFO) << "LsmioPlugin::WriteVariable<string>: key: " << variable.m_Name
              << " bytes: " << values[0].size() << std::endl;
    if (!_lm->put(variable.m_Name, values[0], isSync)) {
        throw std::runtime_error("ERROR: LsmioPlugin: could not write variable " + variable.m_Name);
    }
    RecordVariable(variable);
}

}  // namespace lsmio

#endif
