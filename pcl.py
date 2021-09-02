#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# python standard library
import re, os, json, random

# local pret classes
from printer import printer
from helper import log, output, conv, item, const as c	

class pcl(printer):
  # --------------------------------------------------------------------
  # send PCL command to printer, optionally receive response
  def cmd(self, bytes_send, fb=True):
    bytes_recv = b"" # response buffer
    token = bytes(random.randrange(2**8, 2**15) * -1) # -256..-32767
    footer = c.ESC + b'*s' + token + b'X' # echo delimiter
    # send command to printer device
    try:
      cmd_send = c.UEL + c.PCL_HEADER + bytes_send + footer + c.UEL
      # write to logfile
      log().write(self.logfile, c.ESC + bytes_send + os.linesep)
      # sent to printer
      self.send(cmd_send)
      # use random token as delimiter for PCL responses
      bytes_recv = self.recv(b'ECHO ' + token + b'.*$', fb)
      # crop all PCL lines from received buffer
      bytes_recv = re.sub(rb"\x0d?\x0a?\x0c?PCL.*\x0a?", b'', bytes_recv)
      return bytes_recv

    # handle CTRL+C and exceptions
    except (KeyboardInterrupt, Exception) as e:
      self.reconnect(str(e))
      return b""

  # --------------------------------------------------------------------
  # remove functions not implemented in pcl
  def __init__(self, args):
    del printer.do_rmdir, printer.do_chvol, printer.do_pwd,
    del printer.do_touch, printer.do_append, printer.do_cd,
    del printer.do_traversal, printer.help_fuzz, printer.do_fuzz
    return super(pcl, self).__init__(args)

  # ====================================================================

  '''
  ┌───────────────────────────────────────────────────────────────┐
  │     `pclfs' specs // mosty implemented for the hack value     │
  ├────────────┬──────────────┬───────────────────────────────────┤
  │ macro ids  │        31337 │ superblock (serialized metadata)  │
  │            │ 10000..19999 │ file content (binary or ascii)    │
  ├────────────┼──────────────┼───────────────────────────────────┤
  │ echo codes │       0..255 │ ascii encoding for file transfers │
  │            │ -256..-32767 │ protocol delimiters for pcl jobs  │
  ├────────────┴──────────────┴───────────────────────────────────┤
  │ `superblock' format: JSON containing id, size and timestamp   │
  └───────────────────────────────────────────────────────────────┘
  '''

  # check if remote file exists
  def file_exists(self, path):
    pclfs = self.dirlist()
    for name, (id, size, date) in list(pclfs.items()):
      if path == name: return int(size)
    return c.NONEXISTENT

  #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
  # auto-complete dirlist for remote fs
  options_rfiles = {}
  def complete_rfiles(self, text, line, begidx, endidx):
    return [cat for cat in self.options_rfiles if cat.startswith(text)]

  # define alias
  complete_delete = complete_rfiles # file_or_dir
  complete_rm     = complete_rfiles # file_or_dir
  complete_get    = complete_rfiles # file_or_dir
  complete_cat    = complete_rfiles # file_or_dir
  complete_edit   = complete_rfiles # file_or_dir
  complete_vim    = complete_rfiles # file_or_dir

  # get list of macro ids on printer device
  def idlist(self):
    list = []
    bytes_send = b'*s4T'          # set location type (downloaded)
    bytes_send += c.ESC + b'*s0U' # set location unit (all units)
    bytes_send += c.ESC + b'*s1I' # set inquire entity (macros)
    bytes_recv = self.cmd(bytes_send)
    idlist = re.findall(b'IDLIST="(.*),?"', bytes_recv) ### maybe this can
    for id in item(idlist).split(","):               ### be packed into
      if id.startswith('1'): list.append(int(id))    ### a single regex
    return list

  # get list of files on virtual file system
  def dirlist(self, pclfs={}):
    superblock = self.retrieve_data(c.SUPERBLOCK)
    if superblock: # de-serialize pclfs dictionary
      try: pclfs = json.loads(superblock)
      except: pass # non-existent or invalid superblock
    if not pclfs:
      # handle getting False for pclfs
      pclfs = {}
    self.options_rfiles = pclfs
    return pclfs

  # ------------------------[ ls ]--------------------------------------
  def do_ls(self, arg: str):
    "List contents of virtual file system:  ls"
    pclfs = self.dirlist()
    if not pclfs: # no files have yet been uploaded
      output().raw("This is a virtual pclfs. Use 'put' to upload files.")
    # list files with syntax highlighting
    for name, (id, size, date) in sorted(pclfs.items()):
      output().pcldir(size, conv().lsdate(int(date)), id, name)

  # ====================================================================

  # ------------------------[ delete <file> ]---------------------------
  def delete(self, arg):
    pclfs = self.dirlist()
    if arg in pclfs:
      id = pclfs[arg][0]
      # remove pclfs entry
      del pclfs[arg]
      self.update_superblock(pclfs)
      # remove macro itself
      self.delete_macro(id)
    else:
      print("File not found.")

  # ------------------------[ get <file> ]------------------------------
  def get(self, path, size=None):
    pclfs = self.dirlist()
    for name, (id, size, date) in list(pclfs.items()):
      if path == name:
        bytes_recv = self.retrieve_data(id)
        return (int(size), bytes_recv)
    print("File not found.")
    return c.NONEXISTENT

  def retrieve_data(self, id: bytes):
    bytes_send = b'&f' + id + b'Y'  # set macro id
    bytes_send += c.ESC + b'&f2X'  # execute macro
    return self.echo2data(self.cmd(bytes_send))

  # ------------------------[ put <local file> ]------------------------
  def put(self, path, data):
    path = self.basename(path)
    pclfs = self.dirlist()
    # re-use macro id if file name already present
    if path in pclfs: id = pclfs[path][0]
    # find free macro id not already reserved for file
    else: id = str(item(set(c.BLOCKRANGE).difference(self.idlist())))
    # abort if we have used up the whole macro id space
    if not id: return output().warning("Out of macro slots.")
    self.chitchat("Using macro id #" + id)
    # retrieve and update superblock
    size = str(len(data))
    date = str(conv().now())
    pclfs[path] = [id, size, date]
    self.update_superblock(pclfs)
    # save data as pcl macro on printer
    self.define_macro(id.encode(), data)

  # ====================================================================

  # define macro on printer device
  def define_macro(self, id: bytes, data):
    bytes_send = b'&f' + id + b'Y'        # set macro id
    bytes_send += c.ESC + b'&f0X'        # start macro
    bytes_send += self.data2echo(data)  # echo commands
    bytes_send += c.ESC + b'&f1X'        # end macro
    bytes_send += c.ESC + b'&f10X'       # make permanent
    self.cmd(bytes_send, False)

  # delete macro from printer device
  def delete_macro(self, id: bytes):
    bytes_send = b'&f' + id + b'Y'        # set macro id
    bytes_send += c.ESC + b'&f8X'        # delete macro
    self.cmd(bytes_send, False)

  # update information on virtual file system
  def update_superblock(self, pclfs):
    # serialize pclfs dictionary
    pclfs = json.dumps(pclfs)
    self.define_macro(c.SUPERBLOCK, pclfs)

  # convert binary data to pcl echo commands
  def data2echo(self, data: bytes):
    echo = b''
    for n in data:
      echo += c.ESC + b'*s' + bytes(ord(bytes(n))) + b'X'
    return echo

  # convert pcl echo commands to binary data
  def echo2data(self, echo) -> bytes:
    data = b''
    echo = re.findall(rb"ECHO (\d+)", echo)
    for n in echo:
      data += conv().chr(bytes(n).decode()).encode()
    return data

  # ====================================================================

  # ------------------------[ info <category> ]-------------------------
  def do_info(self, arg: str):
    if arg in self.entities:
      entity, desc = self.entities[arg]
      for location in self.locations:
        output().raw(desc + " " + self.locations[location])
        bytes_send = b'*s' + location.encode() + b'T'         # set location type
        bytes_send += c.ESC + b'*s0U'               # set location unit
        bytes_send += c.ESC + b'*s' + entity.encode() + b'I'  # set inquire entity
        output().info(self.cmd(bytes_send))
    else:
      self.help_info()

  def help_info(self):
    print("Show information:  info <category>")
    print("  info fonts      - Show installed fonts.")
    print("  info macros     - Show installed macros.")
    print("  info patterns   - Show user-defined patterns.")
    print("  info symbols    - Show symbol sets.")
    print("  info extended   - Show extended fonts.")

  def complete_info(self, text, line, begidx, endidx):
    return [cat for cat in self.entities if cat.startswith(text)]

  entities = {
    'fonts':    ['0', 'Fonts'],
    'macros':   ['1', 'Macros'],
    'patterns': ['2', 'User-defined Patterns'],
    'symbols':  ['3', 'Symbol Sets'],
    'extended': ['4', 'Fonts Extended']
  }
  locations = {
  # '1': '(Selected)',
  # '2': '(All Locations)',
    '3': '(Internal)',
    '4': '(Downloaded)',
    '5': '(Cartridge)',
    '7': '(ROM/SIMMs)'
  }

  # ------------------------[ df ]--------------------------------------
  def do_free(self, arg: str):
    "Show available memory."
    output().info(self.cmd('*s1M'))

  # ------------------------[ selftest ]--------------------------------
  def do_selftest(self, arg: str):
    "Perform printer self-test."
    output().info(self.cmd('z'))
