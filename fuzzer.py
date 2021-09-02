#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import List, Tuple, Union


class fuzzer():
  vol: List[bytes]  = [b"", b".", b"\\", b"/", b"file:///", b"C:/"]
  var: List[bytes]  = [b"~", b"$HOME"]
  win: List[bytes]  = [b"%WINDIR%", b"%SYSTEMROOT%", b"%HOMEPATH%", b"%PROGRAMFILES%"]
  smb: List[bytes]  = [b"\\\\127.0.0.1\\"]
  web: List[bytes]  = [b"http://127.0.0.1/"] # "http://hacking-printers.net/log.me"
  dir: List[bytes]  = [b"..", b"...", b"...."] # also combinations like "./.."
  fhs: List[bytes] = [b"/etc", b"/bin", b"/sbin", b"/home", b"/proc", b"/dev", b"/lib",
         b"/opt", b"/run", b"/sys", b"/tmp", b"/usr", b"/var", b"/mnt",]
  abs: List[Union[bytes, List[bytes]]] = [b".profile", [b"etc", b"passwd"], [b"bin", b"sh"], [b"bin", b"ls"],
         b"boot.ini", [b"windows", b"win.ini"], [b"windows", b"cmd.exe"]]
  rel: List[bytes]  = [b"%WINDIR%\\win.ini",
         b"%WINDIR%\\repair\\sam",
         b"%WINDIR%\\repair\\system",
         b"%WINDIR%\\system32\\config\\system.sav",
         b"%WINDIR%\\System32\\drivers\\etc\\hosts",
         b"%SYSTEMDRIVE%\\boot.ini",
         b"%USERPROFILE%\\ntuser.dat",
         b"%SYSTEMDRIVE%\\pagefile.sys",
         b"%SYSTEMROOT%\\repair\\sam",
         b"%SYSTEMROOT%\\repair\\system"]

  # define prefixes to use in fuzzing modes
  path: List[bytes]   = vol+var+win+smb+web # path fuzzing
  write: List[bytes]  = vol+var+win+smb+fhs # write fuzzing
  blind: List[bytes]  = vol+var             # blind fuzzing
