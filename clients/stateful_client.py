#!/usr/bin/env python

import asyncio
from asyncio.futures import CancelledError

from techman_client import TechmanClient, TechmanConnection

# Import 'packets' folder
import os, sys, inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
if parentdir not in sys.path: sys.path.insert(0, parentdir)
from packets.packets import *
from util.exceptions import * # pylint: disable=no-name-in-module

class StatefulClient(TechmanClient):

   def __init__(self, *, robot_ip, robot_port, client_id='SCpy', conn_timeout=3):
      super().__init__(robot_ip=robot_ip, robot_port=robot_port, conn_timeout=conn_timeout)
      self._client_id = client_id

   def _on_connection(self, reader, writer):
      return StatefulConnection(self._client_id, reader, writer, self._conn_timeout)

class StatefulConnection(TechmanConnection):

   def __init__(self, client_id, reader, writer, conn_timeout):
      super().__init__(reader, writer, conn_timeout)
      self._listen_task = None
      self._requests = []
      self._in_listen = False
      self._listen_is_awaited = False
      self._broadcast_callback = None
      self._client_id = client_id
      self._msg_cnt = 0

   def add_broadcast_callback(self, broadcast_callback):
      if not self._in_listen: self._start_listen()
      self._broadcast_callback = broadcast_callback

   async def keep_alive(self):
      self._listen_is_awaited = True
      await self._listen_task

   async def send(self, packet):
      # Send message
      req_fut = asyncio.Future()
      self._requests.append([packet, req_fut, 0])
      if not self._in_listen: self._start_listen()
      self._writer.write(packet.encoded())
      await self._writer.drain()
      # Wait until result
      return await req_fut

   def _obtain_handle_id(self):
      handle_id = f'{self._client_id}{self._msg_cnt}'
      self._msg_cnt += 1
      return handle_id

   def _handle_exception(self, exc):
      for request in self._requests: request[1].set_exception(exc)
      self._requests = []
      if self._listen_is_awaited: raise exc

   def _on_message(self, packet):
      # Check if this is a response to ongoing request
      handle_id = packet.handle_id
      index, req_fut = -1, None
      for i, request in enumerate(self._requests):
         if request[0].handle_id != handle_id: continue
         index, req_fut = i, request[1]      
      # Call request callback
      if index != -1:
         del self._requests[index]
         req_fut.set_result(packet)
      # Call broadcast callback
      elif self._broadcast_callback is not None: self._broadcast_callback(packet)

   def _start_listen(self):
      if self._in_listen: return
      self._in_listen = True
      def callback(res):
         # For debugging purposes
         try: res.result()
         except Exception as e: 
            if not self._listen_is_awaited: print(f'Exception caught: {e}')
      self._listen_task = asyncio.ensure_future(self._listen())
      self._listen_task.add_done_callback(callback)

   async def _listen(self):
      try:
         while True:
            read_bytes = await self._reader.read(100000)
            # Empty byte indicates lost connection
            if read_bytes == b'': raise TMConnectError(None, msg='Socket connection was closed by server')
            # Skip corrupt packet
            elif len(read_bytes) > 5 and (read_bytes[0] != 0x24 or read_bytes[-5] != 0x2A): continue
            # Valid respone
            res = StatefulPacket(read_bytes)
            if res._header == 'CPERR': raise TMProtocolError(CPERR_packet(res).description)
            self._on_message(res)
            # Refresh request if no answer within 5 packets
            for request in self._requests:               
               if request[2] > 5:
                  request[2] = 0
                  self._writer.write(request[0].encoded())
               else: request[2] += 1
            # Quit loop if we are done
            if self._broadcast_callback is None and len(self._requests) == 0: break
         self._in_listen = False
      except CancelledError as e: raise e # Delegate asyncio exception
      except TechmanException as e: self._handle_exception(e)
      except ConnectionError as e: self._handle_exception(TMConnectError(e))
      except Exception as e: self._handle_exception(TechmanException())
