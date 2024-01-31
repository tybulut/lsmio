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

#include <lsmio/manager/store/store_ldb.hpp>


const std::string TEST_DIR_LDB = "";

TEST(lsmioLevelDB, Flush) {
  bool success = true;
  std::string value;

  std::string key1 = "serdar";
  std::string key2 = "bulut";
  std::string value1 = "alpino";
  std::string value2 = "teomos";

  std::string dbName = "test-ldb-store-flush.db";
  std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;

  lsmio::LSMIOStoreLDB lc(dbPath);
  LOG(INFO) << "Created a test database called: " << dbPath << std::endl;

  success = lc.put(key1, value1);
  EXPECT_EQ(success, true);

  success = lc.get(key1, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key1: " << value << std::endl;
  EXPECT_EQ(value, value1);

  success = lc.put(key2, value2);
  EXPECT_EQ(success, true);

  success = lc.get(key2, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key2: " << value << std::endl;
  EXPECT_EQ(value, value2);

  success = lc.append(key1, value2);
  EXPECT_EQ(success, true);

  success = lc.get(key1, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value1+value2 for key2: " << value << std::endl;
  EXPECT_EQ(value, (value1 + value2));

  success = lc.del(key1, false);
  EXPECT_EQ(success, true);

  success = lc.del(key2, false);
  EXPECT_EQ(success, true);
}


TEST(lsmioLevelDB, Deferred) {
  bool success = true;
  std::string value;

  std::string key1 = "serdar";
  std::string key2 = "bulut";
  std::string value1 = "alpino";
  std::string value2 = "teomos";

  std::string dbName = "test-ldb-store-deferred.db";
  std::string dbPath = TEST_DIR_LDB.empty() ? dbName : TEST_DIR_LDB + "/" + dbName;


  lsmio::LSMIOStoreLDB lc(dbPath);
  LOG(INFO) << "Created a test database called: " << dbPath << std::endl;

  success = lc.put(key1, value1, false);
  EXPECT_EQ(success, true);

  success = lc.put(key2, value2, false);
  EXPECT_EQ(success, true);

  success = lc.readBarrier();
  EXPECT_EQ(success, true);

  success = lc.get(key1, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key1: " << value << std::endl;
  EXPECT_EQ(value, value1);

  success = lc.get(key2, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key2: " << value << std::endl;
  EXPECT_EQ(value, value2);

  success = lc.del(key1);
  EXPECT_EQ(success, true);

  success = lc.del(key2);
  EXPECT_EQ(success, true);

  success = lc.writeBarrier();
  EXPECT_EQ(success, true);
}

