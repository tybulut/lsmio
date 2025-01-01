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
#include <gtest/gtest.h>

#include <iostream>
#include <lsmio/lsmio.hpp>
#include <stdexcept>
#include <vector>

void testAdiosWriter(adios2::ADIOS &adios, const std::string &testKey,
                     const std::string &testValue) {
    adios2::IO io = adios.DeclareIO("hello-world-writer");
    adios2::Variable<std::string> varKey = io.DefineVariable<std::string>(testKey);

    /*
      adios2::Params params;
      params["Threads"] = "2"; // Read side: Default = 0 (BP3/4/5)
      params["MaxBufferSize"] = "512Kb"; .// >= 16kb, Default = at EndStep
      params["BufferGrowthFactor"] = "1.5"; // Default = 1.05
      params["FlushStepsCount"] = "5"; // Default = 1
      io.SetParameters(params);

      io.SetEngine("SST"); // Sustainable Staging Transport: Leverages RDMA network

      const unsigned int file =
        io.AddTransport("File", {
                                  {"Library", "POSIX"}, // POSIX (UNIX), FStream (Windows), stdio, IME (DDN)
                                  {"Name","file2.bp" }
                                });

        io.AddTransport("WAN", {
                                 {"Library", "Zmq"},
                                 {"IP","127.0.0.1" },
                                 {"Port","80"}
                               });
    */

    adios2::Engine writer = io.Open("hello-world-cpp.bp", adios2::Mode::Write);
    writer.BeginStep();

    writer.Put(varKey, testValue);

    writer.EndStep();
    writer.Close();

    LOG(INFO) << "testAdiosWriter: wrote: " << testValue << std::endl;
}

std::string testAdiosReader(adios2::ADIOS &adios, const std::string &testKey) {
    adios2::IO io = adios.DeclareIO("hello-world-reader");
    adios2::Engine reader = io.Open("hello-world-cpp.bp", adios2::Mode::Read);
    reader.BeginStep();

    adios2::Variable<std::string> varKey = io.InquireVariable<std::string>(testKey);
    std::string greeting;

    reader.Get(varKey, greeting);

    reader.EndStep();
    reader.Close();

    return greeting;
}

TEST(ADIOS, Basic) {
    const std::string testKey = "Greeting";
    const std::string testValue = "Test Plugin Greeting";
    std::string message;

    try {
        adios2::ADIOS adios;

        testAdiosWriter(adios, testKey, testValue);
        message = testAdiosReader(adios, testKey);
        LOG(INFO) << "Message read: " << message << std::endl;
    } catch (const std::exception &e) {
        FAIL() << "Adios throws an exception: " << e.what() << ".";
    }

    EXPECT_EQ(testValue, message);
}

int main(int argc, char **argv) {
    lsmio::initLSMIODebug(argv[0]);
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
