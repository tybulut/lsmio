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
#include <gtest/gtest.h>

#include <lsmio/posix/posix.hpp>

const std::string TEST_DIR_PSX = "";

TEST(lsmioPosix, Stream) {
  std::string value;

  const char *file1 = "serdar";
  const char *file2 = "bulut";
  std::string value1 = "alpino";
  std::string value2 = "teomos";

  std::string dbName = "test-psx-store-stream.db";
  std::string dbPath = TEST_DIR_PSX.empty() ? dbName : TEST_DIR_PSX + "/" + dbName;

  EXPECT_TRUE(lsmio::LSMIOStream::initialize(dbName, TEST_DIR_PSX));
  LOG(INFO) << "Created a test database called: " << dbName << std::endl;

  lsmio::LSMIOStream ls1;
  ls1.open(file1);
  ls1.write(value1.c_str(), value1.size());

  lsmio::LSMIOStream ls2(file2);
  ls2.write(value2.c_str(), value2.size());

  EXPECT_TRUE(lsmio::LSMIOStream::writeBarrier());

  char rVal1[value1.size()];
  char rVal2[value2.size()];

  ls1.seekp(0);
  ls1.read(rVal1, value1.size());
  value.assign(rVal1, value1.size());

  LOG(INFO) << "Test value for file1: " << value << std::endl;
  EXPECT_EQ(value, value1);

  ls2.seekp(0);
  ls2.read(rVal2, value2.size());
  value.assign(rVal2, value2.size());

  LOG(INFO) << "Test value for file2: " << value << std::endl;
  EXPECT_EQ(value, value2);

  EXPECT_TRUE(lsmio::LSMIOStream::cleanup());
}


TEST(lsmioPosix, StreamMulti) {
  bool success = true;
  std::string value;

  const char *file1 = "serdarM";
  std::string value1 = "alpinoM";
  std::string value2 = "teomosM";

  std::string dbName = "test-psx-store-multi.db";
  std::string dbPath = TEST_DIR_PSX.empty() ? dbName : TEST_DIR_PSX + "/" + dbName;

  EXPECT_TRUE(lsmio::LSMIOStream::initialize(dbName, TEST_DIR_PSX));
  LOG(INFO) << "Created a test database called: " << dbName << std::endl;

  lsmio::LSMIOStream ls1;
  ls1.open(file1);
  ls1.write(value1.c_str(), value1.size());
  ls1.write(value2);

  EXPECT_TRUE(lsmio::LSMIOStream::writeBarrier());

  char rVal1[value1.size()];
  char rVal2[value2.size()];

  ls1.seekp(0);
  ls1.read(rVal1, value1.size());
  value.assign(rVal1, value1.size());

  LOG(INFO) << "Test value for file1: " << value << std::endl;
  EXPECT_EQ(value, value1);

  ls1.read(rVal2, value2.size());
  value.assign(rVal2, value2.size());

  LOG(INFO) << "Test value for file1: " << value << std::endl;
  EXPECT_EQ(value, value2);

  EXPECT_TRUE(lsmio::LSMIOStream::cleanup());
}

int main(int argc, char **argv) {
  lsmio::initLSMIODebug(argv[0]);
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}

