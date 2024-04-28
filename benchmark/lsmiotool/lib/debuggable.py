import inspect, traceback, threading
from lsmiotool.lib.log import Log, LOG_LEVEL


class DebuggableObject(object):

	@classmethod
	def _addTracebackToLog(cls, f_trace_back):
		ret_vale = '\n'
		records = traceback.extract_tb(f_trace_back)
		for file_name, line_number, function, line in records:
			ret_vale += '  File  "%s", line %s\n' % (file_name, line_number)
			ret_vale += '	%s\n' % (line)
		return ret_vale[:-1]


	@classmethod
	def _composeLog(cls, f_dict):
		frm = inspect.stack()[2][3]
		msg = "%s::%s(): " % (cls.__name__, frm)
		parts = []
		trace_back_data = ''
		for key in f_dict:
			if key == '_trace_back' and f_dict[key]:
				trace_back_data = cls._addTracebackToLog(f_dict[key])
				continue
			parts.append("%s=%s" % (key, f_dict[key]))
		msg += ", ".join(parts) + trace_back_data
		return msg


	@classmethod
	def _logDebug(cls, f_dict={}):
		if LOG_LEVEL.DEBUG > Log.getLevel(): return
		Log.debug(cls._composeLog(f_dict))


	@classmethod
	def _logWarning(cls, f_dict={}):
		if LOG_LEVEL.WARNING > Log.getLevel(): return
		Log.warning(cls._composeLog(f_dict))


	@classmethod
	def _logError(cls, f_dict={}):
		if LOG_LEVEL.ERROR > Log.getLevel(): return
		Log.error(cls._composeLog(f_dict))


	@classmethod
	def _dumpConsole(cls, f_dict={}):
		Console.dump(cls._composeLog(f_dict))


	@classmethod
	def __str__(cls):
		return cls.__class__.__name__


