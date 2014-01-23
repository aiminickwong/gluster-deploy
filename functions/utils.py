#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  utils.py
#  
#  Copyright 2013 Paul <paul@rhlaptop>
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

import threading
import os
import ConfigParser						# renamed to configparser in python3!
import socket

import network							# local module

import globalvars as g					# bring in the global variables
import time 


class MsgStack:
	""" 
	Class used to hold progress messages, enabling the current state to be queried
	and used by the UI
	"""
	
	def __init__(self):
		self.messages = []
		self.lock = threading.Lock()

	def popMsgs(self):
		""" Funtion to pop the current entries from the list and return them """

		msgList = []
		
		self.lock.acquire()
		if len(self.messages) > 0:
			msgList = list(self.messages)
			del self.messages[:]	# drop all current elements
		self.lock.release()

		return msgList
		
	def pushMsg(self,msg):
		""" Receive a msg and add it to the current message list """
		self.lock.acquire()
		self.messages.append(msg)
		self.lock.release()
		return
		

	def msgsQueued(self):
		""" Return a count of the size of the message stack """
		return len(self.messages)
		
	def reset(self):
		""" drop existing messages on the list """
		self.lock.acquire()
		del self.messages[:]
		self.lock.release()
		return

def kernelCompare(thisKernel, kernelTarget):	
	""" Receive current and target kernels, return true if the current is > target """
		
	result = False
	
	(k1version, k1release) = thisKernel.split('.')
	(k2version, k2release) = kernelTarget.split('.')
	
	if k1version >= k2version:
		if int(k2release) >= int(k1release):
			result = True
			
	return result


def processConfigFile(configFileName):
	""" 
	Receive a user specfiied configuration file, process it to update global
	runtime settings
	"""
	
	config = ConfigParser.ConfigParser()
	config.read(configFileName)
	
	try:
		nodeNames = config.get("nodes","nodenames").split()
	except:
		print "\t\t-> Config file does not contain valid 'nodes' section, subnet scan will be used"

	try:
		brickPath = config.get("brick","brickpath")
	except:
		print ( "\t\t-> brickpath setting not provided, a default of " 
				+ g.BRICKPATH + "will be used")

	try:
		vgName = config.get("brick","vgname")
	except:
		print ( "\t\t-> vgname not provided, a default of " 
				+ g.VGNAME + "will be used")
				
	try:
		lvName = config.get("brick","lvname")
	except:
		print ( "\t\t-> lvname not provided, a default of "
				+ g.LVNAME + "will be used")


	
	if nodeNames:
		for node in nodeNames:
			
			# process each node to make sure it's a valid IP or name
			# if not drop from the serverList
			if not network.hostOK(node):
				print "\t\t-> dropping " + node + " (name doesn't resolve, or IP is invalid)"
				nodeNames.remove(node)
			else:
				g.LOGGER.info("%s server %s accepted as a potential gluster node", time.asctime(), node)
				
		g.SERVERLIST = sorted(nodeNames)
		
	if brickPath:
		print "\t\t-> Using '" + brickPath + "' for the default brick path"
		g.LOGGER.info("%s config file provided brick path name of %s", time.asctime(), brickPath)
		g.BRICKPATH = brickPath

	if vgName:
		print "\t\t-> Using '" + vgName + "' as the volume group"
		g.LOGGER.info("%s config file provided vg of %s", time.asctime(), vgName)
		g.VGNAME = vgName
	if brickPath:
		print "\t\t-> Using '" + lvName + "' for LV name"
		g.LOGGER.info("%s config file provided lv name of %s", time.asctime(), lvName)
		g.LVNAME = lvName
		
	return 


if __name__ == '__main__':
	pass

