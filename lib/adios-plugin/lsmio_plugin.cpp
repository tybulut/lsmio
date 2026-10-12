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

#include "lsmio_plugin.hpp"

#include <adios2/helper/adiosSystem.h>
#include <adios2/helper/adiosType.h>

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

#include "lsmio_plugin.tcc"

using namespace adios2;

namespace lsmio {

namespace {

// The metadata record: u64 entry count, then per entry: u8 kind, str name, str type, then
//   variable:  u8 shape id, dims shape, dims start, dims count
//   attribute: u8 single value, u64 elements, str values (raw bytes; strings length-prefixed)
// where str is a u64 length and the bytes, and dims a u64 count and u64 values, all in the
// writer's byte order
constexpr uint8_t KIND_VARIABLE = 0;
constexpr uint8_t KIND_ATTRIBUTE = 1;

void putU64(std::string &out, uint64_t value) {
    out.append(reinterpret_cast<const char *>(&value), sizeof(value));
}

void putStr(std::string &out, const std::string &value) {
    putU64(out, value.size());
    out.append(value);
}

void putDims(std::string &out, const Dims &dims) {
    putU64(out, dims.size());
    for (const auto d : dims) putU64(out, d);
}

class RecordReader {
  public:
    explicit RecordReader(const std::string &record) : _record(record) {}

    bool done() const {
        return _pos == _record.size();
    }
    size_t pos() const {
        return _pos;
    }

    uint8_t u8() {
        need(1);
        return static_cast<uint8_t>(_record[_pos++]);
    }

    uint64_t u64() {
        uint64_t value;
        need(sizeof(value));
        std::memcpy(&value, _record.data() + _pos, sizeof(value));
        _pos += sizeof(value);
        return value;
    }

    std::string str() {
        const uint64_t len = u64();
        need(len);
        std::string value = _record.substr(_pos, len);
        _pos += len;
        return value;
    }

    Dims dims() {
        const uint64_t n = u64();
        if (n > (_record.size() - _pos) / sizeof(uint64_t)) {
            throw std::runtime_error("ERROR: LsmioPlugin: corrupt metadata record");
        }
        Dims value(n);
        for (auto &d : value) d = u64();
        return value;
    }

  private:
    void need(uint64_t n) const {
        if (n > _record.size() - _pos) {
            throw std::runtime_error("ERROR: LsmioPlugin: corrupt metadata record");
        }
    }

    const std::string &_record;
    size_t _pos = 0;
};

std::string dimsToString(const Dims &dims) {
    std::string out = "{";
    for (size_t i = 0; i < dims.size(); ++i) {
        out += (i ? "," : "") + std::to_string(dims[i]);
    }
    return out + "}";
}

}  // namespace

LsmioPlugin::LsmioPlugin(core::IO &io, const std::string &name, const Mode mode, helper::Comm comm)
    : plugin::PluginEngineInterface(io, name, mode, comm.Duplicate()) {
    _dbName = name;
    try {
        Init();
    } catch (...) {
        // The destructor doesn't run for a failed constructor: stop the manager (and its
        // collective I/O thread) here
        delete _lm;
        _lm = nullptr;
        throw;
    }
}

LsmioPlugin::~LsmioPlugin() {
    LOG(INFO) << "LsmioPlugin::~LsmioPlugin(): " << std::endl;
    if (_lm) delete _lm;
    LOG(INFO) << "LsmioPlugin::~LsmioPlugin(): completed." << std::endl;
}

bool LsmioPlugin::IsWriter() const {
    return m_OpenMode == adios2::Mode::Write || m_OpenMode == adios2::Mode::Append;
}

void LsmioPlugin::Init() {
    std::string dirName = "", fileName = "";
    std::string aggregationType = "";
    std::string aggregatorRatio = "";
    dirName = helper::GetParameter("DirName", m_IO.m_Parameters, false, "Init()");
    fileName = helper::GetParameter("FileName", m_IO.m_Parameters, true, "Init()");
    helper::GetParameter(m_IO.m_Parameters, "AggregationType", aggregationType);
    helper::GetParameter(m_IO.m_Parameters, "AggregatorRatio", aggregatorRatio);
    LOG(INFO) << "LsmioPlugin::Init: _dbName: " << _dbName
              << " MPI: " << (m_Comm.IsMPI() ? "YES" : "NO") << " rank: " << m_Comm.Rank()
              << " size: " << m_Comm.Size() << " aggregationType: " << aggregationType
              << " aggregatorRatio: " << aggregatorRatio << " dirName: " << dirName
              << " FileName: " << fileName << std::endl;

    if (fileName.empty()) {
        throw std::invalid_argument("ERROR: LsmioPlugin: no FileName parameter provided.");
    }
    _fileName = fileName;

    const bool overWrite = (m_OpenMode == adios2::Mode::Write);

    if (m_Comm.IsMPI()) {
        if (aggregationType.empty() || aggregationType == "twolevelshm") {
            gConfigLSMIO.mpiAggType = MPIAggType::Shared;
        } else if (aggregationType == "everyonewritesserial") {
            gConfigLSMIO.mpiAggType = MPIAggType::EntireSerial;
        } else if (aggregationType == "everyonewrites" || aggregationType == "auto") {
            if (aggregatorRatio == "2")
                gConfigLSMIO.mpiAggType = MPIAggType::Split;
            else
                gConfigLSMIO.mpiAggType = MPIAggType::Entire;
        } else {
            throw std::invalid_argument(
                "ERROR: LsmioPlugin: Invalid AggregationType parameter provided: " +
                aggregationType);
        }

        _lm = new LSMIOManager(fileName, dirName, overWrite, &m_Comm);
    } else {
        _lm = new LSMIOManager(fileName, dirName, overWrite);
    }

    // One get of the metadata record; read mode defines its variables and attributes, append
    // mode keeps its entries to write back with this session's at Close
    if (m_OpenMode == adios2::Mode::Read || m_OpenMode == adios2::Mode::Append) {
        std::string record;
        const bool found = _lm->metaGet(_metadataKey, &record) && !record.empty();
        if (m_OpenMode == adios2::Mode::Read) {
            if (!found) {
                throw std::runtime_error("ERROR: LsmioPlugin: no LSMIO plugin metadata in " +
                                         fileName);
            }
            DecodeMetadata(record, true);
        } else if (found) {
            DecodeMetadata(record, false);
        }
    }

    LOG(INFO) << "LsmioPlugin::Init: completed..." << std::endl;
}

// A variable is listed only once it is put, as in BP5: a reader never sees one without data
void LsmioPlugin::RecordVariable(const core::VariableBase &variable) {
    std::string entry;
    entry.push_back(static_cast<char>(KIND_VARIABLE));
    putStr(entry, variable.m_Name);
    putStr(entry, ToString(variable.m_Type));
    entry.push_back(static_cast<char>(variable.m_ShapeID));
    putDims(entry, variable.m_Shape);
    putDims(entry, variable.m_Start);
    putDims(entry, variable.m_Count);
    _entries[{KIND_VARIABLE, variable.m_Name}] = std::move(entry);
}

std::string LsmioPlugin::EncodeMetadata() const {
    auto entries = _entries;

    for (const auto &[name, attribute] : m_IO.GetAttributes()) {
        if (attribute->m_Type == DataType::Struct) continue;  // not supported
        std::string entry, values;
        entry.push_back(static_cast<char>(KIND_ATTRIBUTE));
        putStr(entry, name);
        putStr(entry, ToString(attribute->m_Type));
        entry.push_back(static_cast<char>(attribute->m_IsSingleValue));
        putU64(entry, attribute->m_Elements);
        const DataType type = attribute->m_Type;
        if (type == DataType::Struct) {
            // not supported (skipped above)
        }
#define declare_template_instantiation(T)        \
    else if (type == helper::GetDataType<T>()) { \
        EncodeAttribute<T>(values, *attribute);  \
    }
        ADIOS2_FOREACH_ATTRIBUTE_STDTYPE_1ARG(declare_template_instantiation)
#undef declare_template_instantiation
        putStr(entry, values);
        entries[{KIND_ATTRIBUTE, name}] = std::move(entry);
    }

    std::string record;
    putU64(record, entries.size());
    for (const auto &[key, entry] : entries) record.append(entry);
    return record;
}

void LsmioPlugin::DecodeMetadata(const std::string &record, bool defineInIO) {
    RecordReader in(record);
    const uint64_t nEntries = in.u64();

    for (uint64_t i = 0; i < nEntries; ++i) {
        const size_t begin = in.pos();
        const uint8_t kind = in.u8();
        const std::string name = in.str();
        const DataType type = helper::GetDataTypeFromString(in.str());
        if (type == DataType::None || type == DataType::Struct) {
            throw std::runtime_error("ERROR: LsmioPlugin: corrupt metadata record");
        }

        if (kind == KIND_VARIABLE) {
            const auto shapeID = static_cast<ShapeID>(in.u8());
            Dims shape = in.dims();
            Dims start = in.dims();
            Dims count = in.dims();
            if (defineInIO) {
                if (shapeID == ShapeID::LocalValue) {
                    shape = {LocalValueDim};
                    start.clear();
                    count.clear();
                }
                if (type == DataType::Struct) {
                    // not supported (rejected above)
                }
#define declare_template_instantiation(T)          \
    else if (type == helper::GetDataType<T>()) {   \
        AddVariable<T>(name, shape, start, count); \
    }
                ADIOS2_FOREACH_STDTYPE_1ARG(declare_template_instantiation)
#undef declare_template_instantiation
                if (shapeID != ShapeID::LocalValue) _blocks[name] = {start, count};
            }
        } else if (kind == KIND_ATTRIBUTE) {
            const bool singleValue = in.u8() != 0;
            const uint64_t elements = in.u64();
            const std::string values = in.str();
            if (defineInIO) {
                if (type == DataType::Struct) {
                    // not supported (rejected above)
                }
#define declare_template_instantiation(T)                                              \
    else if (type == helper::GetDataType<T>()) {                                       \
        DefineAttribute<T>(name, singleValue, elements, values.data(), values.size()); \
    }
                ADIOS2_FOREACH_ATTRIBUTE_STDTYPE_1ARG(declare_template_instantiation)
#undef declare_template_instantiation
            }
        } else {
            throw std::runtime_error("ERROR: LsmioPlugin: corrupt metadata record");
        }

        if (!defineInIO) _entries[{kind, name}] = record.substr(begin, in.pos() - begin);
        LOG(INFO) << "LsmioPlugin::DecodeMetadata: " << (kind ? "attribute " : "variable ") << name
                  << std::endl;
    }

    if (!in.done()) throw std::runtime_error("ERROR: LsmioPlugin: corrupt metadata record");
}

// Values are the contiguous bytes of the selection: a memory selection is not supported
void LsmioPlugin::CheckMemorySelection(const core::VariableBase &variable) {
    if (!variable.m_MemoryCount.empty()) {
        throw std::invalid_argument("ERROR: LsmioPlugin: SetMemorySelection is not supported: " +
                                    variable.m_Name);
    }
}

// Reads return the block a rank wrote: a selection must match its stored start and count
// (reading across blocks is in BACKLOG.md)
void LsmioPlugin::CheckSelection(const core::VariableBase &variable) const {
    const auto it = _blocks.find(variable.m_Name);
    if (it == _blocks.end()) return;
    const auto &[start, count] = it->second;
    if (variable.m_Start != start || variable.m_Count != count) {
        throw std::invalid_argument("ERROR: LsmioPlugin: selection start " +
                                    dimsToString(variable.m_Start) + " count " +
                                    dimsToString(variable.m_Count) + " of variable " +
                                    variable.m_Name + " differs from its stored block start " +
                                    dimsToString(start) + " count " + dimsToString(count));
    }
}

StepStatus LsmioPlugin::BeginStep(StepMode mode, const float timeoutSeconds) {
    LOG(INFO) << "LsmioPlugin::BeginStep(): " << std::endl;
    return StepStatus::OK;
}

void LsmioPlugin::PerformGets() {
    LOG(INFO) << "LsmioPlugin::PerformGets(): " << std::endl;
}

size_t LsmioPlugin::CurrentStep() const {
    LOG(INFO) << "LsmioPlugin::CurrentStep(): " << std::endl;
    return _currentStep;
}

void LsmioPlugin::EndStep() {
    LOG(INFO) << "LsmioPlugin::EndStep(): " << std::endl;
    _currentStep++;
}

// The metadata record is built in RAM and put once, in write mode only
void LsmioPlugin::DoClose(const int transportIndex) {
    LOG(INFO) << "LsmioPlugin::DoClose(): " << std::endl;
    if (!_lm) return;

    bool success = true;
    if (IsWriter()) {
        success = _lm->metaPut(_metadataKey, EncodeMetadata(), false);
    }
    // In aggregated mode every rank of the group learns here whether its aggregator stored all
    // the group's data
    success &= _lm->close();

    // ADIOS keeps the engine open when Close throws: a second Close must find nothing to do
    delete _lm;
    _lm = nullptr;

    if (!success) {
        throw std::runtime_error("ERROR: LsmioPlugin: could not store all data of " + _fileName);
    }
}

#define declare(T)                                                                  \
    void LsmioPlugin::DoGetSync(core::Variable<T> &variable, T *values) {           \
        LOG(INFO) << "LsmioPlugin::DoGetSync(): " << std::endl;                     \
        ReadVariable(variable, values);                                             \
    }                                                                               \
                                                                                    \
    void LsmioPlugin::DoGetDeferred(core::Variable<T> &variable, T *values) {       \
        LOG(INFO) << "LsmioPlugin::DoGetDeferred(): " << std::endl;                 \
        ReadVariable(variable, values);                                             \
    }                                                                               \
                                                                                    \
    void LsmioPlugin::DoPutSync(core::Variable<T> &variable, const T *values) {     \
        LOG(INFO) << "LsmioPlugin::DoPutSync(): " << std::endl;                     \
        WriteVariable(variable, values, adios2::Mode::Sync);                        \
    }                                                                               \
                                                                                    \
    void LsmioPlugin::DoPutDeferred(core::Variable<T> &variable, const T *values) { \
        LOG(INFO) << "LsmioPlugin::DoPutDeferred(): " << std::endl;                 \
        WriteVariable(variable, values, adios2::Mode::Deferred);                    \
    }

ADIOS2_FOREACH_STDTYPE_1ARG(declare)
#undef declare

// Values are put as they arrive and the metadata at Close, so there is nothing to perform
void LsmioPlugin::PerformPuts() {
    LOG(INFO) << "LsmioPlugin::PerformPuts(): " << std::endl;
}

/*
void LsmioPlugin::Flush(const int transportIndex) {
  LOG(INFO) << "LsmioPlugin::Flush(): TODO:" << std::endl;
}
*/

}  // namespace lsmio

extern "C" {

lsmio::LsmioPlugin *EngineCreate(adios2::core::IO &io, const std::string &name,
                                 const adios2::Mode mode, adios2::helper::Comm comm) {
    LOG(INFO) << "LsmioPlugin: EngineCreate: " << std::endl;
    return new lsmio::LsmioPlugin(io, name, mode, comm.Duplicate());
}

void EngineDestroy(lsmio::LsmioPlugin *obj) {
    LOG(INFO) << "LsmioPlugin::EngineDestroy: " << std::endl;
    delete obj;
}
}
