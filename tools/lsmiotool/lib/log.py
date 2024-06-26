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

import os, sys, logging
from logging import handlers as lh
from lsmiotool.lib import enum, PROGRAM


LOG_FILE = "/tmp/%s-%s-%s.log" % (PROGRAM, os.getlogin(), PROGRAM)

LOG_LEVEL = enum('ERROR', 'WARNING', 'DEBUG', 'INFO')
LOG_LEVEL_NAMES = ['ERROR', 'WARNING', 'DEBUG', 'INFO']


class LogOutput(object):

  def __init__(self, f_proc_name):
    self.log_file = LOG_FILE
    self._logger = logging.getLogger('LSMIOTOOL-' + f_proc_name)
    self._logger.setLevel(logging.DEBUG)
    self._handler = lh.RotatingFileHandler(self.log_file,
                  mode='a', maxBytes=524288, backupCount=0)
    self._formatter = logging.Formatter('%(asctime)s - %(message)s')
    self._handler.setFormatter(self._formatter)
    self._logger.addHandler(self._handler)


  def output(cls):
    return self.log_file


  def write(self, f_msg):
    self._logger.debug(f_msg.rstrip('\n'))



class Log(object):
  _singleton = None
  _initialized = False
  prog_name = PROGRAM
  _debug_level = LOG_LEVEL.WARNING


  def __new__(cls, *args, **kwargs):
    if not cls._singleton:
      cls._singleton = object.__new__(cls)
    return cls._singleton


  def __init__(self):
    if self.__class__._initialized:
      return
    self.__class__._initialized = True
    self.output = None


  def currentOutput(self):
    if not self.output:
      self.output = LogOutput(PROGRAM)
    return self.output


  @classmethod
  def _message(cls, f_level, f_msg):
    if f_level > cls.getLevel(): return
    self = cls()
    self.currentOutput().write('%s: %s: %s\n' % (self.prog_name, LOG_LEVEL_NAMES[f_level], f_msg))


  @classmethod
  def info(cls, f_msg):
    return cls._message(LOG_LEVEL.INFO, f_msg)


  @classmethod
  def debug(cls, f_msg):
    return cls._message(LOG_LEVEL.DEBUG, f_msg)


  @classmethod
  def warning(cls, f_msg):
    return cls._message(LOG_LEVEL.WARNING, f_msg)


  @classmethod
  def error(cls, f_msg):
    return cls._message(LOG_LEVEL.ERROR, f_msg)


  @classmethod
  def getLevel(cls):
    return Log._debug_level


  @classmethod
  def setLevel(cls, f_level):
    if type(f_level) is not int or f_level < LOG_LEVEL.ERROR or f_level > LOG_LEVEL.INFO:
      raise ValueError('Log level must be an LOG_LEVEL enum')
    Log._debug_level = f_level


  @classmethod
  def fixPermissions(cls, f_uid, f_gid):
    log_file = LogOutput.outputs
    if not os.path.exists(log_file):
      open(log_file, 'a+').close()
    os.chown(log_file, f_uid, f_gid)



class Console(Log):
  _singleton = None
  _initialized = False

  def __init__(self):
    if self.__class__._initialized:
      return
    super(Console, self).__init__()


  def currentOutput(self):
    return sys.stderr


  @classmethod
  def fixPermissions(cls, f_uid, f_gid):
    pass


  @classmethod
  def dump(cls, f_msg):
    self = cls()
    self.currentOutput().write('%s: %s\n' % (self.prog_name, f_msg))


