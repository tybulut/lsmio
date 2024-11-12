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

#include <adios2.h>

#include <iostream>
#include <lsmio/lsmio.hpp>

#include "bm_base.hpp"

#if ADIOS2_USE_MPI
#else
#error "ERROR: ADIOS2 does not have MPI (ADIOS2_USE_MPI=0)"
#endif

class BMAdios : public BMBase {
  protected:
    adios2::ADIOS *_adios = nullptr;
    adios2::IO _io;
    adios2::Engine _reader;
    adios2::Engine _writer;
    std::string _ioName;

    virtual bool doRead(const std::string key, std::string *value) {
        adios2::Variable<std::string> varKey = _io.InquireVariable<std::string>(key);
        _reader.Get(varKey, value);
        return true;
    }

    virtual bool doWrite(const std::string key, const std::string value) {
        adios2::Variable<std::string> varKey = _io.DefineVariable<std::string>(key);
        if (lsmio::gConfigLSMIO.alwaysFlush) {
            _writer.Put(varKey, value, adios2::Mode::Sync);
        } else {
            _writer.Put(varKey, &value);  // deferred
        }
        return true;
    }

    virtual int writePrepare(bool opt) {
        std::string fnPrefix = std::string("bm:plugin:") + std::to_string(gConfigBM.useLSMIOPlugin);
        _ioName = fnPrefix + "-writer";

        adios2::Params params;
        if (gConfigBM.enableCollectiveIO) {
            _adios = new adios2::ADIOS(MPI_COMM_WORLD);
            if (lsmio::gConfigLSMIO.mpiAggType != lsmio::MPIAggType::Shared)
                params["AggregationType"] = "TwoLevelShm";
            else
                params["AggregationType"] = "EveryoneWrites";
        } else
            _adios = new adios2::ADIOS();
        _io = _adios->DeclareIO(_ioName);

        params["Threads"] = "0";
        params["BufferChunkSize"] = std::to_string(lsmio::gConfigLSMIO.writeBufferSize);
        params["StripeSize"] = std::to_string(lsmio::gConfigLSMIO.transferSize);
        params["MinDeferredSize"] = std::to_string(lsmio::gConfigLSMIO.transferSize);

        if (gConfigBM.useLSMIOPlugin) {
            _io.SetEngine("plugin");
            params["PluginName"] = "LSMIOPlugin";
            params["PluginLibrary"] = "liblsmio_adios";
            params["FileName"] =
                genDBPath(gConfigBM.useLSMIOPlugin, lsmio::gConfigLSMIO.alwaysFlush);
        }
        _io.SetParameters(params);
        _writer = _io.Open(genDBPath(gConfigBM.useLSMIOPlugin, lsmio::gConfigLSMIO.alwaysFlush),
                           adios2::Mode::Write);
        _writer.BeginStep();
        return 0;
    }

    virtual bool doWriteFinalize() {
        LOG(INFO) << "benchWrite: measured before FLUSH: " << _bm.sofar() << std::endl;
        _benchResultsWrite += std::string("/-- before FLUSH: ") +
                              " ----> MICROSECONDS: " + std::to_string(_bm.sofar()) + "\n";
        _writer.PerformPuts();
        //_adios->Flush(); // EnginePlugin fails with Flush() call

        _writer.EndStep();
        _writer.Close();
        return true;
    }

    int writeCleanup() {
        _adios->RemoveIO(_ioName);
        delete _adios;
        _adios = nullptr;
        _ioName = "";
        return 0;
    }

    virtual int readPrepare(bool opt) {
        std::string fnPrefix = std::string("bm:plugin:") + std::to_string(gConfigBM.useLSMIOPlugin);
        _ioName = fnPrefix + "-reader";

        adios2::Params params;
        if (gConfigBM.enableCollectiveIO) {
            _adios = new adios2::ADIOS(MPI_COMM_WORLD);
            if (lsmio::gConfigLSMIO.mpiAggType != lsmio::MPIAggType::Shared)
                params["AggregationType"] = "TwoLevelShm";
            else
                params["AggregationType"] = "EveryoneWrites";
        } else
            _adios = new adios2::ADIOS();
        _io = _adios->DeclareIO(_ioName);

        params["Threads"] = "0";
        params["BufferChunkSize"] = std::to_string(lsmio::gConfigLSMIO.writeBufferSize);
        params["StripeSize"] = std::to_string(lsmio::gConfigLSMIO.transferSize);
        params["MinDeferredSize"] = std::to_string(lsmio::gConfigLSMIO.transferSize);

        if (gConfigBM.useLSMIOPlugin) {
            _io.SetEngine("plugin");
            params["PluginName"] = "LSMIOPlugin";
            params["PluginLibrary"] = "liblsmio_adios";
            params["FileName"] =
                genDBPath(gConfigBM.useLSMIOPlugin, lsmio::gConfigLSMIO.alwaysFlush);
        }
        _io.SetParameters(params);
        _reader = _io.Open(genDBPath(gConfigBM.useLSMIOPlugin, lsmio::gConfigLSMIO.alwaysFlush),
                           adios2::Mode::Read);
        _reader.BeginStep();
        return 0;
    }

    virtual bool doReadFinalize() {
        _reader.EndStep();
        _reader.Close();
        return true;
    }

    int readCleanup() {
        _adios->RemoveIO(_ioName);
        delete _adios;
        _adios = nullptr;
        _ioName = "";
        return 0;
    }
};

int main(int argc, char **argv) {
    int exitCode = 0;
    bool usePlugin[2] = {false, true};
    bool alwaysFlush[2] = {false, true};
    bool bloomFilters[2] = {false, true};

    exitCode += BMBase::beginMain(argc, argv);

    BMAdios bm;

    for (int j = 0; j < 2; j++) {
        for (int k = 0; k < 2; k++) {
            if (gConfigBM.loopAll) {
                lsmio::gConfigLSMIO.alwaysFlush = alwaysFlush[j];
                gConfigBM.useLSMIOPlugin = usePlugin[k];
            }

            std::string bmPrefix = std::string("AdiosDB Flush: ") +
                                   (lsmio::gConfigLSMIO.alwaysFlush ? "true " : "false") +
                                   " Plg: " + (gConfigBM.useLSMIOPlugin ? "true " : "false");
            LOG(INFO) << "Testing: " << bmPrefix << std::endl;

            exitCode += bm.benchSuite(bmPrefix);

            if (!gConfigBM.loopAll) break;
        }

        if (!gConfigBM.loopAll) break;
    }

    bm.writeBenchmarkResults();

    exitCode += BMBase::endMain();

    if (exitCode) {
        LOG(WARNING) << "BMAdios exitCode: " << exitCode << std::endl;
    }

    return exitCode;
}
