#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  gluster.py
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

import xml.etree.ElementTree as ETree
import logging
import time
import os
import threading

from 	functions.syscalls 	import issueCMD, SSHsession
from 	functions.utils 	import logErrorMsgs
import 	functions.config as cfg

class Brick:
	
	def __init__(self,nodeName,deviceID, size,formatRequired=False):
		self.nodeName = nodeName
		self.deviceID = deviceID
		self.sizeMB = size
		self.formatRequired = formatRequired
		self.formatComplete = False			# deprecated
		self.formatStatus = 'pending'		# pending -> success || failed
		self.mountPoint = ""
		self.snapRequired = 'NO'
		self.snapReserve = 0 
		self.thinSize = 0
		self.poolSize = 0
		self.metadSize = 0
		
		self.tuned = ''						# setting used as a trigger during the 
											# the format to set the 'tuned' profile
		self.useCase = ""
		self.vgName = ""
		self.lvName = ""
		self.localDisk = False
		self.brickType = 'LVM'

	def setParms(self, settings):
		""" configure this brick based on the dict passed to it (settings) """
		
		# Use the dict to set all the bricks parameters
		for keyName in settings:
			if hasattr(self, keyName):
				setattr(self, keyName, settings[keyName])

		# Make some adjustments for snap enabled bricks
		if ( self.snapRequired == 'YES' ) and (self.brickType == 'LVM'):
			pct = 100 - self.snapReserve
			
			# usable space = pv size -4M (vg overhead)
			usable = self.sizeMB - 4

			# Adjust usable space if pv alignmeent is requested
			if cfg.STRIPEUNIT:
				if (cfg.STRIPEUNIT * cfg.STRIPEWIDTH)%1024 == 0:
					usable -= (cfg.STRIPEUNIT * STRIPEWIDTH) / 1024
				else:
					usable -= (((cfg.STRIPEUNIT * cfg.STRIPEWIDTH)/1024)+1)
			
			
			# if the disk is > 1TB, just use a flat 16GB max metadata region
			if self.sizeMB > 1000000:
				self.metadSize = 16384	# 16GB of pool metadata
			else:
				# otherwise, allocate 0.1% of the size as metadata rounded 
				# to nearest 4M (default PE size)
				temp = int(float(usable * 0.001)) 
				self.metadSize = temp if ( temp%4 ==0) else 4*((temp/4)+1)
				
			# meta data allocation is x2 due to the mirror of the metadata region			
			self.poolSize = int(usable - (self.metadSize*2))
			self.thinSize = int((self.poolSize / 100) * pct)
			
			# BZ998347 prevents a thinpool being defined with 100%PVS, so
			# getMuliplier used to look at the device size and decide on a
			# 'semi-sensible' % to use for the thinpool lv.
			#pctMultiplier = getMultiplier(self.sizeMB)
			#self.poolSize = int(((self.sizeMB - 4) * pctMultiplier))		# 99.9% of HDD
			#self.thinSize = int((self.poolSize / 100) * pct)

		
		
	def formatBrick(self,userPassword,raidCard):
		"""	Pass the node the format script for this brick """
		
		cfg.LOGGER.info('%s formatting %s as a brick on %s', time.asctime(), self.deviceID, self.nodeName )

		scriptPath = os.path.join(cfg.PGMROOT,'scripts/formatBrick.sh')
		scriptParms = ( " -D -d %s -c %s -b %s -v %s -s %s -l %s -p %s -M %s -m %s -u %s -n %s " % 
						(self.deviceID, 
						raidCard, 
						self.brickType, 
						self.vgName, 
						self.snapRequired, 
						str(self.thinSize), 
						str(self.poolSize),
						str(self.metadSize),
						self.mountPoint, 
						self.useCase,
						self.lvName) )
						
		if cfg.STRIPEUNIT:
			scriptParms += "-r %d -w %d "%(cfg.STRIPEUNIT, cfg.STRIPEWIDTH)
			
		if self.tuned:
			scriptParms += " -T %s "%(self.tuned)
						
		scriptName = scriptPath + scriptParms
		
		cfg.LOGGER.debug('%s Script invocation: %s', time.asctime(),scriptName)

		cfg.MSGSTACK.pushMsg("%s format on %s starting" %(self.deviceID, self.nodeName))

		
		# All formats are done over ssh including the local disks. If not
		# when tuned-adm is invoked by the formatDisk.sh script running under
		# the main thread, tuned 'acquires' the tcp port of gluster-deploy's
		# httpserver !
		#if self.localDisk:
		#	(rc, resp) = issueCMD(scriptName)
		#else:
		ssh=SSHsession('root',self.nodeName,userPassword)
		(rc, resp) = ssh.sshScript(scriptName,300)	# 300 sec timeout on the ssh session
			
		self.formatStatus = 'success' if (rc == 0) else 'failed'
		
		cfg.CLUSTER.opStatus[self.formatStatus] += 1
		
		cfg.MSGSTACK.pushMsg("%s format on %s ended, RC=%d" %(self.deviceID, self.nodeName, rc))
		
		cfg.LOGGER.debug('%s formatBrick complete on %s with retcode = %s', time.asctime(), self.nodeName, str(rc))
		
		return 			

class Node:
	def __init__(self, nodeName):
		self.nodeName = nodeName
		self.userName = 'root'
		self.localNode = False
		self.userPassword = ''
		self.inCluster = False
		self.hasKey = False
		self.diskScanned = False
		self.brickCreated = False			# not needed?
		self.diskList = {}					# device name pointing to Brick Object
		self.raidCard=''
		self.kernelVersion = ''
		self.kernelVersionFull = ''
		self.dmthinp = False
		self.btrfs = False
		self.glusterVersion = ''
		self.memGB = 0
		self.cpuCount = 0
		self.osVersion = ''
		self.tunedProfiles = []				# list of tuned profiles
		
		
	def pushKey(self):
		""" push the local machines root account ssh key to this node """
		
		sshTarget = SSHsession(self.userName, self.nodeName, self.userPassword)
		copyRC = sshTarget.sshCopyID()
		
		if copyRC <= 4:
			cfg.LOGGER.info('%s ssh key added successfully to %s', time.asctime(), self.nodeName)
			self.hasKey = True
		else:
			cfg.LOGGER.info('%s Adding ssh key to %s failed', time.asctime(), self.nodeName)
			self.hasKey = False
			
		
	def joinCluster(self):
		"""	run peer probe against this node """
		
		(rc, probeOutput) = issueCMD("gluster peer probe " + self.nodeName)
		
		if rc > 0:
			# update the clusterState properties
			cfg.LOGGER.debug("%s peer probe for %s failed (RC=%d)", time.asctime(), self.nodeName, rc)
			logErrorMsgs(probeOutput)
			self.inCluster = False
		else:
			# update the clusterState properties
			cfg.LOGGER.debug("%s peer probe for %s succeeded", time.asctime(), self.nodeName)
			self.inCluster = True
		pass
		
	def findDisks(self):
		"""	pass a scan script to the node, returning a list of unused disks in xml format """

		cfg.LOGGER.debug('%s getDisks scanning %s', time.asctime(), self.nodeName)
		
		scriptName = os.path.join(cfg.PGMROOT,'scripts/findDevs.py')
		
		cfg.LOGGER.debug('%s getDisks using script from %s', time.asctime(), scriptName)

		# check if this is the local node, if so, use issueCMD not ssh
		if self.localNode:
			(rc, diskOut) =  issueCMD(scriptName)
		else:
			sshTarget = SSHsession(self.userName, self.nodeName, self.userPassword)
			(rc, diskOut) = sshTarget.sshPython(scriptName)
		
		self.diskScanned = True

		if ( rc == 0 ):
			
			diskData = str(diskOut[0])
			xmlDoc = ETree.fromstring(diskData)
			freeDisks = xmlDoc.findall('disk')
			sysInfo = xmlDoc.find('sysinfo')
			
			# Process the sysinfo data, and update the node's attributes
			self.kernelVersion = sysInfo.attrib['kernel']
			self.dmthinp = True if sysInfo.attrib['dmthinp'] == 'yes' else False
			self.btrfs = True if sysInfo.attrib['btrfs'] == 'yes' else False
			self.glusterVersion = sysInfo.attrib['glustervers']
			self.memGB = int(sysInfo.attrib['memsize']) / 1024**2
			self.cpuCount = int(sysInfo.attrib['cpucount'])
			self.raidCard = sysInfo.attrib['raidcard']
			self.osVersion = sysInfo.attrib['osversion']
			
			self.tunedProfiles = sysInfo.attrib['tunedprofiles'].split(',')
			
			# Process the disk information
			for disk in freeDisks:
				deviceName = disk.attrib['device']
				sizeMB = int(disk.attrib['sizeKB']) / 1024
				
				brick = Brick(self.nodeName, deviceName, sizeMB)
				if self.localNode:
					brick.localDisk = True
				self.diskList[deviceName] = brick
				

		else:
			# Insert Scan failed logic here!
			pass
		
				
		cfg.LOGGER.debug('%s getDisks found %d devices on %s', time.asctime(), len(self.diskList), self.nodeName)
		
	def formatCount(self):
		""" Look at this objects disks, and return a count of the number of disks that 
			are flagged as needing to be formatted """
		
		fmtCount = 0
		
		for diskID in self.diskList:
			if self.diskList[diskID].formatRequired:
				fmtCount+=1
		
		return fmtCount
		
		
class Cluster:
	""" High Level 'cluster' object referencing nodes """
	
	def __init__(self):
		self.node={}
		self.volume={}
		self.glusterVersion=""
		self.brickType=""
		self.capability={}				# btrfs, thinp for example
		self.opStatus = { 'success':0, 'failed':0 }

	def addNode(self,newNode):
		""" Create a new node, and link it to this cluster object """
		
		thisNode = Node(newNode)
		thisNode.joinCluster()

		if thisNode.inCluster:
			self.node[newNode] = thisNode
	
	def addVolume(self, xmlDoc):
		""" Create a volume and link to this cluster object """
		newVolume = Volume(xmlDoc)
		volName = newVolume.volName
		self.volume[volName] = newVolume

		newVolume.createVolume()
	
	def nodeList(self):
		return sorted(self.node.keys())
	
	def volumeList(self):
		return sorted(self.volume.keys())
		
	def size(self):
		return len(self.node.keys())
		
	def resetOpStatus(self):
		self.opStatus['success'] = 0
		self.opStatus['failed'] = 0
		return

	def tunedProfiles(self):
		""" Process the nodes in the cluster to return a list of tuned 
			profiles common to all nodes
		"""
		
		allProfiles = []			# list of lists
		
		for nodeName in self.node:
			allProfiles.append(self.node[nodeName].tunedProfiles)
		
		# calculate common tuned profiles across all nodes
		commonProfiles = set.intersection(*map(set,allProfiles))
			
		return list(commonProfiles)
		

class Volume:
	
	def __init__(self,xmlDoc):

		self.bricks = []
		self.protocols = {}
		self.virtTarget = ''
		
		# Volume parameters
		volumeSettings = xmlDoc.find('settings')
		self.volName = volumeSettings.attrib['name']
		self.volType = volumeSettings.attrib['type']
		self.volDirectory = volumeSettings.attrib['voldirectory']
		self.useCase = volumeSettings.attrib['usecase'].lower()
		self.replicaParm = ' ' if ( volumeSettings.attrib['replica'] == '1') else (' replica ' + volumeSettings.attrib['replica'])
		
		if self.useCase == 'virtualisation':
			self.virtTarget = xmlDoc.find('./usecase/virttarget').text.lower()
		
		if self.useCase == "hadoop":
			self.hadoopMountPoint = xmlDoc.find('./usecase/hadooppath').text


		for child in xmlDoc.findall('.//brick'):
			self.bricks.append(child.attrib['fullpath'])

		self.protocols['nfs'] = 'off' 	if ( xmlDoc.find('protocols').attrib['nfs'] == 'true' )  else 'on'
		self.protocols['cifs'] = 'on' 	if ( xmlDoc.find('protocols').attrib['cifs'] == 'true' ) else 'off'


		self.settings = []					# list of vol set commands used
		self.state = ""						# created, failed or null 
		self.retCode = 0
		self.createMsgs = []				# output from each cmd used to 
											# create the volume
		
		
	def createVolume(self):
		"""	function to define a gluster volume given an xml volume definition """
	
		cmdQueue = []
		
		# protocols
		NFSstate  = 'nfs.disable off'  if ( self.protocols['nfs'] == 'off' )  else 'nfs.disable on'
		CIFSstate = 'user.cifs enable' if ( self.protocols['cifs'] == 'on' ) else 'user.cifs disable'
		
					
		# create volume syntax
		createCMD = "gluster vol create " + self.volName + self.replicaParm + " transport tcp "
		for brick in self.bricks:
			createCMD += brick + "/" + self.volDirectory + " "
		
		#createCMD += " force"		# added to allow the root of the brick to be used (glusterfs 3.4)
		
		cmdQueue.append(createCMD)
		
		# Post Processing Options
		cmdQueue.append('gluster vol set ' + self.volName + ' ' + NFSstate)
		cmdQueue.append('gluster vol set ' + self.volName + ' ' + CIFSstate)
		
		if self.useCase == 'hadoop':
			# Added based on work done by Jeff Vance @ Red Hat
			cmdQueue.append('gluster vol set ' + self.volName + ' quick-read off')
			cmdQueue.append('gluster vol set ' + self.volName + ' cluster.eager-lock on')
			cmdQueue.append('gluster vol set ' + self.volName + ' performance.stat-prefetch off')
			pass
			
		elif self.useCase == 'virtualisation':
			
			# look to see what type of virt target it is
			if self.virtTarget == 'glance':
				cmdQueue.append('gluster vol set ' + self.volName + ' storage.owner-gid 161')
				cmdQueue.append('gluster vol set ' + self.volName + ' storage.owner-uid 161')
				pass
			elif self.virtTarget == 'cinder':
				cmdQueue.append('gluster vol set ' + self.volName + ' storage.owner-gid 165')
				cmdQueue.append('gluster vol set ' + self.volName + ' storage.owner-uid 165')
				pass
			elif self.virtTarget == 'rhev':
				cmdQueue.append('gluster vol set ' + self.volName + ' storage.owner-gid 36')
				cmdQueue.append('gluster vol set ' + self.volName + ' storage.owner-uid 36')				
			
			if ( self.virtTarget in ['cinder','rhev'] ):
				
				# Is the virt group available to use
				if os.path.isfile('/var/lib/glusterd/groups/virt'):
					cmdQueue.append('gluster vol set ' + self.volName + ' group virt')
					pass
				else:
					# Fallback settings if local virt group definition is not there
					cmdQueue.append('gluster vol set ' + self.volName + ' quick-read  off')
					cmdQueue.append('gluster vol set ' + self.volName + ' read-ahead  off')
					cmdQueue.append('gluster vol set ' + self.volName + ' io-cache  off')
					cmdQueue.append('gluster vol set ' + self.volName + ' stat-prefetch  off')
					cmdQueue.append('gluster vol set ' + self.volName + ' eager-lock enable')
					cmdQueue.append('gluster vol set ' + self.volName + ' remote-dio enable')
					pass
				
		self.settings = list(cmdQueue)
			
		# Add volume start to the command sequence
		cmdQueue.append('gluster vol start ' + self.volName)
	
		# log the number of commands that will be run
		numCmds = len(cmdQueue)
		cfg.LOGGER.debug("%s Creating volume %s - %d steps", time.asctime(), self.volName, numCmds)
		
		cfg.MSGSTACK.pushMsg(" ")
		cfg.MSGSTACK.pushMsg("Processing '%s'"%(self.volName))
		
		# Process the command sequence	
		retCode = 0
		stepNum = 1
		
		
		# Pre CREATE phase ##############################################################
		# Volumes are defined on directories on the brick, so the first thing to do 
		# is prepare the brick with the required directory

		for brick in self.bricks:
			(hostName, brickPath) = brick.split(':')
			node = cfg.CLUSTER.node[hostName]
			
			cfg.MSGSTACK.pushMsg("Creating directory on %s" %(hostName))
			cfg.LOGGER.info("%s Creating %s/%s directory on node %s", time.asctime(), brickPath, self.volDirectory, hostName)
			
			s=SSHsession(node.userName, node.nodeName)
			(rc, mkdirOut) = s.ssh('mkdir %s/%s'%(brickPath, self.volDirectory))
			
			if ( rc > 0):
				
				cfg.MSGSTACK.pushMsg("Directory preparation failed")
				cfg.LOGGER.debug("%s step %d/%d successful", time.asctime(), stepNum, numCmds)
				
				retCode = 12
				break
			
		
		if retCode == 0:
			for cmd in cmdQueue:
				
				cmdType = ' '.join(cmd.split()[1:3]) + ' ...'
				cfg.MSGSTACK.pushMsg("Step %d/%d starting (%s)" %(stepNum, numCmds,cmdType))
				
				(rc, cmdOutput) = issueCMD(cmd)
				
				self.createMsgs += cmdOutput
				
				if rc == 0:	# retcode is 1st element, so check it's 0
								
					# push this cmd to the queue for reporting in the UI
					cfg.MSGSTACK.pushMsg("Step %d/%d completed" %(stepNum, numCmds))
					
					# Log the cmd being run as successful
					cfg.LOGGER.info("%s step %d/%d successful", time.asctime(), stepNum, numCmds)
					cfg.LOGGER.debug("%s Command successful : %s", time.asctime(), cmd)
					
				else:
					cfg.LOGGER.info("%s vol create step failed", time.asctime())
					
					cfg.LOGGER.debug("%s command failure - %s", time.asctime(), cmd)
					
					cfg.MSGSTACK.pushMsg("Step %d/%d failed - sequence aborted" %(stepNum, numCmds))
					
					# problem executing the command, log the response and return
					retCode = 8
					break
					
				stepNum +=1
	
	
		# post CREATE phase ###################################################
		#
		if retCode == 0:
		
			if self.useCase == 'hadoop':
				msg = "Mounting '%s' on all nodes"%(self.volName)
				cfg.LOGGER.debug("%s Post configuration for hadoop volume use case", time.asctime())
				cfg.MSGSTACK.pushMsg("'hadoop' use case post processing...")
				
				retCode = self.mountVolume()	# Mounts this volume across all nodes
				
			else:
				pass
			
			
		
		
		
		
		self.state = "Succeeded" if retCode == 0 else "Failed"
		
		self.retCode = retCode
		
		cfg.MSGSTACK.pushMsg("'%s' creation - %s"%(self.volName, self.state))

		
	def mountVolume(self):
		"""Mount the volume across all nodes in the cluster"""
		
		rc = 0
		
		for node in cfg.CLUSTER.nodeList():
			thisNode = cfg.CLUSTER.node[node]
			host = thisNode.nodeName
			vol = self.volName
			path = self.hadoopMountPoint
			
			scriptPath = os.path.join(cfg.PGMROOT,'scripts/postCreate.sh')
			scriptParms = " -a mount -n %s -m %s -v %s"%(host, path, vol)
			scriptName = scriptPath + scriptParms
			
			cfg.LOGGER.info("%s postCreate.sh invoked against %s", time.asctime(), host)
			cfg.MSGSTACK.pushMsg("Mounting '%s' on %s"%(vol, host))
			
			
			s=SSHsession(thisNode.userName, thisNode.nodeName)
			(rc, resp) = s.sshScript(scriptName,30)	# 30 sec timeout for the mount script
			
			cfg.LOGGER.info("%s postCreate.sh completed on %s, with RC= - %d", time.asctime(), host, rc)
			
			if ( rc > 0 ):
				
				break
			
		return rc	
			


class FormatDisks(threading.Thread):
	
	def __init__(self,nodeObject):
		self.node = nodeObject
		threading.Thread.__init__(self)
	
	def run(self):
		""" Loop through the disks that need formatting on this node """
		
		cfg.LOGGER.debug("%s Thread started to process disk formats for node %s", time.asctime(), self.node.nodeName)
		
		thisNode = self.node
		
		for diskID in self.node.diskList:
			thisDisk = self.node.diskList[diskID]
			if thisDisk.formatRequired:
				thisDisk.formatBrick(thisNode.userPassword,thisNode.raidCard)
				pass
	
		
		cfg.LOGGER.debug("%s Format thread complete for node %s", time.asctime(), self.node.nodeName)
		
		return
		


if __name__ == '__main__':
	pass

