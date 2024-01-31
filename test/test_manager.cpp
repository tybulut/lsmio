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

#include <lsmio/manager/manager.hpp>


const std::string TEST_DIR_MGR = "";

TEST(lsmioManager, Flush) {
  bool success = true;
  std::string value;

  std::string key1 = "serdar";
  std::string key2 = "leo";
  std::string value1 = "bulut";
  std::string value2 = "alp";

  std::string dbName = "test-mgr-store-flush.db";
  std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;

  lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
  LOG(INFO) << "Created a test database called: " << lm.getDbPath() << std::endl;

  EXPECT_EQ(lm.getDbPath(), dbPath);

  success = lm.put(key1, value1, true);
  EXPECT_EQ(success, true);

  success = lm.get(key1, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key1: wrote: " << value1 << std::endl;
  LOG(INFO) << "Test value for key1: read: " << value << std::endl;
  EXPECT_EQ(value, value1);

  success = lm.put(key2, value2, true);
  EXPECT_EQ(success, true);

  success = lm.get(key2, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key2: wrote: " << value2 << std::endl;
  LOG(INFO) << "Test value for key2: read: " << value << std::endl;
  EXPECT_EQ(value, value2);

  uint64_t rb, wb;
  uint64_t ro, wo;
  lm.getCounters(wb, rb, wo, ro);

  LOG(INFO) << "LSMIOManager::counters: writeB: " << wb << " readB: " << rb << std::endl;
  EXPECT_EQ(rb, (value1.length() + value2.length()));
  EXPECT_EQ(wb, (value1.length() + value2.length()));

  LOG(INFO) << "LSMIOManager::counters: writeO: " << wo << " readO: " << ro << std::endl;
  EXPECT_EQ(ro, 2);
  EXPECT_EQ(wo, 2);

  success = lm.del(key1, false);
  EXPECT_EQ(success, true);

  success = lm.del(key2, false);
  EXPECT_EQ(success, true);
}


TEST(lsmioManager, Deferred) {
  bool success = true;
  std::string value;

  std::string key1 = "serdar";
  std::string key2 = "bulut";
  std::string value1 = "alpino";
  std::string value2 = "teomos";

  std::string dbName = "test-mgr-store-deferred.db";
  std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;

  lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
  LOG(INFO) << "Created a test database called: " << lm.getDbPath() << std::endl;
  EXPECT_EQ(lm.getDbPath(), dbPath);

  success = lm.put(key1, value1);
  EXPECT_EQ(success, true);

  success = lm.put(key2, value2.c_str(), value2.length());
  EXPECT_EQ(success, true);

  success = lm.writeBarrier();
  EXPECT_EQ(success, true);

  success = lm.get(key1, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key1: " << value << std::endl;
  EXPECT_EQ(value, value1);

  success = lm.get(key2, &value);
  EXPECT_EQ(success, true);

  LOG(INFO) << "Test value for key2: " << value << std::endl;
  EXPECT_EQ(value, value2);

  success = lm.del(key1);
  EXPECT_EQ(success, true);

  success = lm.del(key2);
  EXPECT_EQ(success, true);
}


TEST(lsmioManager, ReOpen_Write) {
  bool success = true;
  std::string value;

  std::string key1 = "serdar";
  std::string key2 = "bulut";
  std::string value1 = "alpino";
  std::string value2 = "teomos";

  std::string dbName = "test-mgr-store-rewrite.db";
  std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;

  for(int i=0; i < 2; i++) {
    lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
    LOG(INFO) << ((i == 0) ? "Created" : "Opened")
              << " a RW test database called: " << lm.getDbPath() << std::endl;

    success = lm.put(key1, value1, true);
    EXPECT_EQ(success, true);

    success = lm.put(key2, value2, true);
    EXPECT_EQ(success, true);
  }
}

TEST(lsmioManager, ReOpen_Read) {
  bool success = true;
  std::string value;

  std::string key1 = "serdar";
  std::string key2 = "bulut";
  std::string value1 = "alpino";
  std::string value2 = "teomos";

  std::string dbName = "test-mgr-store-reread.db";
  std::string dbPath = TEST_DIR_MGR.empty() ? dbName : TEST_DIR_MGR + "/" + dbName;

  for(int i=0; i < 2; i++) {
    lsmio::LSMIOManager lm(dbName, TEST_DIR_MGR);
    LOG(INFO) << ((i == 0) ? "Created" : "Opened")
              << " a RW test database called: " << lm.getDbPath() << std::endl;

    if (i== 0) {
      success = lm.put(key1, value1, true);
      EXPECT_EQ(success, true);

      success = lm.put(key2, value2, true);
      EXPECT_EQ(success, true);
    }
    else {
      success = lm.get(key1, &value);
      LOG(INFO) << "ReOpen read test value for key1: " << value << std::endl;
      EXPECT_EQ(success, true);

      success = lm.get(key2, &value);
      LOG(INFO) << "ReOpen read test value for key2: " << value << std::endl;
      EXPECT_EQ(success, true);
    }
  }
}


int main(int argc, char **argv) {
  lsmio::initLSMIODebug(argv[0]);
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}

