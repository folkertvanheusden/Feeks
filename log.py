import time

# (C) 2017 by folkert@vanheusden.com
# released under AGPL v3.0

logfile = 'feeks.dat'

def l(msg):
	global logfile

	fh = open(logfile, 'a')
	fh.write('%s %s\n' % (time.asctime(), msg))
	fh.close()

def set_l(file_):
	global logfile

	logfile = file_
