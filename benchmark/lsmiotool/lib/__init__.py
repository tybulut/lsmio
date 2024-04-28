import os, lsmiotool

VERSION = "0.1"
PROGRAM = "lsmiotool"
LSMIOTOOL_DIR = os.path.dirname(os.path.abspath(lsmiotool.__file__))

# Enum definition
def enum(*args, **kwargs):
	"""
	a = enum('ERROR', 'WARNING', 'DEBUG', 'INFO')
	assert(a.ERROR == 0)
	"""
	enums = dict(zip(args, range(len(args))), **kwargs)
	return type('Enum', (), enums)


class StringEnum(set):
	"""
	a = StringEnum(['ERROR', 'WARNING', 'DEBUG', 'INFO'])
	assert(a.ERROR == 'ERROR')
	"""
	def __getattr__(self, f_name):
		if f_name in self:
			return f_name
		raise AttributeError(f_name)


class LsmioToolException(Exception):

	def __init__(self, value):
		self.value = value


	def __str__(self):
		return str(self.value)


