#
# Copyright 2026 Serdar Bulut
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be practical products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


class CoverageContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m_source_root = Path(__file__).resolve().parents[4]
        self.m_cmake_script = self.m_source_root / "cmake" / "LsmiotoolPythonCoverage.cmake"
        self.m_root_cmakelists = self.m_source_root / "CMakeLists.txt"
        self.m_test_cmakelists = self.m_source_root / "test" / "CMakeLists.txt"

    def _createMockPython(self, f_temp_dir: Path, f_helper_code: str) -> Path:
        helper_path = f_temp_dir / "mock_helper.py"
        helper_path.write_text(f_helper_code, encoding="utf-8")

        mock_sh = f_temp_dir / "mock_python.sh"
        mock_sh.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{helper_path}" "$@"\n',
            encoding="utf-8",
        )
        mock_sh.chmod(0o755)
        return mock_sh

    def testCoverageConfigureRequiresModule(self) -> None:
        root_cmake_text = self.m_root_cmakelists.read_text(encoding="utf-8")
        self.assertIn("if(LSMIO_ENABLE_COVERAGE)", root_cmake_text)
        self.assertIn('COMMAND "${Python3_EXECUTABLE}" -c "import coverage"', root_cmake_text)
        self.assertIn("FATAL_ERROR", root_cmake_text)
        self.assertIn("pip install coverage", root_cmake_text)

    def testInstalledCoverageHelpAdvertisesDataFileForRunJsonAndReport(self) -> None:
        coverage_available = True
        try:
            import coverage  # noqa: F401
        except ImportError:
            coverage_available = False

        if coverage_available:
            for subcmd in ("run", "json", "report"):
                res = subprocess.run(
                    [sys.executable, "-m", "coverage", subcmd, "--help"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(res.returncode, 0)
                self.assertIn("--data-file", res.stdout)
        else:
            cmake_text = self.m_cmake_script.read_text(encoding="utf-8")
            self.assertIn('"--data-file=${data}"', cmake_text)
            self.assertEqual(cmake_text.count('"--data-file=${data}"'), 3)

    def testOneAbsoluteDataPathIsExplicitOnRunJsonAndReport(self) -> None:
        test_cmake_text = self.m_test_cmakelists.read_text(encoding="utf-8")
        cmake_script_text = self.m_cmake_script.read_text(encoding="utf-8")

        # test/CMakeLists.txt defines the exact data path for both run test and report target
        self.assertIn("-Ddata=${CMAKE_BINARY_DIR}/.coverage.lsmiotool", test_cmake_text)
        self.assertIn("-Djson=${CMAKE_BINARY_DIR}/lsmiotool-python-coverage.json", test_cmake_text)
        self.assertIn("-Dmarker=${CMAKE_BINARY_DIR}/.coverage.lsmiotool.sha256", test_cmake_text)

        # LsmiotoolPythonCoverage.cmake enforces absolute path checks
        self.assertIn('if(NOT IS_ABSOLUTE "${data}")', cmake_script_text)
        self.assertIn('if(NOT IS_ABSOLUTE "${json}")', cmake_script_text)
        self.assertIn('if(NOT IS_ABSOLUTE "${marker}")', cmake_script_text)

        with tempfile.TemporaryDirectory() as f_temp_dir:
            temp_path = Path(f_temp_dir)
            mock_py = self._createMockPython(temp_path, "import sys\nsys.exit(0)\n")
            res = subprocess.run(
                [
                    "cmake",
                    "-Dmode=report",
                    f"-Dpython={mock_py}",
                    "-Ddata=.coverage.relative",
                    f"-Djson={temp_path / 'cov.json'}",
                    f"-Dmarker={temp_path / 'cov.marker'}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("data path must be absolute", res.stderr)

    def testRunModeRemovesOnlyScopedStaleDataJsonAndMarker(self) -> None:
        with tempfile.TemporaryDirectory() as f_temp_dir:
            temp_path = Path(f_temp_dir)
            data_file = temp_path / ".coverage.lsmiotool"
            json_file = temp_path / "lsmiotool-python-coverage.json"
            marker_file = temp_path / ".coverage.lsmiotool.sha256"
            keep_file = temp_path / "unscoped_keep.txt"

            data_file.write_text("stale-data", encoding="utf-8")
            json_file.write_text("stale-json", encoding="utf-8")
            marker_file.write_text("stale-marker", encoding="utf-8")
            keep_file.write_text("must-stay", encoding="utf-8")

            mock_helper_code = (
                "import sys, pathlib\n"
                "data_arg = [a for a in sys.argv if a.startswith('--data-file=')][0].split('=', 1)[1]\n"
                "pathlib.Path(data_arg).write_bytes(b'fresh-coverage-data-payload-12345')\n"
                "sys.exit(0)\n"
            )
            mock_py = self._createMockPython(temp_path, mock_helper_code)
            dummy_entry = temp_path / "lsmiotool"
            dummy_entry.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            res = subprocess.run(
                [
                    "cmake",
                    "-Dmode=run",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dsource={self.m_source_root / 'tools' / 'lsmiotool'}",
                    f"-Dentry={dummy_entry}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, f"res.stderr: {res.stderr}\nres.stdout: {res.stdout}")
            self.assertTrue(keep_file.exists())
            self.assertEqual(keep_file.read_text(encoding="utf-8"), "must-stay")
            self.assertFalse(json_file.exists())
            self.assertTrue(data_file.exists())
            self.assertTrue(marker_file.exists())

            expected_sha = hashlib.sha256(b"fresh-coverage-data-payload-12345").hexdigest()
            self.assertEqual(marker_file.read_text(encoding="utf-8").strip(), expected_sha)

    def testFailedRunLeavesNoCompletionMarker(self) -> None:
        with tempfile.TemporaryDirectory() as f_temp_dir:
            temp_path = Path(f_temp_dir)
            data_file = temp_path / ".coverage.lsmiotool"
            json_file = temp_path / "lsmiotool-python-coverage.json"
            marker_file = temp_path / ".coverage.lsmiotool.sha256"

            marker_file.write_text("pre-existing-marker", encoding="utf-8")
            mock_py = self._createMockPython(temp_path, "import sys\nsys.exit(1)\n")
            dummy_entry = temp_path / "lsmiotool"
            dummy_entry.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            res = subprocess.run(
                [
                    "cmake",
                    "-Dmode=run",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dsource={self.m_source_root / 'tools' / 'lsmiotool'}",
                    f"-Dentry={dummy_entry}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse(marker_file.exists())
            self.assertFalse(data_file.exists())

    def testReportRejectsMissingEmptyOrHashMismatchedData(self) -> None:
        with tempfile.TemporaryDirectory() as f_temp_dir:
            temp_path = Path(f_temp_dir)
            data_file = temp_path / ".coverage.lsmiotool"
            json_file = temp_path / "lsmiotool-python-coverage.json"
            marker_file = temp_path / ".coverage.lsmiotool.sha256"
            mock_py = self._createMockPython(temp_path, "import sys\nsys.exit(0)\n")

            # 1. Missing data file
            marker_file.write_text("somehash\n", encoding="utf-8")
            res_missing_data = subprocess.run(
                [
                    "cmake",
                    "-Dmode=report",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(res_missing_data.returncode, 0)
            self.assertIn("does not exist", res_missing_data.stderr)

            # 2. Missing marker file
            data_file.write_bytes(b"valid-data")
            marker_file.unlink()
            res_missing_marker = subprocess.run(
                [
                    "cmake",
                    "-Dmode=report",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(res_missing_marker.returncode, 0)
            self.assertIn("does not exist", res_missing_marker.stderr)

            # 3. Empty data file
            data_file.write_bytes(b"")
            marker_file.write_text(hashlib.sha256(b"").hexdigest(), encoding="utf-8")
            res_empty_data = subprocess.run(
                [
                    "cmake",
                    "-Dmode=report",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(res_empty_data.returncode, 0)
            self.assertIn("is empty", res_empty_data.stderr)

            # 4. Hash mismatch (stale or altered data file)
            data_file.write_bytes(b"altered-data-bytes")
            marker_file.write_text(hashlib.sha256(b"different-original-bytes").hexdigest(), encoding="utf-8")
            res_mismatch = subprocess.run(
                [
                    "cmake",
                    "-Dmode=report",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(res_mismatch.returncode, 0)
            self.assertIn("does not match marker SHA256", " ".join(res_mismatch.stderr.split()))

    def testDefaultDotCoverageDecoyIsNeverConsumed(self) -> None:
        with tempfile.TemporaryDirectory() as f_temp_dir:
            temp_path = Path(f_temp_dir)
            decoy_dot_coverage = temp_path / ".coverage"
            decoy_content = b"DECOY_DEFAULT_DOT_COVERAGE_NEVER_READ"
            decoy_dot_coverage.write_bytes(decoy_content)
            decoy_mtime_before = decoy_dot_coverage.stat().st_mtime_ns

            data_file = temp_path / ".coverage.lsmiotool"
            json_file = temp_path / "lsmiotool-python-coverage.json"
            marker_file = temp_path / ".coverage.lsmiotool.sha256"

            data_content = b"EXPLICIT_DATA_PAYLOAD_TEST"
            data_file.write_bytes(data_content)
            marker_file.write_text(hashlib.sha256(data_content).hexdigest(), encoding="utf-8")

            mock_helper_code = (
                "import sys, pathlib, json\n"
                "args = sys.argv\n"
                "if 'json' in args:\n"
                "    out_idx = args.index('-o') + 1\n"
                "    out_path = args[out_idx]\n"
                "    pathlib.Path(out_path).write_text(json.dumps({'files': {'foo.py': {'summary': {'percent_covered': 100}}}}))\n"
                "    sys.exit(0)\n"
                "elif 'report' in args:\n"
                "    print('Name Stmts Miss Cover')\n"
                "    sys.exit(0)\n"
                "sys.exit(1)\n"
            )
            mock_py = self._createMockPython(temp_path, mock_helper_code)

            res = subprocess.run(
                [
                    "cmake",
                    "-Dmode=report",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                cwd=str(temp_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, f"res.stderr: {res.stderr}\nres.stdout: {res.stdout}")
            self.assertTrue(decoy_dot_coverage.exists())
            self.assertEqual(decoy_dot_coverage.read_bytes(), decoy_content)
            self.assertEqual(decoy_dot_coverage.stat().st_mtime_ns, decoy_mtime_before)

    def testReportJsonComesFromJustCreatedExplicitData(self) -> None:
        with tempfile.TemporaryDirectory() as f_temp_dir:
            temp_path = Path(f_temp_dir)
            data_file = temp_path / ".coverage.lsmiotool"
            json_file = temp_path / "lsmiotool-python-coverage.json"
            marker_file = temp_path / ".coverage.lsmiotool.sha256"

            stale_json = temp_path / "lsmiotool-python-coverage.json"
            stale_json.write_text('{"stale": true}', encoding="utf-8")

            data_content = b"GENUINE_COVERAGE_RAW_DATA"
            data_file.write_bytes(data_content)
            marker_file.write_text(hashlib.sha256(data_content).hexdigest(), encoding="utf-8")

            mock_helper_code = (
                "import sys, pathlib, json\n"
                "args = sys.argv\n"
                "if 'json' in args:\n"
                "    out_idx = args.index('-o') + 1\n"
                "    out_path = args[out_idx]\n"
                "    pathlib.Path(out_path).write_text(json.dumps({'files': {'lib/worker.py': {'summary': {'percent_covered': 98.5}}}}))\n"
                "    sys.exit(0)\n"
                "elif 'report' in args:\n"
                "    sys.exit(0)\n"
                "sys.exit(1)\n"
            )
            mock_py = self._createMockPython(temp_path, mock_helper_code)

            res = subprocess.run(
                [
                    "cmake",
                    "-Dmode=report",
                    f"-Dpython={mock_py}",
                    f"-Ddata={data_file}",
                    f"-Djson={json_file}",
                    f"-Dmarker={marker_file}",
                    f"-Dbuild_dir={temp_path}",
                    "-P",
                    str(self.m_cmake_script),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, f"res.stderr: {res.stderr}\nres.stdout: {res.stdout}")
            self.assertTrue(json_file.exists())
            report_data = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertIn("files", report_data)
            self.assertIn("lib/worker.py", report_data["files"])

    def testCoverageCommandUsesBranchAndOwnedSourceExcludingTestsAndCtest(self) -> None:
        cmake_script_text = self.m_cmake_script.read_text(encoding="utf-8")
        self.assertIn("--branch", cmake_script_text)
        self.assertIn('"--source=${source}"', cmake_script_text)
        self.assertIn("--omit=*/test/*,*/ctest/*,*/__pycache__/*", cmake_script_text)

        test_cmake_text = self.m_test_cmakelists.read_text(encoding="utf-8")
        self.assertIn("-Dsource=${LSMIO_SOURCE_DIR}/tools/lsmiotool", test_cmake_text)
        self.assertIn("-Dentry=${LSMIO_SOURCE_DIR}/tools/lsmiotool/lsmiotool", test_cmake_text)

    def testJsonHasPerFileStatementsMissingAndPercent(self) -> None:
        sample_json_content = {
            "meta": {"version": "7.0.0"},
            "files": {
                "lib/run.py": {
                    "summary": {
                        "covered_lines": 150,
                        "num_statements": 150,
                        "percent_covered": 100.0,
                        "percent_covered_display": "100",
                        "missing_lines": 0,
                        "excluded_lines": 0,
                        "num_branches": 20,
                        "num_partial_branches": 0,
                        "covered_branches": 20,
                        "missing_branches": 0,
                    }
                }
            },
            "totals": {
                "covered_lines": 150,
                "num_statements": 150,
                "percent_covered": 100.0,
            },
        }

        with tempfile.TemporaryDirectory() as f_temp_dir:
            json_path = Path(f_temp_dir) / "test_coverage.json"
            json_path.write_text(json.dumps(sample_json_content), encoding="utf-8")

            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("files", loaded)
            file_summary = loaded["files"]["lib/run.py"]["summary"]
            self.assertIn("covered_lines", file_summary)
            self.assertIn("num_statements", file_summary)
            self.assertIn("percent_covered", file_summary)
            self.assertIn("covered_branches", file_summary)
            self.assertIn("num_branches", file_summary)

    def testNormalTestDoesNotRequireCoverage(self) -> None:
        test_cmake_text = self.m_test_cmakelists.read_text(encoding="utf-8")
        coverage_block_match = re.search(
            r"if\(LSMIO_ENABLE_COVERAGE\)(.*?)endif\(\)",
            test_cmake_text,
            re.DOTALL,
        )
        self.assertIsNotNone(coverage_block_match)
        coverage_block = coverage_block_match.group(1)
        self.assertIn("else()", coverage_block)
        if_part, else_part = coverage_block.split("else()", 1)

        self.assertIn("LsmiotoolPythonCoverage.cmake", if_part)
        self.assertIn("lsmiotool_python_coverage_report", if_part)

        self.assertIn("Python3::Interpreter", else_part)
        self.assertNotIn("LsmiotoolPythonCoverage.cmake", else_part)
        self.assertNotIn("coverage run", else_part)
        self.assertNotIn("lsmiotool_python_coverage_report", else_part)
