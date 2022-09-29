from __future__ import annotations

from functools import cached_property
import time
from typing import TYPE_CHECKING, Optional
from ..config.setting import baseSetting
from ..common.config_enum import Hypervisor
from .adb_controller import ADBController
from .adb_service import ADBDevice
from ..utils.socketutil import recvall

if TYPE_CHECKING:
    from .client import ADBDevice

import logging

logger = logging.getLogger(__name__)


class ADBDeviceInfo():

    def __init__(self, controller: ADBDevice):
        self._device = controller

    def load_update(self, preload_device_info):
        pass

    # ADB 传输速度（MiB/s）
    def adb_connection_speed(self):
        if self._device is None:
            return 0.0
        buf = bytearray(4096)
        t0 = time.perf_counter()
        sock = self._device.exec_stream('dd if=/dev/zero bs=2048 count=2048 status=none')
        with sock:
            rcvlen = sock.recv_into(buf, 1)
            if rcvlen == 0:
                return 0.0
            tfb = time.perf_counter()
            while time.perf_counter() - tfb < 0.5:
                chunklen = sock.recv_into(buf, 4096)
                if chunklen == 0:
                    break
                rcvlen += chunklen
            tend = time.perf_counter()
        mbytes_per_sec = (rcvlen / 1024 / 1024) / (tend - tfb)
        logger.debug('ADB connection speed: %d bytes in %.3f s - %.2f MiB/s, TTFB %.3f s', rcvlen, tend - tfb,
                     mbytes_per_sec, tfb - t0)
        return mbytes_per_sec

    # 慢速 ADB 连接
    def slow_adb_connection(self):
        return self.adb_connection_speed() < 64

    # 模拟器虚拟化类型
    def emulator_hypervisor(self):
        if self._device is None:
            return None
        if self._device.serial.startswith('emulator-') or self._device.serial.startswith('127.0.0.1:'):
            board = self._device.exec('getprop ro.product.board')
            if b'goldfish' in board:
                return 'avd'
            disk_vendor = self._device.exec(
                'cat /sys/class/block/?da/device/vendor 2>/dev/null').decode().strip()
            disk_model = self._device.exec('cat /sys/class/block/?da/device/model 2>/dev/null').decode().strip()
            full_disk_model = f'{disk_vendor} {disk_model}'.strip()
            if 'VBOX' in full_disk_model:
                return Hypervisor.VBOX
            elif 'Msft Virtual' in full_disk_model:
                return Hypervisor.HYPER_V
        return None

    # NAT 到宿主机本地回环的 IP 地址, doc=用于绕过 adb 连接的 NAT 端口
    def nat_to_host_loopback(self):
        if self.emulator_hypervisor == 'avd':
            return '10.0.2.2'
        if self.emulator_hypervisor == 'vbox':
            arp = self._device.exec('cat /proc/net/arp')
            possible_loopbacks = [x[:x.find(b' ')].decode() for x in arp.splitlines()[1:]]
            if possible_loopbacks:
                loopback = self.test_reverse_connection(possible_loopbacks, self.nc_command())
                return loopback
        return None

    # 宿主机可访问的 IP 地址, doc=用于绕过 adb 连接的 L2 端口
    def host_l2_reachable(self):
        if self.emulator_hypervisor == 'hyper-v':
            import ipaddress
            addrs = self._device.exec('ip -4 addr | grep "scope global"').decode().strip().split('\n')
            for addrline in addrs:
                if 'tun' in addrline or 'tap' in addrline:
                    continue
                tokens = addrline.strip().split(' ', 2)
                network = tokens[1]
                try:
                    addr = ipaddress.ip_interface(network)
                    if addr.network.is_private:
                        return str(addr.ip)
                except:
                    pass
        return None

    # nc 命令, doc=用于绕过 adb 连接的 nc 命令
    def nc_command(self):
        candidates = ['nc', 'busybox nc']
        # TODO: push static busybox to device
        for candidate in candidates:
            response = self._device.exec(f'{candidate} 127.0.0.1 0')
            if response.startswith(b'nc: '):
                # nc: port number too small: 0
                # nc: connect: Connection refused
                # nc: can't connect to remote host (127.0.0.1): Connection refused
                return candidate
        return None

    def test_reverse_connection(self, loopbacks: list[str], nc_command: str = 'nc'):
        if not loopbacks:
            return None
        from .revconn import ReverseConnectionHost
        rch = ReverseConnectionHost.get_instance()
        for addr in loopbacks:
            logger.debug('testing loopback address %s', addr)
            future = rch.register_cookie()
            cmd = 'echo -n %sOKAY | %s -w 1 %s %d' % (future.cookie.decode(), nc_command, addr, rch.port)
            logger.debug(cmd)
            control_sock = self._device.exec_stream(cmd)
            with control_sock:
                conn = future.result(2)
                if conn is not None:
                    data = recvall(conn)
                    conn.close()
                    if data == b'OKAY':
                        logger.debug('found loopback address %s', addr)
                        return addr
        return None

    # @UserReadOnlyField(int, title='窗口句柄')
    # def hwnd(self) -> Optional[int]:
    #     """
    #     indicates that the device can be captured and/or controlled by a window handle
    #     value: the window handle (hwnd on win32)
    #     """
    #     return None

    # @UserReadOnlyField(tuple[str, str], title='共享文件夹')
    # def shared_folder(self) -> Optional[tuple[str, str]]:
    #     """
    #     indicates that the device and the host can exchange files via a shared folder
    #     value: (host_shared_folder, device_shared_folder)
    #     """
    #     return None
