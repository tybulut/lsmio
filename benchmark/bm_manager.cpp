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

#include <iostream>
#include <lsmio/manager/manager.hpp>

#include "bm_base.hpp"

class BMManager : public BMBase {
  protected:
    lsmio::LSMIOManager *_lm = nullptr;

    virtual bool doRead(const std::string key, std::string *value) { return _lm->get(key, value); }

    virtual bool doWrite(const std::string key, const std::string value) {
        return _lm->put(key, value, lsmio::gConfigLSMIO.alwaysFlush);
    }

    virtual int writePrepare(bool opt) {
        if (gConfigBM.enableCollectiveIO)
            _lm = new lsmio::LSMIOManager(
                genDBPath(lsmio::gConfigLSMIO.alwaysFlush, lsmio::gConfigLSMIO.useBloomFilter), "",
                true, MPI_COMM_WORLD);
        else
            _lm = new lsmio::LSMIOManager(
                genDBPath(lsmio::gConfigLSMIO.alwaysFlush, lsmio::gConfigLSMIO.useBloomFilter), "",
                true);
        return 0;
    }

    virtual bool doWriteFinalize() {
        _lm->writeBarrier();
        _lm->close();
        return true;
    }

    virtual int writeCleanup() {
        delete _lm;
        _lm = nullptr;
        return 0;
    }

    virtual int readPrepare(bool opt) {
        if (gConfigBM.enableCollectiveIO)
            _lm = new lsmio::LSMIOManager(
                genDBPath(lsmio::gConfigLSMIO.alwaysFlush, lsmio::gConfigLSMIO.useBloomFilter), "",
                false, MPI_COMM_WORLD);
        else
            _lm = new lsmio::LSMIOManager(
                genDBPath(lsmio::gConfigLSMIO.alwaysFlush, lsmio::gConfigLSMIO.useBloomFilter), "",
                false);
        return 0;
    }

    virtual int readCleanup() {
        delete _lm;
        _lm = nullptr;
        return 0;
    }
};

int main(int argc, char **argv) {
    int exitCode = 0;
    bool alwaysFlush[2] = {false, true};
    bool bloomFilters[2] = {false, true};

    exitCode += BMBase::beginMain(argc, argv);

    BMManager bm;

    for (int j = 0; j < 2; j++) {
        for (int k = 0; k < 2; k++) {
            if (gConfigBM.loopAll) {
                lsmio::gConfigLSMIO.alwaysFlush = alwaysFlush[j];
                lsmio::gConfigLSMIO.useBloomFilter = bloomFilters[k];
            }

            std::string bmPrefix =
                std::string("LsmioMr Flush: ") +
                (lsmio::gConfigLSMIO.alwaysFlush ? "true " : "false") +
                " BLF: " + (lsmio::gConfigLSMIO.useBloomFilter ? "true " : "false");
            LOG(INFO) << "Testing: " << bmPrefix << std::endl;

            exitCode += bm.benchSuite(bmPrefix);

            if (!gConfigBM.loopAll) break;
        }

        if (!gConfigBM.loopAll) break;
    }

    bm.writeBenchmarkResults();

    exitCode += BMBase::endMain();

    if (exitCode) {
        LOG(WARNING) << "BMManager exitCode: " << exitCode << std::endl;
    }

    return exitCode;
}
