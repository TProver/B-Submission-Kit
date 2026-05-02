Table of contentS
1	Integrating an external tool	6
1.1	A simple examples	7
1.2	A more complex example	8
2	List of recognised tags	9
2.1	externalTool	10
2.2	toolParameter	10
2.3	temporaryFile	11
2.4	command	12
2.5	param	12
2.6	List of predefined variables	12
3	REFERENCES	13
3.1	Glossary	14
3.2	Bibliography	14
01.

# Integrating an external tool


Integrating an external tool is done by writing a configuration file, also named an etool file. The configuration file is in XML format and has the name extension ".etool". This file describes the type of tool, as well as the command that will be started. This file should be located in the "extensions" subdirectory of the Atelier B installation, and is loaded when the Atelier B GUI start. 
For each etool file, a corresponding menu entry is created within the "Project" or "Component" menu of the GUI. When the menu is clicked, the tool is launched, and the corresponding task appears in the "Tasks" window of Atelier B. Double-clicking on the task displays a window showing the output of the tool.


## A simple example

Here is a simple example of a configuration file for an external tool for windows that open the project database file (bdp) in an explorer window:
<externalTool name="openbdp"
	category="project"
	label="Open bdp"
	shortcut="Ctrl+Y"
	tooltip="Opens the project database directory in an explorer window"
        icon="openbdp.png"
	>
	<command>c:\windows\explorer.exe</command>
	<param>${projectBdp}</param>
</externalTool>
The file starts with the externalTool tag, which contains the following information as attributes: 
name: the internal name of the tool (mandatory).
category: the category of the tool. Can be "component" or "project" (mandatory).
label: the text that is displayed in the corresponding menu entry (mandatory).
shortcut: a keyboard shortcut for calling the tool (optional)
tooltip: information that is displayed about the tool 
icon: the icon that will be used in the corresponding menu entry. This must be the name of a .png file located in the same directory as the configuration file. 
Within the external tool, the following tags describe the command: 
command: the path to the executable file that will be started (here c:\windows\explorer.exe) 
param: describes one parameter of the command. Here the command takes only one parameter, but for more complex commands with multiple parameters, there should be as many <param> as parameters. 
The variable elements of the command (here the path to the bdp directory) are expressed using the ${variableName} notation. Here ${projectBdp} is replaced by the path to the bdp directory of the project (see § 2.6 - Predefined variables). 

## A more complex example

The previous example had one major shortcoming: the path to the "explorer" executable is hardcoded. A better solution would be to allow the user to configure the path to the "explorer" executable. This can be done by using the toolParameter tag, that defines a new variable for using within the command. In that case, the corresponding etool configuration file would be the following: 
<externalTool name="openbdp"
	category="project"
	label="Open bdp"
	shortcut="Ctrl+Y"
	tooltip="Opens the project database directory in an explorer window"
        icon="openbdp.png" >
        <toolParameter name="explorer" type="exefile" default="c:\windows\explorer.exe" />
	<command>${explorer}</command>
	<param>${projectBdp}</param>
</externalTool>
Here, the toolParameter tag define a new variable that can be set by the user: a new tab is created in the "Preferences" dialog, that allows setting the path to the "explorer" executable (linux users could also provide a more suitable file manager). 
02.

# List of recognised tags


Here is the list of recognised tags as well as their allowed attributes. 
externalTool: The enclosing tag of the etool file. Defines an external tool.
toolParameter: Defines parameters for running the command.
temporaryFile: Create temporary files before running the command.
command: The command that should be run.
param: a parameter to the command.
The attributes for these tags are listed in the next sections. 

## externalTool

The externalTool tag is the main tag of the etool file. It is mandatory, and can contain the following attributes: 
name: the internal name of the tool (mandatory) 
category: the category of the tool. Can be "component" or "project" (mandatory) 
label: the text that is displayed in the corresponding menu entry (mandatory) 
shortcut: an optional keyboard shortcut for calling the tool 
tooltip: information that is displayed about the tool 
icon: the icon that will be used in the corresponding menu entry. This must be the name of a .png file located in the same directory as the etool file. 

## toolParameter

The toolParameter tag defines a variable that will be expanded when running the tool. The allowed attributes are the following: 
name: the name of the parameter. The name correspond to the name of the variable (mandatory)
type: the type of the parameter. Can be one of "ressource", "exefile", "file" and "tool" (mandatory)
default: a default value for the parameter if no other value is available.
optional: can be "yes" or "no" to indicate that the parameter is optional. If the parameter is not optional, the tool will not be executed in the case no value is found for the parameter.
description: a textual description of the parameter. This field is used when creating a preference page for configuring the tool.
Depending on the type of the tool, the textual content of the tag can be required or not, and can have different meanings. The requirement depends on the type of the attribute: 
ressource: in that case the text field correspond to an Atelier B resource, and the variable will be expanded into the value of the resource. For instance: 
<toolParameter name="refinerFile" type="ressource">ATB*BART*RefinerFile</toolParameter>
exefile: in that case, the text field is not used. The variable will be expanded to the path of a file configured by the user in the "Preferences" dialog. 
<toolParameter name="editor" type="exefile" description="The editor" default="/usr/bin/xemacs" />
file: the text field is not used, and the variable will be expanded to the path of a file configured by the user in the "Preferences" dialog. 
<toolParameter name="myFile" type="file" description="tool configuration file" />
tool: This type corresponds to a tool, either provided by Atelier B, either provided by the extension. The text field is optional, and correspond to an Atelier B resource. The variable is expanded into the full path to the corresponding tool. The tool can be an executable or a logic-solver file (*.kin). Example: 
<toolParameter name="krt" type="tool" description="Logic Solver" default="krt">ATB*ATB*Logic_Solver_Command</toolParameter>
The tool is searched as follows: first, the content of the provided resource (if any) is looked up. If it is empty or if no resource is provided, the default value is taken. Then, the corresponding file is searched in the following directories 
The OS-dependent directory of Atelier B (bbin/win32 on windows, bbin/linux on linux, etc...) 
The external tool directory. If the tool is named "mytool", this directory will be extensions/mytool 
The OS dependent subdirectories of the external tool: extensions/mytool/win32 on windows, extensions/mytool/linux on linux, etc... 

## temporaryFile

The temporaryFile tag is used to write a temporary file before running the command. This can be used in the case where the command takes an input file. The textual content of the temporaryFile tag correspond to a template file, where all the variables are replaced by their values. There can be as many temporaryFile tags as needed in the etool file. 
The following attributes are recognised: 

## command

The command tag specifies the executable that should be started. One and only one command tag should be present in the etool file. 
List of attributes: 

## param

The param tag specifies one and only one argument to the <command> tag. There should be as many param tag as there are arguments to the command. This is required to correctly handle spaces in directories. 
The current list of recognised attributes is not documented yet, as it is very likely to change. 

## Predefined variables

The following table lists all the predefined variables and their value: 

07.

# REFERENCES



## Glossary


• Component: text-based model that could either be a specification (B abstract machine), a refinement or an implementation.



## Bibliography


• The B-Book: Assigning programs to meanings, J.R. Abrial, Cambridge University Press (1996)
• Modeling in Event-B: system and software engineering, J.R. Abrial, Cambridge University Press (2010)
• The B-Method: an introduction, S. Schneider, Palgrave Macmillan (2001)
• Program Development by Refinement: case-studies using the B-Method, E. Sekerinski & K. Sere, Springer (1999)
• Spécification formelle avec B, H. Habrias, Lavoisier (2001)


 









[TABLE]
Attribute |  | Description
name | mandatory | the name of the variable that will hold the path to the created temporary file
directory | optional | the directory where the temporary file should be created. If no directory is specified, the system temporary directory will be used. Variables can be used to express this directory.
template | optional | A template for the name of the file. If provided, the name of the temporary file will be based on template
[/TABLE]



[TABLE]
Attribute |  | Description
workingDirectory | optional | The working directory of the started tool. Variables can be used to specify this directory
[/TABLE]



[TABLE]
Variable | Tool type | Description
${projectName} | All | The name of the currently selected project, or the project to which the selected component belongs
${projectBdp} | All | The absolute path to the "bdp" directory of the project
${extensionsDir} | All | The path to the extension directory
${componentName} | Component | The name of the selected component
${componentPath} | Component | The absolute path to the selected component file
${componentDir} | Component | The absolute path to the directory where the component is located
[/TABLE]
