#!/usr/bin/env python3
# MIT License
#
# Copyright (c) 2020 - 2022 Carlos Gil Gonzalez
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
from pynats import NATSClient
import ast
import time
import multiprocessing
from array import array
from binascii import hexlify
from .exceptions import DeviceException
from .decorators import getsource
import functools
import re
import threading


class BASE_NATS_DEVICE:
    def __init__(self, servers: str = "nats://192.168.1.111:4222"):
        # self.bytes_sent = 0
        self.buff = b''
        self._kbi = '\x03'
        self._banner = '\x02'
        self._reset = '\x04'
        self._hreset = 'import machine; machine.reset()\r'
        self.response = ''
        self._traceback = b'Traceback (most recent call last):'
        self.output = None
        self.wr_cmd = self.cmd
        self.prompt = b'>>> '
        self.nc = NATSClient(servers)
        self.nc.connect()
        self.nc.subscribe(subject="mpy.repl.output", callback=self.datacallback)
        self.nc.subscribe(subject="mpy.repl.callback", callback=self.datacallback)
        self.msg = []
        self.state = True
        self.thread = threading.Thread(target=self.waitdata)
        self.thread.start()
        self.lock = threading.Lock()

    def waitdata(self):
        while self.state:
            self.nc.wait(count=1)
            try:
                self.lock.release()
            except Exception:
                pass

    
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()

    def __del__(self):
        self.state = False
        self.write(self._kbi)
        self.thread.join()
  
    def datacallback(self, msg):
        if msg.subject == 'mpy.repl.output':
            self.msg.append(msg.payload)
        elif msg.subject == 'mpy.repl.callback':
            self.callback(msg.payload)

    def callback(self, msg):
        pass

    def read(self):
        if len(self.msg) == 0:
            self.lock.acquire()
        if len(self.msg):
            return self.msg.pop(0)
        else:
            return b''

    def write(self, data: bytes = b''):
        self.nc.publish(subject="mpy.repl.input", payload=data)

    def read_all(self):
        try:
            self.raw_buff = b''
            while self.prompt not in self.raw_buff:
                try:
                    data = self.read()
                    self.raw_buff += data
                except AttributeError:
                    pass

            return self.raw_buff
        except TimeoutError:
            return self.raw_buff

    def cmd(self, cmd, silent=False, rtn=True, long_string=False, rtn_resp=False):
        self.response = ''
        self.output = None
        self.buff = b''
        self.msg = []
        self.write(bytes(cmd+'\r', 'utf-8'))
        # time.sleep(0.2)
        # self.buff = self.serial.read_all()[self.bytes_sent+1:]
        if self.buff == b'':
            # time.sleep(0.2)
            self.buff = self.read_all()
        cmd_filt = bytes(cmd + '\r\n', 'utf-8')
        self.buff = self.buff.replace(cmd_filt, b'', 1)
        if self._traceback in self.buff:
            long_string = True
        if long_string:
            self.response = self.buff.replace(b'\r', b'').replace(
                b'\r\n>>> ', b'').replace(b'>>> ', b'').decode()
        else:
            self.response = self.buff.replace(b'\r\n', b'').replace(
                b'\r\n>>> ', b'').replace(b'>>> ', b'').decode()
        if not silent:
            if self.response != '\n' and self.response != '':
                print(self.response)
            else:
                self.response = ''
        if rtn:
            self.get_output()
            if self.output == '\n' and self.output == '':
                self.output = None
            if self.output is None:
                if self.response != '' and self.response != '\n':
                    self.output = self.response
        if rtn_resp:
            return self.output

    def reset(self, silent=False, reconnect=True, hr=False):
        self.buff = b''
        if not silent:
            print('Rebooting device...')
        if not hr:
            self.write(bytes(self._reset, 'utf-8'))
        else:
            try:
                self.write(bytes(self._hreset, 'utf-8'))
            except OSError:
                pass
        time.sleep(0.5)
        try:
            self.buff = self.read_all()
        except OSError:
            pass
        if not silent:
            print('Done!')

    def kbi(self, silent=True, pipe=None, long_string=False):
        if pipe is not None:
            self.wr_cmd(self._kbi, silent=silent)
            pipe(self.response, std='stderr')
        else:
            self.cmd(self._kbi, silent=silent, long_string=long_string)

    def banner(self, pipe=None):
        self.cmd(self._banner, silent=True, long_string=True)
        if pipe is None:
            print(self.response.replace('\n\n', '\n'))
        else:
            pipe(self.response.replace('\n\n', '\n'))

    def get_output(self):
        try:
            self.output = ast.literal_eval(self.response)
        except Exception as e:
            if 'bytearray' in self.response:
                try:
                    self.output = bytearray(ast.literal_eval(
                        self.response.strip().split('bytearray')[1]))
                except Exception as e:
                    pass
            else:
                if 'array' in self.response:
                    try:
                        arr = ast.literal_eval(
                            self.response.strip().split('array')[1])
                        self.output = array(arr[0], arr[1])
                    except Exception as e:
                        pass
            pass


class NATS_DEVICE(BASE_NATS_DEVICE):
    def __init__(self, servers: str = "127.0.0.1", name=None, dev_platf=None,
                 autodetect=False, init=True):
        super().__init__(servers)
        self.dev_class = 'SerialDevice'
        self.dev_platform = dev_platf
        self.name = name
        self.raw_buff = b''
        self.message = b''
        self.data_buff = ''
        self.datalog = []
        self.output_queue = multiprocessing.Queue(maxsize=1)
        self.paste_cmd = ''
        self.connected = True
        self.repl_CONN = self.connected
        self._is_traceback = False
        self._is_first_line = True
        self._machine = None
        self.stream_kw = ['print', 'ls', 'cat', 'help', 'from', 'import',
                          'tree', 'du']
        if name is None and self.dev_platform:
            self.name = '{}_{}'.format(
                self.dev_platform, servers)
        if autodetect:
            self.cmd('\r', silent=True)
            self.cmd("import gc;import sys; sys.platform", silent=True)
            self.dev_platform = self.output
            if not self.name:
                self.name = '{}_{}'.format(
                    self.dev_platform, servers)
        if init:
            self.cmd(self._kbi+'\r', silent=True)

    def __repr__(self):
        # repr_cmd = "import sys;import os; from machine import unique_id; \
        # [os.uname().sysname, os.uname().release, os.uname().version, \
        # os.uname().machine, unique_id(), sys.implementation.name]"
        # (self.dev_platform, self._release,
        #  self._version, self._machine, uuid, imp) = self.cmd(repr_cmd,
        #                                                      silent=True,
        #                                                      rtn_resp=True)
        # vals = hexlify(uuid).decode()
        # imp = imp[0].upper() + imp[1:]
        # imp = imp.replace('p', 'P')
        # self._mac = ':'.join([vals[i:i+2] for i in range(0, len(vals), 2)])
        # fw_str = '{} {}; {}'.format(imp, self._version, self._machine)
        # dev_str = '(MAC: {})'.format(self._mac)
        # desc_str = '{}, Manufacturer: {}'.format(self.dev_description,
        #                                          self.manufacturer)
        return (f'Servers @ {self.nc}')
                # , Type: {self.dev_platform}, '
                # f'Class: {self.dev_class}\n'
                # f'Firmware: {fw_str}\n{dev_str}')

    def flush_conn(self):
        flushed = 0
        while flushed < 2:
            try:
                self.read(0.01)
                flushed += 1
                self.buff = b''
            except Exception as e:
                flushed += 1

    def _kbi_cmd(self):
        self.write(bytes(self._kbi+'\r', 'utf-8'))

    def read_until(self, exp=None, exp_p=True, rtn=False):
        self.raw_buff = b''
        while exp not in self.raw_buff:
            self.raw_buff += self.read()
            if exp_p:
                if self.prompt in self.raw_buff:
                    break
        if rtn:
            return self.raw_buff
            # print(self.raw_buff)

    def cmd(self, cmd, silent=False, rtn=True, long_string=False,
            rtn_resp=False, follow=False, pipe=None, multiline=False,
            dlog=False, nb_queue=None):
        self._is_traceback = False
        self.response = ''
        self.output = None
        self.flush_conn()
        self.buff = b''
        self.msg = []
        self.write(bytes(cmd+'\r', 'utf-8'))
        # time.sleep(0.2)
        # self.buff = self.serial.read_all()[self.bytes_sent+1:]
        if self.buff == b'':
            if not follow:
                # time.sleep(0.2)
                # self.read_until(b'\n')
                self.buff = self.read_all()
                if self.buff == b'' or self.prompt not in self.buff:
                    # time.sleep(0.2)
                    self.buff += self.read_all()
                    while self.prompt not in self.buff:
                        self.buff += self.read_all()
            else:
                silent_pipe = silent
                silent = True
                rtn = False
                rtn_resp = False
                try:
                    self.follow_output(cmd, pipe=pipe, multiline=multiline,
                                       silent=silent_pipe)
                except KeyboardInterrupt:
                    # time.sleep(0.2)
                    self.paste_cmd = ''
                    if pipe is None:
                        print('')  # print Traceback under ^C
                        self.kbi(pipe=pipe, silent=False,
                                 long_string=long_string)  # KBI
                    else:
                        self.kbi(pipe=pipe)  # KBI
                    # time.sleep(0.2)
                    for i in range(1):
                        self.write(b'\r')
                        self.flush_conn()
        cmd_filt = bytes(cmd + '\r\n', 'utf-8')
        self.buff = self.buff.replace(cmd_filt, b'', 1)
        if dlog:
            self.data_buff = self.buff.replace(b'\r', b'').replace(
                b'\r\n>>> ', b'').replace(b'>>> ', b'').decode()
        if self._traceback in self.buff:
            long_string = True
        
        if long_string:
            self.response = self.buff.replace(b'\r', b'').replace(
                b'\r\n>>> ', b'').replace(b'>>> ', b'').decode()
        else:
            self.response = self.buff.replace(b'\r\n', b'').replace(
                b'\r\n>>> ', b'').replace(b'>>> ', b'').decode()
        if not silent:
            if self.response != '\n' and self.response != '':
                if pipe is None:
                    try:
                        if self._traceback.decode() in self.response:
                            raise DeviceException(self.response)
                        else:
                            print(self.response)
                    except Exception as e:
                        print(e)
                        self.response = ''
            else:
                self.response = ''
        if rtn:
            self.get_output()
            if self.output == '\n' and self.output == '':
                self.output = None
            if self.output is None:
                if self.response != '' and self.response != '\n':
                    self.output = self.response
            if nb_queue is not None:
                if nb_queue.empty():
                    nb_queue.put(self.output, block=False)
                else:
                    nb_queue.get_nowait()
                    nb_queue.put(self.output, block=False)
        if rtn_resp:
            return self.output

    def follow_output(self, inp, pipe=None, multiline=False, silent=False):
        self.raw_buff = b''
        # self.raw_buff += self.serial.read(len(inp)+2)
        # if not pipe:
        self.read_until(exp=b'\n')
        # self.read_until(exp=bytes(inp, 'utf-8')+b'\r\n')
        # self.read_until(exp=bytes(inp, 'utf-8'))
        if pipe is not None:
            self._is_first_line = True
            if any(_kw in inp for _kw in self.stream_kw):
                self._is_first_line = False
            if self.paste_cmd != '':
                if self.dev_platform != 'pyboard' and self.dev_platform != 'rp2':
                    while self.paste_cmd.split('\n')[-1] not in self.raw_buff.decode():
                        self.read_until(exp=b'\n')

                    self.read_until(exp=b'\n')
        while True:
            if pipe is not None and not multiline:
                self.message = b''
                while b'\n' not in self.message:
                    self.message += self.read()
                    if self.prompt in self.message:
                        break
            else:
                self.message = b''
                while b'\r\n' not in self.message:
                    self.message += self.read()
                    if self.prompt in self.message:
                        break
            self.buff += self.message
            self.raw_buff += self.message
            if self.message == b'':
                pass
            else:
                if self.message.startswith(b'\n') and 'ls(' not in inp:
                    self.message = self.message[1:]
                if pipe:
                    cmd_filt = bytes(inp + '\r\n', 'utf-8')
                    self.message = self.message.replace(cmd_filt, b'', 1)
                msg = self.message.replace(b'\r', b'').decode('utf-8')
                if 'cat' in inp:
                    if msg.endswith('>>> '):
                        msg = msg.replace('>>> ', '')
                        if not msg.endswith('\n'):
                            msg = msg+'\n'
                if pipe is not None:
                    if msg == '>>> ':
                        pass
                    else:
                        pipe_out = msg.replace('>>> ', '')
                        if pipe_out != '':
                            if self.paste_cmd != '':
                                if self.buff.endswith(b'>>> '):
                                    # if pipe_out[-1] == '\n':
                                    pipe_out = pipe_out[:-1]
                                    if pipe_out != '' and pipe_out != '\n':
                                        if self._traceback.decode() in pipe_out:
                                            self._is_traceback = True
                                            # catch before traceback:
                                            pipe_stdout = pipe_out.split(
                                                self._traceback.decode())[0]
                                            if pipe_stdout != '' and pipe_stdout != '\n':
                                                pipe(pipe_stdout)
                                            pipe_out = self._traceback.decode(
                                            ) + pipe_out.split(self._traceback.decode())[1]
                                        if self._is_traceback:
                                            pipe(pipe_out, std='stderr')
                                        else:
                                            if self._is_first_line:
                                                self._is_first_line = False
                                                if not multiline:
                                                    pipe(pipe_out, execute_prompt=True)
                                                else:
                                                    pipe(pipe_out)
                                            else:
                                                pipe(pipe_out)
                                else:
                                    if self._traceback.decode() in pipe_out:
                                        self._is_traceback = True
                                        # catch before traceback:
                                        pipe_stdout = pipe_out.split(
                                            self._traceback.decode())[0]
                                        if pipe_stdout != '' and pipe_stdout != '\n':
                                            pipe(pipe_stdout)
                                        pipe_out = self._traceback.decode(
                                        ) + pipe_out.split(self._traceback.decode())[1]
                                    if self._is_traceback:
                                        pipe(pipe_out, std='stderr')
                                    else:
                                        if self._is_first_line:
                                            self._is_first_line = False
                                            if not multiline:
                                                pipe(pipe_out, execute_prompt=True)
                                            else:
                                                pipe(pipe_out)
                                        else:
                                            pipe(pipe_out)
                            else:
                                if self._traceback.decode() in pipe_out:
                                    self._is_traceback = True
                                    # catch before traceback:
                                    pipe_stdout = pipe_out.split(
                                        self._traceback.decode())[0]
                                    if pipe_stdout != '' and pipe_stdout != '\n':
                                        pipe(pipe_stdout)
                                    pipe_out = self._traceback.decode(
                                    ) + pipe_out.split(self._traceback.decode())[1]
                                if self._is_traceback:
                                    pipe(pipe_out, std='stderr')
                                else:
                                    if self._is_first_line:
                                        self._is_first_line = False
                                        if not multiline:
                                            pipe(pipe_out, execute_prompt=True)
                                        else:
                                            pipe(pipe_out)
                                    else:
                                        pipe(pipe_out)
                else:
                    if pipe is None:
                        if not silent:
                            print(msg.replace('>>> ', ''), end='')
            if self.buff.endswith(b'>>> '):
                break
        self.paste_cmd = ''

    # def disconnect(self):
    #     asyncio.run(self.sub.unsubscribe())
    #     asyncio.run(self.nc.drain())
    #     self.connected = False

    def paste_buff(self, long_command):
        self.paste_cmd = long_command
        self.write(b'\x05')
        lines = long_command.split('\n')
        for line in lines:
            time.sleep(0.01)
            self.write(bytes(line+'\n', 'utf-8'))
        self.flush_conn()

    def get_datalog(self, dvars=None, fs=None, time_out=None, units=None):
        self.datalog = []
        self.output = None
        for line in self.data_buff.splitlines():
            self.output = None
            self.response = line
            self.get_output()
            if self.output is not None and self.output != '':
                self.datalog.append(self.output)
        if dvars is not None and self.datalog != []:
            temp_dict = {var: [] for var in dvars}
            temp_dict['vars'] = dvars
            for data in self.datalog:
                if len(data) == len(dvars):
                    for i in range(len(data)):
                        temp_dict[dvars[i]].append(data[i])
            if time_out is not None:
                fs = int((1/time_out)*1000)
            if fs is not None:
                temp_dict['fs'] = fs
                temp_dict['ts'] = [i/temp_dict['fs']
                                   for i in range(len(temp_dict[dvars[0]]))]
            if units is not None:
                temp_dict['u'] = units
            self.datalog = temp_dict

    def cmd_nb(self, command, silent=False, rtn=True, long_string=False,
               rtn_resp=False, follow=False, pipe=None, multiline=False,
               dlog=False, block_dev=True):
        if block_dev:
            self.dev_process_raw = multiprocessing.Process(
                target=self.wr_cmd, args=(command, silent, rtn, long_string, rtn_resp,
                                          follow, pipe, multiline, dlog,
                                          self.output_queue))
            self.dev_process_raw.start()
        else:
            self.write(bytes(command+'\r', 'utf-8'))

    def get_opt(self):
        try:
            self.output = self.output_queue.get(block=False)
        except Exception:
            pass


class NatsDevice(NATS_DEVICE):
    def __init__(self, *args: object, **kargs: object) -> object:
        super().__init__(*args, **kargs)

    def code(self, func):
        # str_func = '\n'.join(getsource(func).split('\n')[1:])
        source_lines = getsource(func).split('\n')[1:]
        indent = len(source_lines[0]) - len(source_lines[0].lstrip())
        str_func = '\n'.join([line[indent:] for line in source_lines if line.strip()])
        self.paste_buff(str_func)
        self.cmd('\x04', silent=True)

        @functools.wraps(func)
        def wrapper_cmd(*args, **kwargs):
            flags = ['>', '<', 'object', 'at', '0x']
            args_repr = [repr(a) for a in args if any(
                f not in repr(a) for f in flags)]
            kwargs_repr = [f"{k}={v!r}" if not callable(
                v) else f"{k}={v.__name__}" for k, v in kwargs.items()]
            signature = ", ".join(args_repr + kwargs_repr)
            cmd_ = f"{func.__name__}({signature})"
            self.wr_cmd(cmd_, rtn=True)
            if self.output:
                return self.output
        return wrapper_cmd

    def code_follow(self, func):
        # str_func = '\n'.join(getsource(func).split('\n')[1:])
        source_lines = getsource(func).split('\n')[1:]
        indent = len(source_lines[0]) - len(source_lines[0].lstrip())
        str_func = '\n'.join([line[indent:] for line in source_lines if line.strip()])
        self.paste_buff(str_func)
        self.cmd('\x04', silent=True)

        @functools.wraps(func)
        def wrapper_cmd(*args, **kwargs):
            flags = ['>', '<', 'object', 'at', '0x']
            args_repr = [repr(a) for a in args if any(
                f not in repr(a) for f in flags)]
            kwargs_repr = [f"{k}={v!r}" if not callable(
                v) else f"{k}={v.__name__}" for k, v in kwargs.items()]
            signature = ", ".join(args_repr + kwargs_repr)
            cmd_ = f"{func.__name__}({signature})"
            self.wr_cmd(cmd_, rtn=True, follow=True)
            if self.output:
                return self.output
        return wrapper_cmd
    
    def remotefun(self, func):
        source_lines = getsource(func).split('\n')[1:]
        indent = len(source_lines[0]) - len(source_lines[0].lstrip())
        str_func = '\n'.join([line[indent:] for line in source_lines if line.strip()])
        self.paste_buff(str_func)
        self.cmd('\x04', silent=True)
        return CustomFunction(func)

    def load(self, file):
        with open(file, 'r') as upy_file:
            upy_content = upy_file.read()
        self.paste_buff(upy_content)
        self.wr_cmd('\x04', follow=True)

    def raise_traceback(self):
        if self._traceback.decode() in self.response:
            dev_traceback = re.search(r'\b(Traceback)\b', self.response)
            tr_index = dev_traceback.start()
            raise DeviceException(self.response[tr_index:])


class CustomFunction:
    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kwargs):
        self.func(*args, **kwargs)

    def __repr__(self):
        return self.func.__name__
