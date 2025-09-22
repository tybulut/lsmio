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

import csv
import logging
import os
import sys
from enum import IntEnum
from logging import handlers as lh
from typing import Any, List, Optional, TextIO, Type, Union

from lsmiotool.lib import PROGRAM


LOG_FILE: str = f"/tmp/{PROGRAM}-{os.getlogin()}-{PROGRAM}.log"

class LogLevel(IntEnum):
    """Log levels for the application."""
    ERROR = 0
    WARNING = 1
    DEBUG = 2
    INFO = 3

LOG_LEVEL = LogLevel
LOG_LEVEL_NAMES: List[str] = ['ERROR', 'WARNING', 'DEBUG', 'INFO']


class LogOutput:
    """Handles log output to file."""

    def __init__(self, f_proc_name: str) -> None:
        """Initialize log output with process name."""
        self.log_file: str = LOG_FILE
        self._logger: logging.Logger = logging.getLogger('LSMIOTOOL-' + f_proc_name)
        self._logger.setLevel(logging.DEBUG)
        self._handler: lh.RotatingFileHandler = lh.RotatingFileHandler(
            self.log_file,
            mode='a',
            maxBytes=524288,
            backupCount=0
        )
        self._formatter: logging.Formatter = logging.Formatter('%(asctime)s - %(message)s')
        self._handler.setFormatter(self._formatter)
        self._logger.addHandler(self._handler)

    def output(self) -> str:
        """Return the log file path."""
        return self.log_file

    def write(self, f_msg: str) -> None:
        """Write message to log file."""
        self._logger.debug(f_msg.rstrip('\n'))


class Log:
    """Main logging class with singleton pattern."""

    _singleton: Optional['Log'] = None
    _initialized: bool = False
    prog_name: str = PROGRAM
    _debug_level: LogLevel = LogLevel.WARNING

    def __new__(cls: Type['Log'], *args: Any, **kwargs: Any) -> 'Log':
        """Create or return singleton instance."""
        if not cls._singleton:
            cls._singleton = object.__new__(cls)
        return cls._singleton

    def __init__(self) -> None:
        """Initialize log instance if not already initialized."""
        if self.__class__._initialized:
            return
        self.__class__._initialized = True
        self.output: Optional[LogOutput] = None

    def currentOutput(self) -> LogOutput:
        """Get or create current log output."""
        if not self.output:
            self.output = LogOutput(PROGRAM)
        return self.output

    @classmethod
    def _message(cls, f_level: LogLevel, f_msg: str) -> None:
        """Write message at specified log level."""
        if f_level > cls.getLevel():
            return
        self = cls()
        self.currentOutput().write(
            f'{self.prog_name}: {LOG_LEVEL_NAMES[f_level]}: {f_msg}\n'
        )

    @classmethod
    def info(cls, f_msg: str) -> None:
        """Log info message."""
        return cls._message(LogLevel.INFO, f_msg)

    @classmethod
    def debug(cls, f_msg: str) -> None:
        """Log debug message."""
        return cls._message(LogLevel.DEBUG, f_msg)

    @classmethod
    def warning(cls, f_msg: str) -> None:
        """Log warning message."""
        return cls._message(LogLevel.WARNING, f_msg)

    @classmethod
    def error(cls, f_msg: str) -> None:
        """Log error message."""
        return cls._message(LogLevel.ERROR, f_msg)

    @classmethod
    def getLevel(cls) -> LogLevel:
        """Get current log level."""
        return Log._debug_level

    @classmethod
    def setLevel(cls, f_level: LogLevel) -> None:
        """Set log level."""
        if not isinstance(f_level, LogLevel) or f_level < LogLevel.ERROR or f_level > LogLevel.INFO:
            raise ValueError('Log level must be a LogLevel enum')
        Log._debug_level = f_level

    @classmethod
    def fixPermissions(cls, f_uid: int, f_gid: int) -> None:
        """Fix permissions on log file."""
        log_file = LogOutput.outputs
        if not os.path.exists(log_file):
            open(log_file, 'a+').close()
        os.chown(log_file, f_uid, f_gid)


class Console(Log):
    """Console output handler."""

    _singleton: Optional['Console'] = None
    _initialized: bool = False

    def __init__(self) -> None:
        """Initialize console output if not already initialized."""
        if self.__class__._initialized:
            return
        super(Console, self).__init__()

    def currentOutput(self) -> TextIO:
        """Get console output stream."""
        return sys.stderr

    @classmethod
    def fixPermissions(cls, f_uid: int, f_gid: int) -> None:
        """No-op for console output."""
        pass

    @classmethod
    def dump(cls, f_msg: str) -> None:
        """Dump message to console."""
        self = cls()
        self.currentOutput().write(f'{self.prog_name}: {f_msg}\n')
