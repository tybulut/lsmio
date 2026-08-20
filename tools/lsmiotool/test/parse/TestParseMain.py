#
# Copyright 2023 Serdar Bulut
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
#    contributors may be used to endorse or promote products derived from
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

import os
import tempfile
import unittest
from unittest import TestCase
from unittest.mock import patch, MagicMock
from lsmiotool.lib import main, env


class TestParseMain(TestCase):
    """Unit tests for ParseMain command and dispatch logic."""

    def testInitValidArguments(self) -> None:
        """Test initialization with valid command, scale mode, and ssd option."""
        pm = main.ParseMain("ior", "small", ssd=True)
        self.assertEqual(pm.m_command, "ior")
        self.assertEqual(pm.m_mode, "small")
        self.assertTrue(pm.m_is_ssd)

    def testInitInvalidCommand(self) -> None:
        """Test system exit on unknown benchmark command."""
        with self.assertRaises(SystemExit):
            main.ParseMain("invalid_cmd", "small")

    def testInitInvalidMode(self) -> None:
        """Test system exit on unknown execution mode."""
        with self.assertRaises(SystemExit):
            main.ParseMain("lsmio", "invalid_mode")

    @patch.object(main.ParseMain, "parseIor")
    def testDispatchIor(self, mock_parse_ior: MagicMock) -> None:
        """Test run() dispatches to parseIor."""
        pm = main.ParseMain("ior", "small", ssd=False)
        pm.run()
        mock_parse_ior.assert_called_once_with("small", False)

    @patch.object(main.ParseMain, "parseLsmio")
    def testDispatchLsmio(self, mock_parse_lsmio: MagicMock) -> None:
        """Test run() dispatches to parseLsmio."""
        pm = main.ParseMain("lsmio", "large", ssd=True)
        pm.run()
        mock_parse_lsmio.assert_called_once_with("large", True)

    @patch.object(main.ParseMain, "parseLmp")
    def testDispatchLmp(self, mock_parse_lmp: MagicMock) -> None:
        """Test run() dispatches to parseLmp."""
        pm = main.ParseMain("lmp", "bake", ssd=False)
        pm.run()
        mock_parse_lmp.assert_called_once_with("bake", False)

    @patch("lsmiotool.lib.output.IorAggOutput")
    def testParseIorExecution(self, mock_agg_class: MagicMock) -> None:
        """Test parseIor instantiates IorAggOutput and calls generateReports."""
        mock_agg = MagicMock()
        mock_agg_class.return_value = mock_agg
        pm = main.ParseMain("ior", "small")
        pm.parseIor("small", False)
        mock_agg.generateReports.assert_called_once()

    @patch("lsmiotool.lib.output.LsmioAggOutput")
    def testParseLsmioExecution(self, mock_agg_class: MagicMock) -> None:
        """Test parseLsmio instantiates LsmioAggOutput and calls generateReports."""
        mock_agg = MagicMock()
        mock_agg_class.return_value = mock_agg
        pm = main.ParseMain("lsmio", "small")
        pm.parseLsmio("small", False)
        mock_agg.generateReports.assert_called_once()

    @patch("lsmiotool.lib.output.LmpAggOutput")
    def testParseLmpExecution(self, mock_agg_class: MagicMock) -> None:
        """Test parseLmp instantiates LmpAggOutput and calls generateReports."""
        mock_agg = MagicMock()
        mock_agg_class.return_value = mock_agg
        pm = main.ParseMain("lmp", "small")
        pm.parseLmp("small", False)
        mock_agg.generateReports.assert_called_once()
