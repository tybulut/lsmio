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

import inspect
import threading
import traceback
from types import TracebackType
from typing import Any, Dict, List, Optional, Tuple, Type

from lsmiotool.lib.log import Log, LOG_LEVEL


class DebuggableObject:
    """Base class for objects that support debug logging."""

    @classmethod
    def _addTracebackToLog(cls, f_trace_back: TracebackType) -> str:
        """Add traceback information to log message."""
        ret_value = '\n'
        records: List[Tuple[str, int, str, str]] = traceback.extract_tb(f_trace_back)
        for file_name, line_number, function, line in records:
            ret_value += f'  File  "{file_name}", line {line_number}\n'
            ret_value += f'  {line}\n'
        return ret_value[:-1]

    @classmethod
    def _composeLog(cls, f_dict: Dict[str, Any]) -> str:
        """Compose log message from dictionary of values."""
        frm: str = inspect.stack()[2][3]
        msg: str = f"{cls.__name__}::{frm}(): "
        parts: List[str] = []
        trace_back_data: str = ''

        for key, value in f_dict.items():
            if key == '_trace_back' and value:
                trace_back_data = cls._addTracebackToLog(value)
                continue
            parts.append(f"{key}={value}")

        msg += ", ".join(parts) + trace_back_data
        return msg

    @classmethod
    def _logDebug(cls, f_dict: Dict[str, Any] = None) -> None:
        """Log debug message if debug level is enabled."""
        if f_dict is None:
            f_dict = {}
        if LOG_LEVEL.DEBUG > Log.getLevel():
            return
        Log.debug(cls._composeLog(f_dict))

    @classmethod
    def _logWarning(cls, f_dict: Dict[str, Any] = None) -> None:
        """Log warning message if warning level is enabled."""
        if f_dict is None:
            f_dict = {}
        if LOG_LEVEL.WARNING > Log.getLevel():
            return
        Log.warning(cls._composeLog(f_dict))

    @classmethod
    def _logError(cls, f_dict: Dict[str, Any] = None) -> None:
        """Log error message if error level is enabled."""
        if f_dict is None:
            f_dict = {}
        if LOG_LEVEL.ERROR > Log.getLevel():
            return
        Log.error(cls._composeLog(f_dict))

    @classmethod
    def _dumpConsole(cls, f_dict: Dict[str, Any] = None) -> None:
        """Dump message to console."""
        if f_dict is None:
            f_dict = {}
        Console.dump(cls._composeLog(f_dict))

    @classmethod
    def __str__(cls) -> str:
        """Return class name as string."""
        return cls.__class__.__name__
