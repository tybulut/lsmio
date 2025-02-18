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
#include <mpi.h>

#include <iostream>
#include <lsmio/lsmio.hpp>
#include <stdexcept>
#include <vector>

#include "test_mpi_utils.hpp"

#if ADIOS2_USE_MPI
#else
#error "ERROR: ADIOS2 does not have MPI (ADIOS2_USE_MPI=0)"
#endif

#include <cstdint>

#include <algorithm>
#include <array>
#include <limits>
#include <string>
#include <vector>

#ifdef _MSC_VER
#define NOMINMAX
#endif

// Test data for each type.  Make sure our values exceed the range of the
// previous size to make sure we all bytes for each element
struct SmallTestData
{
    std::string S1 = "Testing ADIOS2 String type";

    // These shoudl be able to use std::array like the rest of the pieces
    // but the XL compiler seems to have some bad code generation surounding
    // it that results in a double-free corruption.  Switching to std::vector
    // bypasses the problem
    std::vector<std::string> S1array = {"one"};
    std::vector<std::string> S3 = {"one", "two", "three"};

    std::array<int8_t, 10> I8 = {{0, 1, -2, 3, -4, 5, -6, 7, -8, 9}};
    std::array<int16_t, 10> I16 = {{512, 513, -510, 515, -508, 517, -506, 519, -504, 521}};
    std::array<int32_t, 10> I32 = {
        {131072, 131073, -131070, 131075, -131068, 131077, -131066, 131079, -131064, 131081}};
    std::array<int64_t, 10> I64 = {{8589934592, 8589934593, -8589934590, 8589934595, -8589934588,
                                    8589934597, -8589934586, 8589934599, -8589934584, 8589934601}};
    std::array<uint8_t, 10> U8 = {{128, 129, 130, 131, 132, 133, 134, 135, 136, 137}};
    std::array<uint16_t, 10> U16 = {
        {32768, 32769, 32770, 32771, 32772, 32773, 32774, 32775, 32776, 32777}};
    std::array<uint32_t, 10> U32 = {{2147483648, 2147483649, 2147483650, 2147483651, 2147483652,
                                     2147483653, 2147483654, 2147483655, 2147483656, 2147483657}};
    std::array<uint64_t, 10> U64 = {
        {9223372036854775808UL, 9223372036854775809UL, 9223372036854775810UL, 9223372036854775811UL,
         9223372036854775812UL, 9223372036854775813UL, 9223372036854775814UL, 9223372036854775815UL,
         9223372036854775816UL, 9223372036854775817UL}};
    std::array<float, 10> R32 = {{0.1f, 1.1f, 2.1f, 3.1f, 4.1f, 5.1f, 6.1f, 7.1f, 8.1f, 9.1f}};
    std::array<double, 10> R64 = {{10.2, 11.2, 12.2, 13.2, 14.2, 15.2, 16.2, 17.2, 18.2, 19.2}};
    std::array<long double, 10> R128 = {
        {410.2, 411.2, 412.2, 413.2, 414.2, 415.2, 416.2, 417.2, 418.2, 419.2}};

    std::array<std::complex<float>, 10> CR32 = {
        {std::complex<float>(0.1f, 1.1f), std::complex<float>(1.1f, 2.1f),
         std::complex<float>(2.1f, 3.1f), std::complex<float>(3.1f, 4.1f),
         std::complex<float>(4.1f, 5.1f), std::complex<float>(5.1f, 6.1f),
         std::complex<float>(6.1f, 7.1f), std::complex<float>(7.1f, 8.1f),
         std::complex<float>(8.1f, 9.1f), std::complex<float>(9.1f, 10.1f)}};

    std::array<std::complex<double>, 10> CR64 = {
        {std::complex<double>(10.2, 11.2), std::complex<double>(11.2, 12.2),
         std::complex<double>(12.2, 13.2), std::complex<double>(13.2, 14.2),
         std::complex<double>(14.2, 15.2), std::complex<double>(15.2, 16.2),
         std::complex<double>(16.2, 17.2), std::complex<double>(17.2, 18.2),
         std::complex<double>(18.2, 19.2), std::complex<double>(19.2, 20.2)}};

    std::array<char, 10> CHAR = {{'a', 'b', 'c', 'y', 'z', 'A', 'B', 'C', 'Y', 'Z'}};
    std::array<bool, 10> TF = {{true, false, true, true, false, false, true, false, false, true}};
};

SmallTestData generateNewSmallTestData(SmallTestData in, size_t step, size_t rank, size_t size)
{
    size_t j = rank + 1 + step * size;
    std::for_each(in.I8.begin(), in.I8.end(), [&](int8_t &v) { v += static_cast<int8_t>(j); });
    std::for_each(in.I16.begin(), in.I16.end(), [&](int16_t &v) { v += static_cast<int16_t>(j); });
    std::for_each(in.I32.begin(), in.I32.end(), [&](int32_t &v) { v += static_cast<int32_t>(j); });
    std::for_each(in.I64.begin(), in.I64.end(), [&](int64_t &v) { v += static_cast<int64_t>(j); });
    std::for_each(in.U8.begin(), in.U8.end(), [&](uint8_t &v) { v += static_cast<uint8_t>(j); });
    std::for_each(in.U16.begin(), in.U16.end(),
                  [&](uint16_t &v) { v += static_cast<uint16_t>(j); });
    std::for_each(in.U32.begin(), in.U32.end(),
                  [&](uint32_t &v) { v += static_cast<uint32_t>(j); });
    std::for_each(in.U64.begin(), in.U64.end(),
                  [&](uint64_t &v) { v += static_cast<uint64_t>(j); });
    std::for_each(in.R32.begin(), in.R32.end(), [&](float &v) { v += static_cast<float>(j); });
    std::for_each(in.R64.begin(), in.R64.end(), [&](double &v) { v += static_cast<double>(j); });
    std::for_each(in.R128.begin(), in.R128.end(), [&](long double &v) { v += j; });

    std::for_each(in.CR32.begin(), in.CR32.end(), [&](std::complex<float> &v) {
        v.real(v.real() + static_cast<float>(j));
        v.imag(v.imag() + static_cast<float>(j));
    });
    std::for_each(in.CR64.begin(), in.CR64.end(), [&](std::complex<double> &v) {
        v.real(v.real() + static_cast<double>(j));
        v.imag(v.imag() + static_cast<double>(j));
    });

    std::for_each(in.CHAR.begin(), in.CHAR.end(), [&](char &v) {
        char jc = static_cast<char>(j);
        char inc = jc % ('z' - 'a');
        v += inc;
        if (v > 'z')
        {
            v = 'a' + (v - 'z') - 1;
        }
        else if (v > 'Z' && v < 'a')
        {
            v = 'A' + (v - 'Z') - 1;
        }
    });

    return in;
}

void UpdateSmallTestData(SmallTestData &in, int step, int rank, int size)
{
    int j = rank + 1 + step * size;
    std::for_each(in.I8.begin(), in.I8.end(), [&](int8_t &v) { v += j; });
    std::for_each(in.I16.begin(), in.I16.end(), [&](int16_t &v) { v += j; });
    std::for_each(in.I32.begin(), in.I32.end(), [&](int32_t &v) { v += j; });
    std::for_each(in.I64.begin(), in.I64.end(), [&](int64_t &v) { v += j; });
    std::for_each(in.U8.begin(), in.U8.end(), [&](uint8_t &v) { v += j; });
    std::for_each(in.U16.begin(), in.U16.end(), [&](uint16_t &v) { v += j; });
    std::for_each(in.U32.begin(), in.U32.end(), [&](uint32_t &v) { v += j; });
    std::for_each(in.U64.begin(), in.U64.end(), [&](uint64_t &v) { v += j; });
    std::for_each(in.R32.begin(), in.R32.end(), [&](float &v) { v += j; });
    std::for_each(in.R64.begin(), in.R64.end(), [&](double &v) { v += j; });
    std::for_each(in.R128.begin(), in.R128.end(), [&](long double &v) { v += j; });

    std::for_each(in.CR32.begin(), in.CR32.end(), [&](std::complex<float> &v) {
        v.real(v.real() + static_cast<float>(j));
        v.imag(v.imag() + static_cast<float>(j));
    });
    std::for_each(in.CR64.begin(), in.CR64.end(), [&](std::complex<double> &v) {
        v.real(v.real() + static_cast<double>(j));
        v.imag(v.imag() + static_cast<double>(j));
    });

    std::for_each(in.CHAR.begin(), in.CHAR.end(), [&](char &v) {
        char jc = static_cast<char>(j);
        char inc = jc % ('z' - 'a');
        v += inc;
        if (v > 'z')
        {
            v = 'a' + (v - 'z') - 1;
        }
        else if (v > 'Z' && v < 'a')
        {
            v = 'A' + (v - 'Z') - 1;
        }
    });
}


class Hdf5Test : public testing::Test {
  public:
    SmallTestData m_TestData;
};


TEST_F(Hdf5Test, ArrayTest) {
    const std::string fName = "." + std::string(&adios2::PathSeparator, 1) + "test-mpi-hdf5-basic.h5";
    LOG(INFO) << "Hdf5Test::BasicTest:: starting: " << fName;

    int numProcesses, worldRank;
    MPI_Comm_size(MPI_COMM_WORLD, &numProcesses);
    MPI_Comm_rank(MPI_COMM_WORLD, &worldRank);

    const std::string zero = std::to_string(0);
    const std::string s1_Array = std::string("s1_Array_") + zero;
    const std::string i8_Array = std::string("i8_Array_") + zero;
    const std::string i16_Array = std::string("i16_Array_") + zero;
    const std::string i32_Array = std::string("i32_Array_") + zero;
    const std::string i64_Array = std::string("i64_Array_") + zero;
    const std::string u8_Array = std::string("u8_Array_") + zero;
    const std::string u16_Array = std::string("u16_Array_") + zero;
    const std::string u32_Array = std::string("u32_Array_") + zero;
    const std::string u64_Array = std::string("u64_Array_") + zero;
    const std::string r32_Array = std::string("r32_Array_") + zero;
    const std::string r64_Array = std::string("r64_Array_") + zero;

    SmallTestData currentTestData = generateNewSmallTestData(m_TestData, 0, 0, 0);

    LOG(INFO) << "Hdf5Test::BasicTest: rank: " << worldRank;

    adios2::ADIOS adios(MPI_COMM_WORLD);
    MPI_Barrier(MPI_COMM_WORLD);

    {
        adios2::IO io = adios.DeclareIO("TestIO");
        io.SetEngine("HDF5");

        adios2::Engine engine = io.Open(fName, adios2::Mode::Write);

        // Declare Single Value Attributes
        io.DefineAttribute<std::string>(s1_Array, currentTestData.S3.data(),
                                        currentTestData.S3.size());

        io.DefineAttribute<int8_t>(i8_Array, currentTestData.I8.data(), currentTestData.I8.size());
        io.DefineAttribute<int16_t>(i16_Array, currentTestData.I16.data(),
                                    currentTestData.I16.size());
        io.DefineAttribute<int32_t>(i32_Array, currentTestData.I32.data(),
                                    currentTestData.I32.size());
        io.DefineAttribute<int64_t>(i64_Array, currentTestData.I64.data(),
                                    currentTestData.I64.size());

        io.DefineAttribute<uint8_t>(u8_Array, currentTestData.U8.data(), currentTestData.U8.size());
        io.DefineAttribute<uint16_t>(u16_Array, currentTestData.U16.data(),
                                     currentTestData.U16.size());
        io.DefineAttribute<uint32_t>(u32_Array, currentTestData.U32.data(),
                                     currentTestData.U32.size());
        io.DefineAttribute<uint64_t>(u64_Array, currentTestData.U64.data(),
                                     currentTestData.U64.size());

        io.DefineAttribute<float>(r32_Array, currentTestData.R32.data(),
                                  currentTestData.R32.size());
        io.DefineAttribute<double>(r64_Array, currentTestData.R64.data(),
                                   currentTestData.R64.size());

        // only attributes are written
        engine.Close();
    }

    MPI_Barrier(MPI_COMM_WORLD);
    {
        adios2::IO ioRead = adios.DeclareIO("ioRead");
        ioRead.SetEngine("HDF5");

        adios2::Engine bpRead = ioRead.Open(fName, adios2::Mode::Read);

        auto attr_s1 = ioRead.InquireAttribute<std::string>(s1_Array);

        auto attr_i8 = ioRead.InquireAttribute<int8_t>(i8_Array);
        auto attr_i16 = ioRead.InquireAttribute<int16_t>(i16_Array);
        auto attr_i32 = ioRead.InquireAttribute<int32_t>(i32_Array);
        auto attr_i64 = ioRead.InquireAttribute<int64_t>(i64_Array);

        auto attr_u8 = ioRead.InquireAttribute<uint8_t>(u8_Array);
        auto attr_u16 = ioRead.InquireAttribute<uint16_t>(u16_Array);
        auto attr_u32 = ioRead.InquireAttribute<uint32_t>(u32_Array);
        auto attr_u64 = ioRead.InquireAttribute<uint64_t>(u64_Array);

        auto attr_r32 = ioRead.InquireAttribute<float>(r32_Array);
        auto attr_r64 = ioRead.InquireAttribute<double>(r64_Array);

        EXPECT_TRUE(attr_s1);
        ASSERT_EQ(attr_s1.Name(), s1_Array);
        ASSERT_EQ(attr_s1.Data().size() == 1, false);
        ASSERT_EQ(attr_s1.Type(), adios2::GetType<std::string>());

        EXPECT_TRUE(attr_i8);
        ASSERT_EQ(attr_i8.Name(), i8_Array);
        ASSERT_EQ(attr_i8.Data().size() == 1, false);
        ASSERT_EQ(attr_i8.Type(), adios2::GetType<int8_t>());

        EXPECT_TRUE(attr_i16);
        ASSERT_EQ(attr_i16.Name(), i16_Array);
        ASSERT_EQ(attr_i16.Data().size() == 1, false);
        ASSERT_EQ(attr_i16.Type(), adios2::GetType<int16_t>());

        EXPECT_TRUE(attr_i32);
        ASSERT_EQ(attr_i32.Name(), i32_Array);
        ASSERT_EQ(attr_i32.Data().size() == 1, false);
        ASSERT_EQ(attr_i32.Type(), adios2::GetType<int32_t>());

        EXPECT_TRUE(attr_i64);
        ASSERT_EQ(attr_i64.Name(), i64_Array);
        ASSERT_EQ(attr_i64.Data().size() == 1, false);
        ASSERT_EQ(attr_i64.Type(), adios2::GetType<int64_t>());

        EXPECT_TRUE(attr_u8);
        ASSERT_EQ(attr_u8.Name(), u8_Array);
        ASSERT_EQ(attr_u8.Data().size() == 1, false);
        ASSERT_EQ(attr_u8.Type(), adios2::GetType<uint8_t>());

        EXPECT_TRUE(attr_u16);
        ASSERT_EQ(attr_u16.Name(), u16_Array);
        ASSERT_EQ(attr_u16.Data().size() == 1, false);
        ASSERT_EQ(attr_u16.Type(), adios2::GetType<uint16_t>());

        EXPECT_TRUE(attr_u32);
        ASSERT_EQ(attr_u32.Name(), u32_Array);
        ASSERT_EQ(attr_u32.Data().size() == 1, false);
        ASSERT_EQ(attr_u32.Type(), adios2::GetType<uint32_t>());

        EXPECT_TRUE(attr_u64);
        ASSERT_EQ(attr_u64.Name(), u64_Array);
        ASSERT_EQ(attr_u64.Data().size() == 1, false);
        ASSERT_EQ(attr_u64.Type(), adios2::GetType<uint64_t>());

        EXPECT_TRUE(attr_r32);
        ASSERT_EQ(attr_r32.Name(), r32_Array);
        ASSERT_EQ(attr_r32.Data().size() == 1, false);
        ASSERT_EQ(attr_r32.Type(), adios2::GetType<float>());

        EXPECT_TRUE(attr_r64);
        ASSERT_EQ(attr_r64.Name(), r64_Array);
        ASSERT_EQ(attr_r64.Data().size() == 1, false);
        ASSERT_EQ(attr_r64.Type(), adios2::GetType<double>());

        auto I8 = attr_i8.Data();
        auto I16 = attr_i16.Data();
        auto I32 = attr_i32.Data();
        auto I64 = attr_i64.Data();

        auto U8 = attr_u8.Data();
        auto U16 = attr_u16.Data();
        auto U32 = attr_u32.Data();
        auto U64 = attr_u64.Data();

        const size_t Nx = 10;
        for (size_t i = 0; i < Nx; ++i)
        {   
            EXPECT_EQ(I8[i], currentTestData.I8[i]);
            EXPECT_EQ(I16[i], currentTestData.I16[i]);
            EXPECT_EQ(I32[i], currentTestData.I32[i]);
            EXPECT_EQ(I64[i], currentTestData.I64[i]);

            EXPECT_EQ(U8[i], currentTestData.U8[i]);
            EXPECT_EQ(U16[i], currentTestData.U16[i]);
            EXPECT_EQ(U32[i], currentTestData.U32[i]);
            EXPECT_EQ(U64[i], currentTestData.U64[i]);
        }

        bpRead.Close();
    }

    LOG(INFO) << "Hdf5Test::BasicTest:: concluded: " << fName;
}

