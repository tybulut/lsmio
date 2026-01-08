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

#include <string>
#include <tuple>
#include <vector>

#include "lsmio_plugin.tcc"

using namespace adios2;

namespace lsmio {

LsmioPlugin::LsmioPlugin(core::IO &io, const std::string &name, const Mode mode, helper::Comm comm)
    : plugin::PluginEngineInterface(io, name, mode, comm.Duplicate()) {
    _dbName = name;
    Init();
}

LsmioPlugin::~LsmioPlugin() {
    LOG(INFO) << "LsmioPlugin::~LsmioPlugin(): " << std::endl;
    if (_lm) delete _lm;
    LOG(INFO) << "LsmioPlugin::~LsmioPlugin(): completed." << std::endl;
}

Dims convertStrToDims(const std::string &str) {
    Dims dims;

    if (str.size() > 2) {
        auto vals = str.substr(1, str.size() - 2);
        std::stringstream ss(vals);
        while (ss.good()) {
            std::string substr;
            std::getline(ss, substr, ',');
            dims.push_back(std::stoi(substr));
        }
    }

    return dims;
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

    bool overWrite = false;
    if (m_OpenMode == adios2::Mode::Write || m_OpenMode == adios2::Mode::Append) {
        LOG(INFO) << "LsmioPlugin::Init: Opening for writing..." << std::endl;

        if (m_OpenMode == adios2::Mode::Write) {
            overWrite = true;
        }
    }

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

    if (m_OpenMode == adios2::Mode::Read) {
        LOG(INFO) << "LsmioPlugin::Init: Opened for reading..." << std::endl;

        std::vector<std::tuple<std::string, std::string>> values;
        bool success = _lm->metaGetAll(&values);

        LOG(INFO) << "LsmioPlugin::Init: variableStoreKey success: [" << success << "]" << std::endl;

        for (const auto& [key, value] : values) {
            std::string name, typeStr, shapeStr, startStr, countStr;

            std::stringstream sStream(value);

            std::getline(sStream, name, ';');
            std::getline(sStream, typeStr, ';');
            std::getline(sStream, shapeStr, ';');
            std::getline(sStream, startStr, ';');
            std::getline(sStream, countStr);

            auto shape = convertStrToDims(shapeStr);
            auto start = convertStrToDims(startStr);
            auto count = convertStrToDims(countStr);

            const DataType type = helper::GetDataTypeFromString(typeStr);
            if (type == DataType::Struct) {
                // not supported
            }
#define declare_template_instantiation(T)          \
    else if (type == helper::GetDataType<T>()) {   \
        AddVariable<T>(name, shape, start, count); \
    }
            ADIOS2_FOREACH_STDTYPE_1ARG(declare_template_instantiation)
#undef declare_template_instantiation

            LOG(INFO) << "LsmioPlugin::Init: variableStoreKey: " << name << std::endl;
        }
    }

    LOG(INFO) << "LsmioPlugin::Init: completed..." << std::endl;
}

StepStatus LsmioPlugin::BeginStep(StepMode mode, const float timeoutSeconds) {
    LOG(INFO) << "LsmioPlugin::BeginStep(): " << std::endl;
    return StepStatus::OK;
}

void LsmioPlugin::PerformGets() { LOG(INFO) << "LsmioPlugin::PerformGets(): " << std::endl; }

size_t LsmioPlugin::CurrentStep() const {
    LOG(INFO) << "LsmioPlugin::CurrentStep(): " << std::endl;
    return _currentStep;
}

void LsmioPlugin::EndStep() {
    LOG(INFO) << "LsmioPlugin::EndStep(): " << std::endl;

    if (m_OpenMode == adios2::Mode::Write || m_OpenMode == adios2::Mode::Append) {
        PerformPuts();
    }

    _currentStep++;
}

void LsmioPlugin::DoClose(const int transportIndex) {
    LOG(INFO) << "LsmioPlugin::DoClose(): " << std::endl;
    PerformPuts();
    if (_lm) _lm->close();
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

void LsmioPlugin::PerformPuts() {
    LOG(INFO) << "LsmioPlugin::PerformPuts(): " << std::endl;
    WriteVarsFromIO(adios2::Mode::Deferred);
}

/*
void LsmioPlugin::Flush(const int transportIndex) {
  LOG(INFO) << "LsmioPlugin::Flush(): TODO:" << std::endl;
}
*/

void LsmioPlugin::WriteVarsFromIO(const Mode launch) {
    bool isSync = (launch == Mode::Sync) ? true : false;
    std::string keyTypes;
    bool success;

    LOG(INFO) << "LsmioPlugin::WriteVarsFromIO(): Begin..." << std::endl;
    const core::VarMap &variables = m_IO.GetVariables();
    for (const auto &vpair : variables) {
        const std::string &varName = vpair.first;
        LOG(INFO) << "LsmioPlugin::WriteVarsFromIO(): " << varName << std::endl;

        const DataType varType = vpair.second->m_Type;
#define declare_template_instantiation(T)                        \
    if (varType == helper::GetDataType<T>()) {                   \
        core::Variable<T> *v = m_IO.InquireVariable<T>(varName); \
        if (!v) {                                                \
            return;                                              \
        }                                                        \
        keyTypes = WriteVariableInfo(*v);                        \
        success = _lm->metaPut(v->m_Name, keyTypes, isSync);     \
    }

        ADIOS2_FOREACH_STDTYPE_1ARG(declare_template_instantiation)
#undef declare_template_instantiation
    }
}

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
