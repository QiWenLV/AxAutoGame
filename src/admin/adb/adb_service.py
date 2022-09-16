from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, TYPE_CHECKING
import time
import struct
import socket
import os
import numpy as np
import contextlib
from src.admin.utils.sys_utils import find_adb_from_android_sdk
from src.admin.utils.socket_util import recvexactly, recvall

import logging

logger = logging.getLogger(__name__)

_last_check = 0


def _check_okay(sock):
    result = recvexactly(sock, 4)
    if result != b'OKAY':
        raise RuntimeError(_read_hexlen(sock))


def _read_hexlen(sock):
    textlen = int(recvexactly(sock, 4), 16)
    if textlen == 0:
        return b''
    buf = recvexactly(sock, textlen)
    return buf


def _read_binlen_le(sock):
    textlen = struct.unpack('<I', recvexactly(sock, 4))[0]
    if textlen == 0:
        return b''
    buf = recvexactly(sock, textlen)
    return buf


def check_adb_alive(server: ADBServer):
    global _last_check
    if time.monotonic() - _last_check < 0.1:
        return True
    try:
        sess = server._create_session_nocheck()
        version = int(sess.service('host:version').read_response().decode(), 16)
        logger.debug('ADB server version %d', version)
        _last_check = time.monotonic()
        return True
    except socket.timeout:
        return False
    except ConnectionRefusedError:
        return False
    except RuntimeError:
        return False


def ensure_adb_alive(server: ADBServer):
    if check_adb_alive(server):
        return
    if server.address[0] != '127.0.0.1' and server.address[0] != 'localhost':
        raise RuntimeError('ADB server is not running on localhost, please start it manually')
    start_adb_server(server)


def start_adb_server(server: ADBServer):
    logger.info('尝试启动 adb server')
    import subprocess
    import app
    adbbin = app.config.device.adb_binary
    if not adbbin:
        adb_binaries = ['adb']
        try:
            bundled_adb = app.get_vendor_path('platform-tools')
            adb_binaries.append(bundled_adb / 'adb')
        except FileNotFoundError:
            pass
        findadb = find_adb_from_android_sdk()
        if findadb is not None:
            adb_binaries.append(findadb)
    else:
        adb_binaries = [adbbin]
    port = server.address[1]
    for adbbin in adb_binaries:
        try:
            logger.debug('trying %r', adbbin)
            if port != 5037:
                env = {**os.environ, 'ANDROID_ADB_SERVER_PORT': str(port)}
            else:
                env = os.environ
            if os.name == 'nt' and app.background:
                si = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW, wShowWindow=subprocess.SW_HIDE)
                subprocess.run([adbbin, 'start-server'], env=env, check=True, startupinfo=si)
            else:
                subprocess.run([adbbin, 'start-server'], env=env, check=True)
            # wait for the newly started ADB server to probe emulators
            time.sleep(0.5)
            if check_adb_alive(server):
                logger.info('已启动 adb server')
                return
        except FileNotFoundError:
            pass
        except subprocess.CalledProcessError:
            pass
    raise OSError("can't start adb server")


class ADBServer:
    DEFAULT: ADBServer

    def __init__(self, address=('127.0.0.1', 5037)):
        self.address = address

    def __repr__(self):
        address = f'{self.address[0]}:{self.address[1]}'
        return f'{self.__class__.__name__}({address!r})'

    def create_session(self):
        ensure_adb_alive(self)
        return self._create_session_nocheck()

    def _create_session_nocheck(self):
        return ADBClientSession(server=self.address)

    def service(self, cmd: str, timeout: Optional[float] = None):
        """make a service request to ADB server, consult ADB sources for available services"""
        session = self.create_session()
        session.sock.settimeout(timeout)
        session.service(cmd)
        return session

    def devices(self, show_offline=False):
        """returns list of devices that the adb server knows"""
        resp = self.service('host:devices').read_response().decode()
        devices = [tuple(line.rsplit('\t', 2)) for line in resp.splitlines()]
        if not show_offline:
            devices = [x for x in devices if x[1] != 'offline']
        return devices

    def connect(self, device, timeout=None):
        resp = self.service('host:connect:%s' % device, timeout=timeout).read_response().decode(errors='ignore')
        logger.debug('adb connect %s: %s', device, resp)
        if 'unable' in resp or 'cannot' in resp:
            raise RuntimeError(resp)

    def disconnect(self, device):
        resp = self.service('host:disconnect:%s' % device).read_response().decode(errors='ignore')
        logger.debug('adb disconnect %s: %s', device, resp)
        if 'unable' in resp or 'cannot' in resp:
            raise RuntimeError(resp)

    def disconnect_all_offline(self):
        with contextlib.suppress(RuntimeError):
            for x in self.devices():
                if x[1] == 'offline':
                    with contextlib.suppress(RuntimeError):
                        self.disconnect(x[0])

    def paranoid_connect(self, port, timeout=5):
        with contextlib.suppress(RuntimeError):
            self.disconnect(port)
        self.connect(port, timeout=timeout)

    def _check_device(self, device: ADBDevice) -> ADBDevice:
        device.create_session().close()
        return device

    def get_device(self, serial: Optional[str] = None) -> ADBDevice:
        """Connect to a device"""
        return self._check_device(ADBDevice(serial, self))

    def get_usbdevice(self) -> ADBDevice:
        """switch to a USB-connected device"""
        return self._check_device(ADBAnyUSBDevice(self))

    def get_emulator(self) -> ADBDevice:
        """switch to an (SDK) emulator device"""
        return self._check_device(ADBAnyEmulatorDevice(self))


class ADBDevice:
    def __init__(self, serial: Optional[str] = None, server: Optional[ADBServer] = None):
        self.serial = serial
        self.server = server or ADBServer.DEFAULT

    def __repr__(self):
        return f'{self.__class__.__name__}({self.server!r}, serial={self.serial!r})'

    def create_session(self):
        if self.serial is not None:
            session = self._create_session_retry()
        else:
            session = self.server.create_session()
            session.service('host:transport-any')
        return session

    def _create_session_retry(self, retry_count=0):
        session = self.server.create_session()
        try:
            session.service('host:transport:' + self.serial)
            return session
        except RuntimeError as e:
            session.close()
            if retry_count == 0 and e.args and isinstance(e.args[0], bytes) and b'not found' in e.args[0]:
                if ':' in self.serial and self.serial.split(':')[-1].isdigit():
                    logger.info('adb connect %s', self.serial)
                    self.server.paranoid_connect(self.serial)
                    return self._create_session_retry(retry_count + 1)
            raise

    def service(self, cmd: str):
        """make a service request to adbd, consult ADB sources for available services"""
        session = self.create_session()
        session.service(cmd)
        return session

    def exec_stream(self, cmd=''):
        """run command in device, with stdout/stdin attached to the socket returned"""
        return self.service('exec:' + cmd).detach()

    def exec(self, cmd):
        """run command in device, returns stdout content after the command exits"""
        if len(cmd) == 0:
            raise ValueError('no command specified for blocking exec')
        sock = self.exec_stream(cmd)
        data = recvall(sock)
        sock.close()
        return data

    def shell_stream(self, cmd=''):
        """run command in device, with pty attached to the socket returned"""
        return self.service('shell:' + cmd).detach()

    def shell(self, cmd):
        """run command in device, returns pty output after the command exits"""
        if len(cmd) == 0:
            raise ValueError('no command specified for blocking shell')
        sock = self.shell_stream(cmd)
        data = recvall(sock)
        sock.close()
        return data

    def push(self, target_path: str, buffer: ReadableBuffer, mode=0o100755, mtime: int = None):
        """push data to device"""
        # Python has no type hint for buffer protocol, why?
        sock = self.service('sync:').detach()
        request = b'%s,%d' % (target_path.encode(), mode)
        sock.send(b'SEND' + struct.pack("<I", len(request)) + request)
        sendbuf = np.empty(65536 + 8, dtype=np.uint8)
        sendbuf[0:4] = np.frombuffer(b'DATA', dtype=np.uint8)
        input_arr = np.frombuffer(buffer, dtype=np.uint8)
        for arr in np.array_split(input_arr, np.arange(65536, input_arr.size, 65536)):
            sendbuf[4:8].view('<I')[0] = len(arr)
            sendbuf[8:8 + len(arr)] = arr
            sock.sendall(sendbuf[0:8 + len(arr)])
        if mtime is None:
            mtime = int(time.time())
        sock.sendall(b'DONE' + struct.pack("<I", mtime))
        _check_okay(sock)
        _read_binlen_le(sock)
        sock.close()


@dataclass
class ADBControllerTarget:
    adb_server: ADBServer
    adb_serial: Optional[str]
    description: str
    adb_address: str
    dedup_priority: int
    auto_connect_priority: int
    display_id: Optional[int] = None
    override_identifier: Optional[str] = None
    preload_device_info: Optional[dict] = None

    def create_controller(self):
        from .adb_controller import ADBController
        device = self.get_device()
        preload = self.preload_device_info
        if preload is None:
            preload = {}
        return ADBController(device, self.display_id, preload, self.override_identifier)

    def get_device(self):
        return self.adb_server.get_device(self.adb_serial or self.adb_address)

    def describe(self):
        """returns identifier, description"""
        if self.override_identifier is not None:
            identifier = self.override_identifier
            description = f'{self.description}, {self.adb_serial or self.adb_address}'
        else:
            identifier = self.adb_serial or self.adb_address
            description = self.description
        if self.display_id:
            identifier += f':display={self.display_id}'
        return identifier, description

    def __str__(self):
        identifier, description = self.describe()
        return f'{identifier} ({description})'


class ADBClientSession:
    def __init__(self, server=None, timeout=None):
        if server is None:
            server = ('127.0.0.1', 5037)
        if server[0] == '127.0.0.1' or server[0] == '::1':
            timeout = 0.5
        sock = socket.create_connection(server, timeout=timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(None)
        self.sock: socket.socket = sock

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def service(self, cmd: str):
        """make a service request to ADB server, consult ADB sources for available services"""
        cmdbytes = cmd.encode()
        data = b'%04X%b' % (len(cmdbytes), cmdbytes)
        self.sock.send(data)
        _check_okay(self.sock)
        return self

    def read_response(self):
        """read a chunk of length indicated by 4 hex digits"""
        return _read_hexlen(self.sock)

    def detach(self):
        sock = self.sock
        self.sock = None
        return sock


class ADBAnyDevice(ADBDevice):
    def __init__(self, server: Optional[ADBServer] = None):
        super().__init__(None, server)


class ADBAnyUSBDevice(ADBDevice):
    def __init__(self, server: Optional[ADBServer] = None):
        super().__init__('<any usb>', server)

    def create_session(self):
        return self.server.create_session().service('host:transport-usb')


class ADBAnyEmulatorDevice(ADBDevice):
    def __init__(self, server: Optional[ADBServer] = None):
        super().__init__('<any emulator>', server)

    def create_session(self):
        return self.server.create_session().service('host:transport-local')
