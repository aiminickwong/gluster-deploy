
/*
 * This package provides generic functions that are used within the UI
 * across all the other functional components 
 * 
 */
 

function validPathName(pathName) {
	// use a regex to validate a given path
	
	var pathRegex = /^\/[a-z0-9\/]*$/;
	return (pathName.match(pathRegex) ) ? true :false;
	
}

function fade(elementName,state) {
	
	// Give state a default to disable the element
	var state = state || 'disable'
	
	// Toggle the fade attribute of the given element
	
	if (document.getElementById(elementName).className == 'fade') {
		document.getElementById(elementName).className ='';
	}
	else {
		document.getElementById(elementName).className ='fade'
		
		if (state == "disable") {
			disableDiv(elementName)
		}
	}
}

function disableDiv(divName) {
	// Disable the div first
	document.getElementById(divName).disabled = true;
	
	// now loop through the other elements in the div and disable them 
	var nodes = document.getElementById(divName).getElementsByTagName('*');
	for(var i = 0; i < nodes.length; i++) {
		nodes[i].disabled = true;
	}
}

function slide(newDiv) {
	
	switch (newDiv) {
		
		case 'error' :
			disableDiv('toolbar');
			document.getElementById('toolbar').className = 'invisible'
			break;
		
		default : 
			// Update the menu area
			var oldTask = 'm-' + currentPage
			var newTask = 'm-' + newDiv
			document.getElementById(oldTask).className = 'done';
			document.getElementById(newTask).className = 'active';
			break;
	}
	
	disableDiv(currentPage);
	
	document.getElementById(newDiv).className = 'slide';
	
	currentPage = newDiv;
	
	document.getElementById('quitBtn').disabled = false;
	
}

function showBusy(msg) {
	
	var msg = msg || '';
	document.getElementById('busyMsg').innerHTML = msg;
	
	// if the busy dialog is visible, turn it off
	if (document.getElementById('busy').style.visibility == 'visible') {

		document.getElementById('busy').style.visibility = 'hidden';
		document.getElementById('busyGraphic').className = 'spinner';
		document.getElementById('busyButton').disabled = true;
		document.getElementById('busyButton').style.visibility = 'hidden';
		document.getElementById('busyLog').className = "";
		document.getElementById('busyLog').innerHTML = "";
		msgLog.length = 0									// reset the message log array
		
		document.getElementById('quitBtn').disabled = false;
	}
	else {
		
		// the busy dialog box was hidden, so show it and disable the quit
		// button
		document.getElementById('busy').style.visibility = 'visible';
		document.getElementById('quitBtn').disabled = true;
	}
	
}

function enableButton(buttonName) {

	document.getElementById(buttonName).disabled = false;
}

function updateCheckbox(checkboxName, state) {
	// function that just toggles the checked state of all checkboxes in a given group
	
	var checkboxes = document.getElementsByName(checkboxName);
	var numCheckboxes = checkboxes.length;
	
	for (var i=0; i<numCheckboxes; i++) {
		checkboxes[i].checked = state;
	}
		
}



function disableRadio(radioName) {
	radioButtons = document.getElementsByName(radioName);
	numButtons = radioButtons.length;
	for (var n =0; n < numButtons; n++) {
		radioButtons[n].disabled = true;
	}
}

//function toggleElement(elementName) {
	// Simply toggle the disabled true or false of a given element
	
//	currentState = document.getElementById(elementName).disabled; 
//	document.getElementById(elementName).disabled = !currentState; 
//}


function formatGB(gb) {
	// Receive a GB value, scale it and add a t or g suffix
	if (gb < 1000) {
		val = gb + "g"
	}
	else {
		val = (gb/1000);
		val = val.toFixed(1) + "t"
	}
	return val;
}

function emptyTable(tableName) {
	// Receive a table name, and then delete the rows in it
	thisTable = document.getElementById(tableName);
	
	// find the number of table rows
	var numRows = (thisTable.tBodies[0].rows.length) - 1;

	// loop, deleting these rows (except for 1st row)		
	for ( var i= numRows; i>0; i--) {
		thisTable.deleteRow(i)
	}
	
	// empty the data from the first cell		
	thisTable.rows[0].cells[0].innerHTML = " ";
	
}

function countSelected(elementName) {
	// Return the number of selected items in a given list/selectbox
	
	var options = document.getElementById(elementName).options;
	var count = 0;
	for ( var i = 0; i< options.length; i++) {
		
		if (options[i].selected) {
			//alert(options[i].value + " .. " + count);
			count = count + 1;
		}
	}

	return count
}

function removeSelected(selectBox) {
	// remove any selected item in the given "select box"
	
	thisBox = document.getElementById(selectBox)
	
	for (var i = thisBox.options.length-1; i>=0; i--) {
		if (thisBox.options[i].selected == true) {
			thisBox.remove(i);
		}
	}
}

function shutDown() {
	// Send a quit message to the python web server to shut down 
	// the script
	
	var xmlString = "<data><request-type>quit</request-type></data>";
	
	xml_http_post('../www/main.html', xmlString, dummyHandler);
}

function dummyHandler(req) {
	var xmlDoc = req.responseXML;
}

function showMountHelp() {
	window.location = ('../www/mounthelp.html');
	
	//shutDown();
}

function quitUI() {
	
	// remove the quit button from the UI
	parent = document.getElementById('finish');
	child = document.getElementById('quitButton');
	parent.removeChild(child);
	
	// remove the hyperlink, if it exists on the page
	if ( document.getElementById('mountHelp') ) {
		link = document.getElementById('mountHelp'); 
		link.removeAttribute('href');
	}
	
	// hide the toolbar
	document.getElementById('toolbar').className = "invisible";
		
	document.getElementById('goodbye').className = 'reveal';
	shutDown();
}

 
function queryMsgs() {
	
	// queryStatus polls the server to retrieve any messages, and displays them 
	// in the busyLog element
	
	var xmlString = "<data><request-type>query-status</request-type></data>"
	xml_http_post('../www/main.html', xmlString, displayMsgs);
		
}

function displayMsgs(req) {
	
	// displayMsgs receives the response from the webserver. If the 'state' value
	// is OK, then a further timeout interval is set to repeat the request to update
	// the busyBox. Any other state value will not set a timeout, so the queries
	// back to the web server stop.
	
	var xmlDoc = req.responseXML;
	
	var state = xmlDoc.getElementsByTagName("status-text")[0].childNodes[0].nodeValue;
	
	if ( state == 'OK' ) {			// OK or NOTOK passed back
		
		// extract the messages from the response
		var msgs = xmlDoc.getElementsByTagName('message');
		
		if (msgs.length > 0) {
		
			// add the message to the msgLog array
			for (var i=0; i<msgs.length; i++) {
				msgLog.push(msgs[i].childNodes[0].nodeValue);
			}
			
			// Build the log messages string for the busyLog element
			var logString = "";
			for (var i=(msgLog.length-1); i>=0; i--) {
				logString += msgLog[i] + "<br>";
			}
			
			document.getElementById('busyLog').innerHTML = logString;
	

		}			
		// establish next poll for messages
		setTimeout(queryMsgs,pollingInterval);
	}
		
}

function enableMsgLog() {
	document.getElementById('busyLog').className = "show";	
	queryMsgs();
}

function showModal(state) {
	// function to just toggle the display of the modal window

	var state = state || 'off';

	if ( state == 'on') {
		// make it visible
		document.getElementById('modal-window').className = 'md-modal md-show';
	}
	else {
		// turn of modal window
		document.getElementById('modal-window').className = 'md-modal';
	}
	
}

function showError() {
	// Just slide the error page into view and initiate the shutdown
	slide('error');
	shutDown();
}
	
function populateDiv(xmlDoc) {
	// This function receives a xmldocument, extracting the next div name
	// and contents enabling the webpage to be updated dynamically
	
	var nextDiv = xmlDoc.getElementsByTagName('next-div')[0].getAttribute('div-name');
	var divContents = xmlDoc.getElementsByTagName("div-contents")[0].childNodes[0].nodeValue
				
	document.getElementById(nextDiv).innerHTML = divContents;

	
}
