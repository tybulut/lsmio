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

#ifndef _LSMIO_PLUGIN_TCC_
#define _LSMIO_PLUGIN_TCC_

#include "lsmio_plugin.hpp"


namespace lsmio {

void commaSplit(std::string const &str, std::vector<std::string> &out) {
  const char delimiter = ',';
  std::stringstream ss(str);
  std::string s;

  while (std::getline(ss, s, delimiter)) {
      out.push_back(s);
  }
}


template <typename T>
void LsmioPlugin::AddVariable(const std::string &name, Dims shape,
                                    Dims start, Dims count) {
  LOG(INFO) << "LsmioPlugin::AddVariable<T>: " << name << std::endl;

  core::Variable<T> *v = m_IO.InquireVariable<T>(name);
  if (!v) {
    m_IO.DefineVariable<T>(name, shape, start, count);
  }
}

template <class T>
inline void LsmioPlugin::ReadVariable(core::Variable<T> &variable,
                                            T *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<T>: " << variable.m_Name << std::endl;
  std::string vals;
  bool success = _lm->get(variable.m_Name, &vals);
  if (vals.find(",") == vals.npos) {
    values[0] = helper::StringTo<T>(vals, "");
  }
  else {
    std::istringstream ss(vals);
    std::string val;
    int i = 0;

    while (std::getline(ss, val, ',')) {
      values[i] = helper::StringTo<T>(val, "");
      i++;
    }
  }
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<std::string> &variable,
                                std::string *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<string>: " << variable.m_Name << std::endl;
  bool success = _lm->get(variable.m_Name, &(values[0]));
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<char> &variable,
                                            char *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<char>: " << variable.m_Name << std::endl;
  std::string value;
  bool success = _lm->get(variable.m_Name, &value);
  std::vector<std::string> valueArray;
  commaSplit(value, valueArray);

  for (size_t i = 0; i < variable.SelectionSize(); ++i) {
    values[i] = static_cast<char>(valueArray[i][0]);
  }
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<unsigned char> &variable,
                                unsigned char *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<unsigned char>: " << variable.m_Name << std::endl;
  std::string value;
  bool success = _lm->get(variable.m_Name, &value);
  std::vector<std::string> valueArray;
  commaSplit(value, valueArray);

  for (size_t i = 0; i < variable.SelectionSize(); ++i) {
    values[i] = static_cast<unsigned char>(valueArray[i][0]);
  }
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<signed char> &variable,
                                signed char *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<signed char>: " << variable.m_Name << std::endl;
  std::string value;
  bool success = _lm->get(variable.m_Name, &value);
  std::vector<std::string> valueArray;
  commaSplit(value, valueArray);

  for (size_t i = 0; i < variable.SelectionSize(); ++i) {
    values[i] = static_cast<signed char>(valueArray[i][0]);
  }
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<short> &variable,
                                            short *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<short>: " << variable.m_Name << std::endl;
  std::string value;
  bool success = _lm->get(variable.m_Name, &value);
  std::vector<std::string> valueArray;
  commaSplit(value, valueArray);

  for (size_t i = 0; i < variable.SelectionSize(); ++i) {
    values[i] = static_cast<short>(std::stoi(valueArray[i]));
  }
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<unsigned short> &variable,
                                unsigned short *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<unsigned short>: " << variable.m_Name << std::endl;
  std::string value;
  bool success = _lm->get(variable.m_Name, &value);
  std::vector<std::string> valueArray;
  commaSplit(value, valueArray);

  for (size_t i = 0; i < variable.SelectionSize(); ++i) {
    values[i] = static_cast<unsigned short>(std::stoi(valueArray[i]));
  }
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<long double> &variable,
                                long double *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<long double>: " << variable.m_Name << std::endl;
  std::string value;
  bool success = _lm->get(variable.m_Name, &value);
  std::vector<std::string> valueArray;
  commaSplit(value, valueArray);

  for (size_t i = 0; i < variable.SelectionSize(); ++i) {
    try {
      values[i] = std::strtold(valueArray[i].data(), nullptr);
    }
    catch (...) {
      std::throw_with_nested(std::invalid_argument(
                        "ERROR: could not cast " + valueArray[i] + " to long double "));
    }
  }
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<std::complex<float>> &variable,
                                std::complex<float> *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<float>: " << variable.m_Name << std::endl;
  throw std::invalid_argument(
        "ERROR: std::complex<float> not supported in this engine");
}

template <>
inline void LsmioPlugin::ReadVariable(core::Variable<std::complex<double>> &variable,
                                std::complex<double> *values) {
  LOG(INFO) << "LsmioPlugin::ReadVariable<double>: " << variable.m_Name << std::endl;
  throw std::invalid_argument(
        "ERROR: std::complex<double> not supported in this engine");
}

template <typename T>
std::string LsmioPlugin::WriteVariableInfo(core::Variable<T> &variable) {
  std::ostringstream valueStream;

  valueStream << variable.m_Name << ";" << variable.m_Type << ";"
            << variable.m_Shape << ";" << variable.m_Start << ";"
            << variable.m_Count << std::endl;

  LOG(INFO) << "LsmioPlugin::WriteVariableInfo(): key: " << _variableStoreKey
            << ": " << valueStream.str() << std::endl;

  return valueStream.str();
}

template <typename T>
inline void LsmioPlugin::WriteVariable(core::Variable<T> &variable, const T *values, const Mode launch) {
  std::ostringstream valueStream;
  bool isSync = (launch == Mode::Sync) ? true : false;

  for (size_t i = 0; i < variable.SelectionSize(); ++i) {
    valueStream << values[i];
    if (i < variable.SelectionSize() - 1) {
       valueStream << ",";
    }
  }

  LOG(INFO) << "LsmioPlugin::WriteVariable<T>: key: " << variable.m_Name
            << ": " << valueStream.str() << std::endl;

  bool success = _lm->put(variable.m_Name, valueStream.str(), isSync);
}

template <>
inline void LsmioPlugin::WriteVariable(core::Variable<std::string> &variable, const std::string *values, const Mode launch) {
  bool isSync = (launch == Mode::Sync) ? true : false;
  LOG(INFO) << "LsmioPlugin::WriteVariable<string>: key: " << variable.m_Name
            << ": " << values[0] << std::endl;
  bool success = _lm->put(variable.m_Name, values[0], isSync);
}


}  // namespace lsmio

#endif
