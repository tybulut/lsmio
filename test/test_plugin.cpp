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

#include <climits>
#include <complex>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <lsmio/lsmio.hpp>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

void testPluginWriter(adios2::ADIOS &adios, const std::string &testKey,
                      const std::string &testValue) {
    adios2::IO io = adios.DeclareIO("test-plugin-writer");
    io.SetEngine("Plugin");
    adios2::Params params;
    params["PluginName"] = "LSMIOPlugin";
    params["PluginLibrary"] = "liblsmio_adios";
    params["FileName"] = "test-plugin.db";
    // params["verbose"] = "5";
    io.SetParameters(params);

    adios2::Variable<std::string> varKey;
    adios2::Engine writer = io.Open("test-plugin.bp", adios2::Mode::Write);

    for (int i = 0; i < 10; i++) {
        std::string testKeyA = testKey + ":" + std::to_string(i);
        varKey = io.InquireVariable<std::string>(testKeyA);
        if (!varKey) {
            varKey = io.DefineVariable<std::string>(testKeyA);
        }

        // writer.Put(varKey, testValue); // Sync: send value
        writer.Put(varKey, &testValue);  // Deferred: send &value
    }

    writer.PerformPuts();
    LOG(INFO) << "Wrote: " << testKey << "[0-1000]: " << testValue << std::endl;

    writer.Close();
}

void testPluginReader(adios2::ADIOS &adios, const std::string &testKey,
                      std::vector<std::string> &messages) {
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
    for (int i = 0; i < 10; i++) {
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
    } catch (const std::exception &e) {
        FAIL() << "Adios throws an exception: " << e.what() << ".";
    }

    ASSERT_EQ(messages.size(), 10u);
    for (int i = 0; i < messages.size(); i++) {
        EXPECT_EQ(testValue, messages[i]);
    }
}

namespace {

adios2::Params pluginParams(const std::string &fileName) {
    adios2::Params params;
    params["PluginName"] = "LSMIOPlugin";
    params["PluginLibrary"] = "liblsmio_adios";
    params["FileName"] = fileName;
    return params;
}

adios2::Engine openPlugin(adios2::ADIOS &adios, adios2::IO &io, const std::string &fileName,
                          adios2::Mode mode) {
    io.SetEngine("Plugin");
    io.SetParameters(pluginParams(fileName));
    return io.Open(fileName, mode);
}

template <typename T>
void putArray(adios2::IO &io, adios2::Engine &writer, const std::string &name,
              const std::vector<T> &values, adios2::Mode mode = adios2::Mode::Sync) {
    adios2::Variable<T> var = io.DefineVariable<T>(name, {values.size()}, {0}, {values.size()});
    writer.Put(var, values.data(), mode);
}

template <typename T>
std::vector<T> getArray(adios2::IO &io, adios2::Engine &reader, const std::string &name) {
    std::vector<T> values;
    adios2::Variable<T> var = io.InquireVariable<T>(name);
    if (!var) throw std::runtime_error("variable not found: " + name);
    reader.Get(var, values, adios2::Mode::Sync);
    return values;
}

// Bit-for-bit comparison: EXPECT_EQ would treat -0.0 and 0.0 as equal
template <typename T>
bool sameBytes(const std::vector<T> &a, const std::vector<T> &b) {
    return a.size() == b.size() && std::memcmp(a.data(), b.data(), a.size() * sizeof(T)) == 0;
}

}  // namespace

// Numeric arrays round-trip bit for bit (values were once stored as 6-digit text)
TEST(ADIOS, PluginArrays) {
    const std::string fileName = "test-plugin-arrays.db";
    const std::vector<double> doubles = {1.0 / 3.0, -2.718281828459045, 6.02214076e23, 0.0};
    const std::vector<float> floats = {1.0f / 7.0f, -0.0f, 3.4028235e38f};
    const std::vector<int64_t> int64s = {INT64_MIN, -1, 0, 1234567890123456789LL};
    const std::vector<char> chars = {'a', ',', '\0', 'z'};
    const std::vector<std::complex<double>> complexes = {{1.0 / 3.0, -1.0 / 7.0}};
    const std::vector<double> deferred = {-1.0 / 11.0, 1e-300};
    const double scalar = 1.0 / 9.0;

    std::vector<double> doublesRead, deferredRead;
    std::vector<float> floatsRead;
    std::vector<int64_t> int64sRead;
    std::vector<char> charsRead;
    std::vector<std::complex<double>> complexesRead;
    double scalarRead = 0.0;

    try {
        adios2::ADIOS adios;

        adios2::IO wio = adios.DeclareIO("test-plugin-arrays-writer");
        adios2::Engine writer = openPlugin(adios, wio, fileName, adios2::Mode::Write);
        putArray(wio, writer, "doubles", doubles);
        putArray(wio, writer, "floats", floats);
        putArray(wio, writer, "int64s", int64s);
        putArray(wio, writer, "chars", chars);
        putArray(wio, writer, "complexes", complexes);
        putArray(wio, writer, "deferred", deferred, adios2::Mode::Deferred);
        adios2::Variable<double> varScalar = wio.DefineVariable<double>("scalar");
        writer.Put(varScalar, scalar, adios2::Mode::Sync);
        writer.PerformPuts();
        writer.Close();

        adios2::IO rio = adios.DeclareIO("test-plugin-arrays-reader");
        adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
        doublesRead = getArray<double>(rio, reader, "doubles");
        floatsRead = getArray<float>(rio, reader, "floats");
        int64sRead = getArray<int64_t>(rio, reader, "int64s");
        charsRead = getArray<char>(rio, reader, "chars");
        complexesRead = getArray<std::complex<double>>(rio, reader, "complexes");
        deferredRead = getArray<double>(rio, reader, "deferred");
        reader.Get(rio.InquireVariable<double>("scalar"), scalarRead, adios2::Mode::Sync);
        reader.Close();
    } catch (const std::exception &e) {
        FAIL() << "Adios throws an exception: " << e.what() << ".";
    }

    EXPECT_TRUE(sameBytes(doubles, doublesRead));
    EXPECT_TRUE(sameBytes(floats, floatsRead));
    EXPECT_TRUE(sameBytes(int64s, int64sRead));
    EXPECT_TRUE(sameBytes(chars, charsRead));
    EXPECT_TRUE(sameBytes(complexes, complexesRead));
    EXPECT_TRUE(sameBytes(deferred, deferredRead));
    EXPECT_EQ(scalar, scalarRead);
}

// Attributes are stored with the metadata record at Close and defined again on open for read
TEST(ADIOS, PluginAttributes) {
    const std::string fileName = "test-plugin-attributes.db";
    const std::string text = std::string("/data/%T/;a,b") + '\0' + "tail";
    const std::vector<std::string> texts = {"meshes", "", "x;y"};
    const std::vector<double> doubles = {1.0 / 3.0, -0.0};

    try {
        adios2::ADIOS adios;

        adios2::IO wio = adios.DeclareIO("test-plugin-attributes-writer");
        adios2::Engine writer = openPlugin(adios, wio, fileName, adios2::Mode::Write);
        wio.DefineAttribute<int>("io_version", 42);
        wio.DefineAttribute<std::string>("basePath", text);
        wio.DefineAttribute<std::string>("names", texts.data(), texts.size());
        wio.DefineAttribute<double>("doubles", doubles.data(), doubles.size());
        adios2::Variable<double> var = wio.DefineVariable<double>("x");
        writer.Put(var, 2.5, adios2::Mode::Sync);
        // Attributes defined after the first Put are stored too
        wio.DefineAttribute<int64_t>("job_time", INT64_MAX);
        writer.Close();

        adios2::IO rio = adios.DeclareIO("test-plugin-attributes-reader");
        adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
        EXPECT_EQ(rio.AvailableAttributes().size(), 5u);

        auto version = rio.InquireAttribute<int>("io_version");
        ASSERT_TRUE(version);
        EXPECT_TRUE(version.IsValue());
        EXPECT_EQ(version.Data(), std::vector<int>{42});

        auto basePath = rio.InquireAttribute<std::string>("basePath");
        ASSERT_TRUE(basePath);
        EXPECT_EQ(basePath.Data(), std::vector<std::string>{text});

        auto names = rio.InquireAttribute<std::string>("names");
        ASSERT_TRUE(names);
        EXPECT_FALSE(names.IsValue());
        EXPECT_EQ(names.Data(), texts);

        auto doublesAttr = rio.InquireAttribute<double>("doubles");
        ASSERT_TRUE(doublesAttr);
        EXPECT_TRUE(sameBytes(doublesAttr.Data(), doubles));

        auto jobTime = rio.InquireAttribute<int64_t>("job_time");
        ASSERT_TRUE(jobTime);
        EXPECT_EQ(jobTime.Data(), std::vector<int64_t>{INT64_MAX});

        double x = 0.0;
        reader.Get(rio.InquireVariable<double>("x"), x, adios2::Mode::Sync);
        EXPECT_EQ(x, 2.5);
        reader.Close();
    } catch (const std::exception &e) {
        FAIL() << "Adios throws an exception: " << e.what() << ".";
    }
}

// Local values (EPOCpp's per-rank scalars) are stored with a dimension of LocalValueDim, which
// used to crash the reader's Open
TEST(ADIOS, PluginLocalValue) {
    const std::string fileName = "test-plugin-local-value.db";
    int rankRead = -1;

    try {
        adios2::ADIOS adios;

        adios2::IO wio = adios.DeclareIO("test-plugin-local-value-writer");
        adios2::Engine writer = openPlugin(adios, wio, fileName, adios2::Mode::Write);
        adios2::Variable<int> var = wio.DefineVariable<int>("rank", {adios2::LocalValueDim});
        writer.Put(var, 7, adios2::Mode::Sync);
        writer.Close();

        adios2::IO rio = adios.DeclareIO("test-plugin-local-value-reader");
        adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
        reader.Get(rio.InquireVariable<int>("rank"), rankRead, adios2::Mode::Sync);
        reader.Close();
    } catch (const std::exception &e) {
        FAIL() << "Adios throws an exception: " << e.what() << ".";
    }

    EXPECT_EQ(rankRead, 7);
}

// Joined arrays (shape JoinedDim, no start) round-trip; their dimension also crashed the reader
TEST(ADIOS, PluginJoinedArray) {
    const std::string fileName = "test-plugin-joined.db";
    const std::vector<double> values = {1.0 / 3.0, -2.0, 4.5};
    std::vector<double> read;

    try {
        adios2::ADIOS adios;
        adios2::IO wio = adios.DeclareIO("test-plugin-joined-writer");
        adios2::Engine writer = openPlugin(adios, wio, fileName, adios2::Mode::Write);
        adios2::Variable<double> var =
            wio.DefineVariable<double>("joined", {adios2::JoinedDim}, {}, {values.size()});
        writer.Put(var, values.data(), adios2::Mode::Sync);
        writer.Close();

        adios2::IO rio = adios.DeclareIO("test-plugin-joined-reader");
        adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
        read = getArray<double>(rio, reader, "joined");
        reader.Close();
    } catch (const std::exception &e) {
        FAIL() << "Adios throws an exception: " << e.what() << ".";
    }

    EXPECT_TRUE(sameBytes(values, read));
}

// A selection must match the block a rank wrote: reading across blocks is not supported
TEST(ADIOS, PluginSelectionMismatch) {
    const std::string fileName = "test-plugin-selection.db";
    const std::vector<double> values = {1.0, 2.0, 3.0, 4.0};

    adios2::ADIOS adios;
    adios2::IO wio = adios.DeclareIO("test-plugin-selection-writer");
    adios2::Engine writer = openPlugin(adios, wio, fileName, adios2::Mode::Write);
    adios2::Variable<double> var = wio.DefineVariable<double>("v", {8}, {4}, {4});
    writer.Put(var, values.data(), adios2::Mode::Sync);
    writer.Close();

    adios2::IO rio = adios.DeclareIO("test-plugin-selection-reader");
    adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
    adios2::Variable<double> rvar = rio.InquireVariable<double>("v");
    ASSERT_TRUE(rvar);

    std::vector<double> read;
    reader.Get(rvar, read, adios2::Mode::Sync);
    EXPECT_TRUE(sameBytes(values, read));

    // A memory selection would place the block inside a larger buffer: not supported
    std::vector<double> padded(6);
    rvar.SetMemorySelection({{1}, {6}});
    EXPECT_THROW(reader.Get(rvar, padded.data(), adios2::Mode::Sync), std::invalid_argument);

    // Same size, another offset: would silently return the stored block
    rvar.SetMemorySelection();
    rvar.SetSelection({{0}, {4}});
    EXPECT_THROW(reader.Get(rvar, read, adios2::Mode::Sync), std::invalid_argument);
    reader.Close();
}

// A value over LSMIO's maximum value length fails the Put instead of being lost
TEST(ADIOS, PluginOversizedValue) {
    const std::string fileName = "test-plugin-oversized.db";
    const std::vector<char> big(lsmio::gConfigLSMIO.getMaxValueLen() + 1, 'v');

    adios2::ADIOS adios;
    adios2::IO wio = adios.DeclareIO("test-plugin-oversized-writer");
    adios2::Engine writer = openPlugin(adios, wio, fileName, adios2::Mode::Write);
    try {
        putArray(wio, writer, "big", big);
        ADD_FAILURE() << "the put of an oversized value did not throw";
    } catch (const std::exception &e) {
        EXPECT_NE(std::string(e.what()).find("could not write variable big"), std::string::npos)
            << e.what();
    }
    writer.Close();

    // The failed put is not listed to readers
    adios2::IO rio = adios.DeclareIO("test-plugin-oversized-reader");
    adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
    EXPECT_FALSE(rio.InquireVariable<char>("big"));
    reader.Close();
}

// Only variables that were put are listed to readers, as in BP5
TEST(ADIOS, PluginUnputVariable) {
    const std::string fileName = "test-plugin-unput.db";

    adios2::ADIOS adios;
    adios2::IO wio = adios.DeclareIO("test-plugin-unput-writer");
    adios2::Engine writer = openPlugin(adios, wio, fileName, adios2::Mode::Write);
    wio.DefineVariable<double>("never", {4}, {0}, {4});
    putArray(wio, writer, "put", std::vector<double>{1.0, 2.0});
    writer.Close();

    adios2::IO rio = adios.DeclareIO("test-plugin-unput-reader");
    adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
    EXPECT_EQ(rio.AvailableVariables().size(), 1u);
    EXPECT_TRUE(rio.InquireVariable<double>("put"));
    EXPECT_FALSE(rio.InquireVariable<double>("never"));
    reader.Close();
}

// Append keeps the existing variables and attributes; ones of the same name are replaced
TEST(ADIOS, PluginAppend) {
    const std::string fileName = "test-plugin-append.db";
    const std::vector<double> first = {1.0, 2.0}, second = {3.0, 4.0, 5.0}, replaced = {-1.0};

    try {
        adios2::ADIOS adios;
        {
            adios2::IO io = adios.DeclareIO("test-plugin-append-writer");
            adios2::Engine writer = openPlugin(adios, io, fileName, adios2::Mode::Write);
            putArray(io, writer, "first", first);
            putArray(io, writer, "replaced", std::vector<double>{9.0, 9.0});
            io.DefineAttribute<int>("kept", 1);
            io.DefineAttribute<int>("changed", 1);
            writer.Close();
        }
        {
            adios2::IO io = adios.DeclareIO("test-plugin-append-appender");
            adios2::Engine writer = openPlugin(adios, io, fileName, adios2::Mode::Append);
            putArray(io, writer, "second", second);
            putArray(io, writer, "replaced", replaced);
            io.DefineAttribute<int>("changed", 2);
            writer.Close();
        }

        adios2::IO rio = adios.DeclareIO("test-plugin-append-reader");
        adios2::Engine reader = openPlugin(adios, rio, fileName, adios2::Mode::Read);
        EXPECT_EQ(rio.AvailableVariables().size(), 3u);
        EXPECT_TRUE(sameBytes(getArray<double>(rio, reader, "first"), first));
        EXPECT_TRUE(sameBytes(getArray<double>(rio, reader, "second"), second));
        EXPECT_TRUE(sameBytes(getArray<double>(rio, reader, "replaced"), replaced));
        auto kept = rio.InquireAttribute<int>("kept");
        ASSERT_TRUE(kept);
        EXPECT_EQ(kept.Data(), std::vector<int>{1});
        auto changed = rio.InquireAttribute<int>("changed");
        ASSERT_TRUE(changed);
        EXPECT_EQ(changed.Data(), std::vector<int>{2});
        reader.Close();
    } catch (const std::exception &e) {
        FAIL() << "Adios throws an exception: " << e.what() << ".";
    }
}

namespace {

void appendU64(std::string &out, uint64_t value) {
    out.append(reinterpret_cast<const char *>(&value), sizeof(value));
}

void appendStr(std::string &out, const std::string &value) {
    appendU64(out, value.size());
    out.append(value);
}

// Plants record as the plugin's metadata: a string variable is stored as its raw bytes under its
// name, and the writer is never closed, so the plugin doesn't put its own record over it
void plantMetadata(const std::string &fileName, const std::string &record) {
    adios2::ADIOS adios;
    adios2::IO io = adios.DeclareIO("test-plugin-corrupt-writer");
    adios2::Engine writer = openPlugin(adios, io, fileName, adios2::Mode::Write);
    writer.Put(io.DefineVariable<std::string>("__lsmio_md::__adios_metadata"), record,
               adios2::Mode::Sync);
}

}  // namespace

// A corrupt metadata record is refused on open for read with a clear error, without reading
// past its end or allocating what a corrupt count asks for
TEST(ADIOS, PluginCorruptMetadata) {
    std::string variable;  // one double variable "x", up to its shape id
    appendU64(variable, 1);
    variable.push_back(0);  // variable
    appendStr(variable, "x");
    appendStr(variable, "double");
    variable.push_back(static_cast<char>(adios2::ShapeID::GlobalArray));

    std::string hugeDims = variable;
    appendU64(hugeDims, uint64_t(1) << 61);

    std::string badType;
    appendU64(badType, 1);
    badType.push_back(0);
    appendStr(badType, "x");
    appendStr(badType, "no-such-type");

    std::string badKind;
    appendU64(badKind, 1);
    badKind.push_back(7);
    appendStr(badKind, "x");
    appendStr(badKind, "double");

    std::string badAttribute;  // a single-value int attribute holding no elements
    appendU64(badAttribute, 1);
    badAttribute.push_back(1);  // attribute
    appendStr(badAttribute, "a");
    appendStr(badAttribute, "int32_t");
    badAttribute.push_back(1);  // single value
    appendU64(badAttribute, 0);
    appendStr(badAttribute, "");

    // An attribute entry: kind, name, type, single value, element count and payload
    const auto attribute = [](const std::string &type, bool singleValue, uint64_t elements,
                              const std::string &payload) {
        std::string record;
        appendU64(record, 1);
        record.push_back(1);
        appendStr(record, "a");
        appendStr(record, type);
        record.push_back(singleValue ? 1 : 0);
        appendU64(record, elements);
        appendStr(record, payload);
        return record;
    };
    // 2^62 int32 elements: their byte count wraps to 0, matching the empty payload
    const std::string overflowAttribute = attribute("int32_t", false, uint64_t(1) << 62, "");
    std::string oneString;  // one length-prefixed string "abc"
    appendStr(oneString, "abc");
    const std::string truncatedPrefix = attribute("string", false, 1, oneString.substr(0, 5));
    const std::string truncatedString = attribute("string", false, 1, oneString.substr(0, 10));
    const std::string missingString = attribute("string", false, 2, oneString);

    // Each case and the check that must refuse it: the record reader, or an attribute's values
    const std::string inRecord = "corrupt metadata record";
    const std::string inAttribute = "corrupt metadata for attribute a";
    const std::vector<std::tuple<std::string, std::string, std::string>> records = {
        {"truncated", variable, inRecord},
        {"huge-dims", hugeDims, inRecord},
        {"bad-type", badType, inRecord},
        {"bad-kind", badKind, inRecord},
        {"bad-attribute", badAttribute, inAttribute},
        {"overflow-attribute", overflowAttribute, inAttribute},
        {"truncated-prefix", truncatedPrefix, inAttribute},
        {"truncated-string", truncatedString, inAttribute},
        {"missing-string", missingString, inAttribute},
        {"trailing", std::string(9, '\0'), inRecord}};

    for (const auto &[name, record, expected] : records) {
        const std::string fileName = "test-plugin-corrupt-" + name + ".db";
        plantMetadata(fileName, record);

        adios2::ADIOS adios;
        adios2::IO rio = adios.DeclareIO("test-plugin-corrupt-reader");
        try {
            openPlugin(adios, rio, fileName, adios2::Mode::Read);
            ADD_FAILURE() << name << ": the corrupt record was accepted";
        } catch (const std::exception &e) {
            EXPECT_NE(std::string(e.what()).find(expected), std::string::npos)
                << name << ": " << e.what();
        }
    }
}

// A DB without the plugin's metadata record is refused on open for read
TEST(ADIOS, PluginMissingMetadata) {
    adios2::ADIOS adios;
    adios2::IO rio = adios.DeclareIO("test-plugin-missing-reader");
    EXPECT_ANY_THROW(openPlugin(adios, rio, "test-plugin-missing.db", adios2::Mode::Read));
}
