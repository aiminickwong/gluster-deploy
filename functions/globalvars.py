#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  global.py
#  
#  Copyright 2013 Paul Cuzner <paul.cuzner@redhat.com>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#  
import logging
import os
import sys

def init():
	""" Initialise global variables """
	global LOGFILE
	global LOGLEVEL
	global ACCESSKEY
	global LOGGER
	global SVCPORT
	global HTTPPORT
	global NICPREFIX
	global PGMROOT
	
	LOGFILE = 'gluster-deploy.log'
	LOGLEVEL = logging.getLevelName('DEBUG')		# DEBUG | INFO | ERROR
	
	logging.basicConfig(filename=LOGFILE, 
					level=LOGLEVEL, 
					filemode='w')
	
	LOGGER = logging.getLogger()
	
	NICPREFIX = ('eth', 'bond', 'em','virbr0','ovirtmgmt','rhevm')
	
	SVCPORT = 24007
	HTTPPORT = 8080
	
	PGMROOT = os.path.split(os.path.abspath(os.path.realpath(sys.argv[0])))[0]
	# glusterNodes
	
	
	pass
