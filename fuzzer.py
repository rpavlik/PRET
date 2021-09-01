#!/usr/bin/env python3
# -*- coding: utf-8 -*-

class fuzzer():
  vol = [b"", b".", b"\\", b"/", b"file:///", b"C:/"]
  var = [b"~", b"$HOME"]
  win = [b"%WINDIR%", b"%SYSTEMROOT%", b"%HOMEPATH%", b"%PROGRAMFILES%"]
  smb = [b"\\\\127.0.0.1\\"]
  web = [b"http://127.0.0.1/"] # "http://hacking-printers.net/log.me"
  dir = [b"..", b"...", b"...."] # also combinations like "./.."
# sep = [b"", b"\\", b"/", b"\\\\", b"//", b"\\/"]
  fhs = [b"/etc", b"/bin", b"/sbin", b"/home", b"/proc", b"/dev", b"/lib",
         "/opt", b"/run",  "/sys", b"/tmp", b"/usr", b"/var", b"/mnt",]
  abs = [b".profile", [b"etc", b"passwd"], [b"bin", b"sh"], [b"bin", b"ls"],
         "boot.ini", [b"windows", b"win.ini"], [b"windows", b"cmd.exe"]]
  rel = [b"%WINDIR%\\win.ini",
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
  path  = vol+var+win+smb+web # path fuzzing
  write = vol+var+win+smb+fhs # write fuzzing
  blind = vol+var             # blind fuzzing
