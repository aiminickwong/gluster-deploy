#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  webservices.py
#  
#  Copyright 2014 Paul <paul@rhlaptop>
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

import BaseHTTPServer
import SimpleHTTPServer
import SocketServer
import httplib
import time
import xml.etree.ElementTree as ETree

import 	functions.config as cfg
from 	functions.network 		import getSubnets,findService
from 	functions.gluster		import Cluster, Volume
from 	functions.syscalls		import getMultiplier
from 	functions.utils			import kernelCompare


class RequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
	
	adminIP = ''
	pollingEnabled = False
	pollingEnabledTasks = ['build-bricks','vol-create', 'find-nodes']

	def do_GET(self):
		""" 
		Override get method, checking the client IP to prevent more than
		client IP connecting to the webserver at the same time
		"""
		thisIP = self.client_address[0]

		if RequestHandler.adminIP == '':
			RequestHandler.adminIP = thisIP
			cfg.LOGGER.info("%s Admin access to the interface is locked to %s", time.asctime(), thisIP)

		if thisIP != RequestHandler.adminIP:
			self.path = "/www/disallowed.html"
			cfg.LOGGER.info("%s Setup wizard access attempt from %s DENIED", time.asctime(), thisIP)

		return SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)

	def do_QUIT(self):
		""" Internal quit handler to terminate additional request threads """
		
		self.send_response(200)         # completed ok
		self.end_headers()              # blank line end of http response
		self.server.stop=True
		self.finish()

		 
		 
	def do_POST(self):
		""" 
		Handle a post request looking at it's contents to determine the action to take
		"""
		
		self.daemon=True		
		

		length = int(self.headers.getheader('content-length'))        
		dataString = self.rfile.read(length)
		

		try:
			xmlRoot = ETree.fromstring(dataString)
			requestType = xmlRoot.find('./request-type').text
			
		except:
			print "XML parsing error - string received was " + dataString
			self.server.stop = True
			exit(8)
			return

		if requestType in RequestHandler.pollingEnabledTasks:
			cfg.LOGGER.debug("%s Message polling from the client is enabled for %s", time.asctime(),requestType)
			RequestHandler.pollingEnabled = True
		
		if ( requestType == "password" ):
			
			if cfg.PASSWORDCHECK:
				
				userKey = xmlRoot.find('password').text
				
				if userKey == cfg.ACCESSKEY:
					cfg.LOGGER.debug('%s passwordCheck matched users access key',time.asctime())
					retString = 'OK'
				else:
					cfg.LOGGER.debug('%s passwordCheck unable to match users password(%s)',time.asctime(),userKey)
					retString = 'NOTOK'

			else:
				# PASSWORDCHECK turned off so just return OK
				cfg.LOGGER.info('%s passwordCheck bypassed by -n parameter',time.asctime())
				retString = 'OK'
			
			response = "<response><status-text>" + retString + "</status-text></response>"
			
			self.wfile.write(response)	
				
			
		elif ( requestType == "subnet-list" ):

			response = "<response><status-text>"

			# If there are servers in the SERVERLIST, we pass back the server IP/names not
			# subnets to allow subnet selection and scan to be bypassed
			if cfg.SERVERLIST:
				cfg.LOGGER.info("%s Bypassing subnet scan, using nodes from configuration file", time.asctime())
				response += "OK</status-text><request-type>servers</request-type>"
				response += "</response>"
				
				print "\t\tHost list from the configuration file passed to the UI (bypassing subnet scanning)"
				
			else:
				# server list has not been provided, so let look at the hosts IP config and 
				# get a list of subnets for the admin to choose from for the subnet scan

				subnets = getSubnets()
				
				if subnets:
					response = "<response><status-text>OK</status-text><request-type>scan</request-type>"
					for subnet in subnets:
						response += "<subnet>" + subnet + "</subnet>"
					response += "</response>"
	
					allSubnets = ' '.join(subnets)
				
					cfg.LOGGER.debug("%s network.getSubnets found - %s", time.asctime(), allSubnets)
					
					print "\t\tHost checked for active NIC's"				
				
				else:
					response = "<response><status-text>FAILED</status-text></response>"
				
			self.wfile.write(response)
			
		elif ( requestType == "find-nodes" ):
			
			scanType = xmlRoot.find('scan-type').text
			
			if scanType == 'subnet':
				scanTarget = xmlRoot.find('subnet').text
				cfg.LOGGER.info('%s network.findService starting to scan %s', time.asctime(), scanTarget)
			elif scanType == 'serverlist':
				scanTarget = " ".join(cfg.SERVERLIST)
				cfg.LOGGER.info('%s network.findService processing server list', time.asctime())
			
	
			nodeList = findService(scanTarget,cfg.SVCPORT)
			
			if nodeList:
				response = "<response><status-text>OK</status-text>"
				for node in nodeList:
					response += "<node>" + node + "</node>"
				response += "</response>"
					
				cfg.LOGGER.info('%s network.findService scan complete', time.asctime())
				cfg.LOGGER.debug("%s network.findService found %s services", time.asctime(), str(len(nodeList)))

			else:
				response = "<response><status-text>FAILED</status-text></response>"

			print "\t\tNodes scanned for open glusterd ports - " + str(len(nodeList)) + " found"
			
			# Using the list of servers for the nodes completes really quickly, and they never get displayed
			# but stack in the message stack, appearing on the next tasks msg log. To prevent this, we drop
			# the msg stack.
			if scanType == 'serverlist':
				cfg.MSGSTACK.reset()
			
			self.wfile.write(response)
			
			RequestHandler.pollingEnabled = False	
			
		
		elif (requestType == "create-cluster"):

			nodeElements = xmlRoot.findall('node')
			nodeList = []
			for node in nodeElements:
				nodeList.append(node.text)

			success = 0 
			failed = 0
			cfg.LOGGER.info('%s createCluster joining %s nodes to the cluster', time.asctime(), (len(nodeList)-1))
						
			# create the node objects 
			for nodeName in nodeList:

				if nodeName.endswith('*'):
					# this is the local node, lose the last char
					nodeName = nodeName[:-1]
					
					# create a node object and set to local
					# no need for joincluster or success/fail increment on the local node
					cfg.CLUSTER.addNode(nodeName)
					cfg.CLUSTER.node[nodeName].localNode = True

				else:
					
					# create a node object
					cfg.CLUSTER.addNode(nodeName)
					
					if cfg.CLUSTER.node[nodeName].inCluster:
						success += 1
					else:
						failed +=1
				
			# Build XML response string
			respText = "OK" if failed == 0 else "FAILED"
			response = ( "<response><status-text>" + respText + "</status-text><summary success='" + str(success)
						+ "' failed='" + str(failed) + "' />")
			
			# Add the nodes successfully added to the response	(sorted for display purposes)		
			for nodeName in cfg.CLUSTER.nodeList():
				if not cfg.CLUSTER.node[nodeName].localNode:
					response += "<node name='" + nodeName + "' />"
			
			response += "</response>" 
			
			cfg.LOGGER.debug('%s createCluster results - success %d, failed %d',time.asctime(), success, failed)
			
			print "\t\tCluster created - added " + str(success) + " nodes to this node (" + str(failed) + " nodes failed)"

			# return success and failed counts to the caller (UI)			
			self.wfile.write(response)
			
			cfg.LOGGER.info('%s gluster.createCluster complete - %d successful, %d failed', time.asctime(), success, failed)			
		

		
		elif ( requestType == "push-keys" ):

			success = 0
			failed = 0
						
			nodes = xmlRoot.findall('node')
			for node in nodes:
				nodeName = node.attrib['server']
				nodePassword = node.attrib['password']
				
				thisNode = cfg.CLUSTER.node[nodeName]
				thisNode.userPassword = nodePassword
				thisNode.pushKey()
				if thisNode.hasKey:
					success += 1
				else:
					failed += 1

			
			cfg.LOGGER.info('%s pushKeys distributing ssh keys to %d nodes', time.asctime(), len(nodes))

			respText = "OK" if failed == 0 else "FAILED"
			response = ( "<response><status-text>" + respText + "</status-text><summary success='" 
						+ str(success) + "' failed='" + str(failed) + "' /></response>" )
						
			self.wfile.write(response)
			
			cfg.LOGGER.info('%s pushKeys complete - success %d, failed %d', time.asctime(), success, failed)
			
			print "\t\tSSH keys distributed"
			
			
			
		elif ( requestType == "find-disks" ):		
			# receive the same list as sent to the keys
			# it only makes sense to try to get disk info from the successful
			# nodes where the ssh key copy worked
			
			retString = '<data>'
			diskCount = 0
			
			cfg.LOGGER.info('%s findDisks invoked', time.asctime())
			for nodeName in cfg.CLUSTER.nodeList():
				
				# Scan this node for unused disks
				thisNode = cfg.CLUSTER.node[nodeName]
				thisNode.findDisks()
				
				# Look at this nodes diskList - if it's not empty add it to an XML string 
				# to return to the caller
				if thisNode.diskList:
				
					retString = retString + "<node><nodename name='" + nodeName + "'/><disks>"
					for deviceID in sorted(thisNode.diskList):
						diskObj = thisNode.diskList[deviceID]
						sizeGB = diskObj.sizeMB / 1024
						retString = retString + "<device id='" + deviceID + "' size='" + str(sizeGB) + "' />"
						diskCount += 1
					retString = retString + "</disks></node>"

			retString = retString + "</data>"

			self.wfile.write(retString)
			
			cfg.LOGGER.info('%s findDisks complete', time.asctime())
			print "\t\tNodes scanned for available (free) disks (" + str(diskCount) + " found)"
			

			
		elif ( requestType == "register-bricks" ):

			devices = xmlRoot.findall('device')
			
			# Cycle through the devices, and set the formatRequired flag
			for device in devices:
				targetHost = device.attrib['host']
				targetDevice = device.attrib['device']
				
				thisNode = cfg.CLUSTER.node[targetHost]
				
				brick = thisNode.diskList[targetDevice]
				brick.formatRequired=True 
			
			response = "<response><status-text>OK</status-text>"
			response += "<brick path='" + cfg.BRICKPATH + "' vgname='" + cfg.VGNAME + "' lvname='" + cfg.LVNAME + "' />"

			# Determine whether snapshots are available, by looking at the capabilities
			# of every node in the cluster. They must all tally for these features to be 
			# used.
			
			thinpSupport = "YES"
			btrfsSupport = "YES"
			
			# use a dict to determine if nodes are all on same version, or mixed
			versionLookup={}
			
			# cycle through all nodes. They must ALL match to have snapshot or btrfs 
			# features enabled
			for nodeName in cfg.CLUSTER.nodeList():   
				thisNode = cfg.CLUSTER.node[nodeName]
				thisVersion = thisNode.glusterVersion
				versionLookup[thisVersion] = 'OK'
				
				if thisNode.dmthinp == False:
					thinpSupport = "NO"
				if (thisNode.btrfs == False) or (not kernelCompare(thisNode.kernelVersion[:2])):
					btrfsSupport = "NO"
			
			# Update the cluster's capability based on the findings from 
			# each node
			cfg.CLUSTER.capability['btrfs'] = btrfsSupport
			cfg.CLUSTER.capability['thinp'] = thinpSupport
			cfg.CLUSTER.glusterVersion = thisVersion if len(versionLookup) == 1 else "Mixed (Warning!)"
			
			response += "<features snapshot='" + thinpSupport + "' btrfs='" + btrfsSupport + "' />"
			response += "</response>"
			
			self.wfile.write(response)
		
			
		elif ( requestType == "build-bricks" ):		
			
			success = 0 
			failed = 0
			
			# process the parameter XML file to set variables up for the script			
			parms = xmlRoot.find('brickparms')
			
			useCase = parms.attrib['usecase']
			brickType = parms.attrib['brickprovider']			# LVM or BTRFS
			snapRequired = parms.attrib['snaprequired']			# YES or NO

			lvName = parms.attrib['lvname'] if ( brickType == 'LVM' ) else ""
			vgName = parms.attrib['volgroup'] if (brickType == 'LVM') else ""
			
			if snapRequired == 'YES':
				snapReserve = int(parms.attrib['snapreserve'])
			else:
				snapReserve = 0
			
			mountPoint = parms.attrib['mountpoint']

			# Maintain a list of bricks that were formatted to pass back to the
			# UI for brick selection when creating the volume
			brickList = []	
						
			for nodeName in cfg.CLUSTER.nodeList():

				thisNode = cfg.CLUSTER.node[nodeName]
				multipleDisks = False
				
				# take a look at this nodes disk list 
				# for each disk with formatrequired
				# 	call the formatbrick method
				# 	if ret_code is ok update the state of the brick and
				#      post message to queue
				if thisNode.diskList:
					
					if thisNode.formatCount() > 1:
						# Set a suffix to add to mountpoint and lvname
						sfx = 1
						multipleDisks = True
						
						# adjust the mountpoint and lvname if they end in a number
						if mountPoint[-1].isdigit():
							mountPoint = mountPoint[:-1]
						if lvName[-1].isdigit():
							lvName = lvName[:-1]

						
					for diskID in thisNode.diskList:
						thisDisk = thisNode.diskList[diskID]
						
						if thisDisk.formatRequired:
							cfg.LOGGER.debug('%s format requested for node %s, disk %s',time.asctime(), nodeName, thisDisk.deviceID)

							if multipleDisks:
								thisDisk.mountPoint = mountPoint + str(sfx)
								thisDisk.lvName     = lvName + str(sfx)
								sfx += 1
							else:
								thisDisk.mountPoint = mountPoint
								thisDisk.lvName = lvName
							
							thisDisk.vgName = vgName
							thisDisk.brickType = brickType
							thisDisk.snapReserve = snapReserve
							thisDisk.useCase = useCase

							thisDisk.snapRequired = snapRequired
							if ( thisDisk.snapRequired == 'YES' ):
								pct = 100 - snapReserve
								
								# BZ998347 prevents a thinpool being defined with 100%PVS, so
								# getMuliplier used to look at the device size and decide on a
								# semi-sensible % to use for the thinpool lv.
								pctMultiplier = getMultiplier(thisDisk.sizeMB)
								thisDisk.poolSize = int(((thisDisk.sizeMB - 4) * pctMultiplier))		# 99.9% of HDD
								thisDisk.thinSize = int((thisDisk.poolSize / 100) * pct)
							
							# issue command, and check status of the disk
							thisDisk.formatBrick(thisNode.userPassword,thisNode.raidCard)
							
							if thisDisk.formatStatus == 'complete':
								brickList.append(thisDisk)
								success += 1
							else:
								failed += 1


			
			# Future: check the brickList to only allow bricks of the same size through to vol create
			
			# Now the bricks have been formatted, we process the list
			# to assemble an xml string ready for the UI to load into an
			# array for use in the volCreate step				
			respText = 'OK' if (failed == 0 ) else 'FAILED'
			response = ( "<response><status-text>" + respText + "</status-text>"
						+ "<summary success='" + str(success) + "' failed='" + str(failed) + "' />" )
			
			for brick in brickList:
				# eg. <brick fsname='/gluster/brick' size='10' servername='rhs1-1' />

				sizeGB = ( brick.sizeMB / 1024 ) if brick.thinSize == 0 else ( brick.thinSize / 1024 )

				response += "<brick fsname='" + brick.mountPoint + "' size='" + str(sizeGB) + "' servername='" + brick.nodeName + "' />"
			response += "</response>"

			# Send to UI
			self.wfile.write(response)
			
			print "\t\tBricks formatted : " + str(success) + " successful, " + str(failed) + " failed"

			RequestHandler.pollingEnabled = False
		
	
		elif ( requestType == "vol-create" ):
			
			cfg.LOGGER.info('%s Initiating vol create process', time.asctime())
			
			cfg.CLUSTER.addVolume(xmlRoot)
			
			# Get the last volume from the cluster's volume list
			volName = cfg.CLUSTER.volumeList()[-1]
			
			# Look at the return code from the create process
			rc = cfg.CLUSTER.volume[volName].retCode
			
			if rc == 0:
				# Create volume was successful
				cfg.LOGGER.info('%s Volume creation was successful', time.asctime())
				msg = 'OK'
			else:
				# Problem creating the volume
				cfg.LOGGER.info('%s Volume creation failed rc=%d', time.asctime(), rc)
				msg = 'FAILED'
			
			response = "<response><status-text>" + msg + "</status-text></response>"
				
			self.wfile.write(response)	
			
			print "\t\tVolume create result: " + msg	
			
			RequestHandler.pollingEnabled = False	


		elif (requestType == "query-status"):
			
			cfg.LOGGER.debug("%s query-status received from the web client", time.asctime())
			
			msgs = cfg.MSGSTACK.popMsgs()
			
			xmlMsgs = ""
			for msg in msgs:
				xmlMsgs += "<message>" + msg + "</message>"
			
			
			respText = "OK" if ( ( RequestHandler.pollingEnabled ) or ( len(msgs) > 0 ) ) else "NOTOK"
			response = ( "<response><status-text>" + respText + "</status-text>"
						+ xmlMsgs + "</response>")
			
			cfg.LOGGER.debug("%s query-status returned %s", time.asctime(), response)
			
			self.wfile.write(response)
			
			self.request.close()
			
						
		elif ( requestType == "quit"):
			print "\t\tQuit received from the UI, shutting down"
			
			# Update the httpd servers state, so the run forever loop can be exited
			self.server.stop = True
			self.dummyRequest()		# Send a dummy request to force thread termination

		
	def dummyRequest(self):
		""" Forces a dummy request to ensure thread termination """
		conn = httplib.HTTPConnection('localhost:8080')
		conn.request('QUIT','/')
		self.server.stop=True
		conn.getresponse()
						

			

	def log_message(self, format, *args):
		""" Override std log_message method to record http messages only for debug mode """
			
		if cfg.LOGLEVEL == 10:				# 10 = DEBUG, 20=INFO, 30=WARN
			cfg.LOGGER.debug("%s %s %s", time.asctime(), self.address_string(), args)
		return


class StoppableHTTPServer ( SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
	""" Standard HTTPServer extended with a multi-threading and a 'Stop' capability - SocketServer.ThreadingMixIn,"""
	
	daemon_threads = True 	# Ensure ctrl-c kills all spawned threads
	
	def serve_forever(self):
		""" Overridden method to insert the stop process """
		self.stop = False
		self.daemon=True	
		while not self.stop:
			self.handle_request()

if __name__ == '__main__':
	pass

