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
#include <stdexcept>
#include <vector>

#include <adios2.h>
#include <gtest/gtest.h>

#include <lsmio/lsmio.hpp>


void testPluginWriter(adios2::ADIOS &adios, const std::string &testKey,
                                      const std::string &testValue) {
  adios2::IO io = adios.DeclareIO("test-plugin-writer");
  io.SetEngine("Plugin");
  adios2::Params params;
  params["PluginName"] = "LSMIOPlugin";
  params["PluginLibrary"] = "liblsmio_adios";
  params["FileName"] = "test-plugin.db";
  //params["verbose"] = "5";
  io.SetParameters(params);

  adios2::Variable<std::string> varKey;
  adios2::Engine writer = io.Open("test-plugin.bp", adios2::Mode::Write);

  for(int i=0; i < 10; i++) {
    std::string testKeyA = testKey + ":" + std::to_string(i);
    varKey = io.InquireVariable<std::string>(testKeyA);
    if (! varKey) {
      varKey = io.DefineVariable<std::string>(testKeyA);
    }

    //writer.Put(varKey, testValue); // Sync: send value
    writer.Put(varKey, &testValue); // Deferred: send &value
  }

  writer.PerformPuts();
  LOG(INFO) << "Wrote: " << testKey << "[0-1000]: " << testValue << std::endl;

  writer.Close();
}

void testPluginReader(adios2::ADIOS &adios, const std::string &testKey,
                                            std::vector<std::string> messages) {
  adios2::IO io = adios.DeclareIO("test-plugin-reader");
  io.SetEngine("Plugin");
  adios2::Params params;
  params["PluginName"] = "LSMIOPlugin";
  params["PluginLibrary"] = "liblsmio_adios";
  params["FileName"] = "test-plugin.db";
  io.SetParameters(params);

  adios2::Variable<std::string> varKey;
  adios2::Engine reader = io.Open("test-plugin.db", adios2::Mode::Read);

  std::string message;
  for(int i=0; i < 10; i++) {
    std::string testKeyA = testKey + ":" + std::to_string(i);
    varKey = io.InquireVariable<std::string>(testKeyA);
    reader.Get(varKey, message);
    messages.push_back(message);
  }

  LOG(INFO) << "Read: " << message << std::endl;
  reader.Close();
}


TEST(ADIOS, Plugin) {
  const std::string testKey = "Greeting";
  const std::string testValue = "Test Plugin Greeting";
  std::vector<std::string> messages;

  try {
    adios2::ADIOS adios;

    testPluginWriter(adios, testKey, testValue);
    testPluginReader(adios, testKey, messages);
  }
  catch (const std::exception& e) {
    FAIL() << "Adios throws an exception: " << e.what() << ".";
  }

  for(int i=0; i < messages.size(); i++) {
    EXPECT_EQ(testValue, messages[i]);
  }
}

