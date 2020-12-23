#!/usr/bin/env python

import asyncio

# Import 'packets' folder
import os, sys, inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
if parentdir not in sys.path: sys.path.insert(0, parentdir)
from packets.packets import *

class TechmanException(Exception):
   pass

class TechmanClient:

   def __init__(self, suppress_warn=False, conn_timeout=None, *, robot_ip, robot_port):
      self._conn_timeout = 3 if conn_timeout is None else conn_timeout
      self._suppress_warn = suppress_warn
      self._robot_ip = robot_ip
      self._robot_port = robot_port
      self._conn_exception = None
      self._loop = asyncio.get_event_loop()
      if not self._connect():
         if not self._suppress_warn: print('[TechmanClient] WARN: Could not connect to robot during initialisation.')

   def _connect(self): return self._loop.run_until_complete(self._connect_async())
   async def _connect_async(self):
      connect_fut = asyncio.open_connection(self._robot_ip, self._robot_port)
      try: 
         self._reader, self._writer = await asyncio.wait_for(connect_fut, timeout=self._conn_timeout)
      except Exception as e:
         self._conn_exception = e
         return False
      self._conn_exception = None
      return True

   @property
   def is_connected(self): return self._conn_exception is None
