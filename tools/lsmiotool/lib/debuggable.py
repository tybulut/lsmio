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


class DebuggableObject(object):
    @classmethod
    def _addTracebackToLog(cls, f_trace_back: TracebackType) -> str:
        ret_vale = '\n'
        records: List[Tuple[str, int, str, str]] = traceback.extract_tb(f_trace_back)
        for file_name, line_number, function, line in records:
            ret_vale += '  File  "%s", line %s\n' % (file_name, line_number)
            ret_vale += '  %s\n' % (line)
        return ret_vale[:-1]

    @classmethod
    def _composeLog(cls, f_dict: Dict[str, Any]) -> str:
        frm: str = inspect.stack()[2][3]
        msg: str = "%s::%s(): " % (cls.__name__, frm)
        parts: List[str] = []
        trace_back_data: str = ''
        for key in f_dict:
            if key == '_trace_back' and f_dict[key]:
                trace_back_data = cls._addTracebackToLog(f_dict[key])
                continue
            parts.append("%s=%s" % (key, f_dict[key]))
        msg += ", ".join(parts) + trace_back_data
        return msg

    @classmethod
    def _logDebug(cls, f_dict: Dict[str, Any] = {}) -> None:
        if LOG_LEVEL.DEBUG > Log.getLevel(): return
        Log.debug(cls._composeLog(f_dict))

    @classmethod
    def _logWarning(cls, f_dict: Dict[str, Any] = {}) -> None:
        if LOG_LEVEL.WARNING > Log.getLevel(): return
        Log.warning(cls._composeLog(f_dict))

    @classmethod
    def _logError(cls, f_dict: Dict[str, Any] = {}) -> None:
        if LOG_LEVEL.ERROR > Log.getLevel(): return
        Log.error(cls._composeLog(f_dict))

    @classmethod
    def _dumpConsole(cls, f_dict: Dict[str, Any] = {}) -> None:
        Console.dump(cls._composeLog(f_dict))

    @classmethod
    def __str__(cls) -> str:
        return cls.__class__.__name__
