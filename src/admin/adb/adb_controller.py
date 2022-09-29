from __future__ import annotations
from typing import Optional, Protocol, cast

import io
import logging
import random
import shlex
import socket
import struct
import time
import warnings
import zlib

from random import randint

import numpy as np

# import app

from src.admin.utils import cvimage
from src.admin.utils.socketutil import recvall
from revconn import ReverseConnectionHost
from adb_service import ADBServer, ADBDevice
from info import ADBDeviceInfo
from agent import ControlAgentClient
from ..config.setting import baseSetting

from ..common.config_enum import ConfigApp, EventAction, EventFlag, GroupName, KeyName, \
    ControllerCapabilities, InputMethod, ScreenshotMethod, ScreenshotTransport, AospScreencapEncoding

logger = logging.getLogger(__name__)

class AdbOperate():
    def get_input_capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities(0)
    def touch_tap(self, x: int, y: int, hold_time: float = 0) -> None:
        raise NotImplementedError
    def touch_swipe(self, x0, y0, x1, y1, move_duration=1, hold_before_release=0, interpolation='linear'):
        raise NotImplementedError
    def touch_event(self, action: EventAction, x: int, y: int, pointer_id = 0) -> None:
        raise NotImplementedError
    def key_event(self, action: EventAction, keycode: int, metastate: int = 0) -> None:
        raise NotImplementedError
    def send_key(self, keycode: int, metastate: int = 0) -> None:
        raise NotImplementedError
    def send_text(self, text: str) -> None:
        raise NotImplementedError
    def close(self) -> None:
        pass


class _TouchEventsInputImpl(AdbOperate):
    def touch_tap(self, x: int, y: int, hold_time: float = 0) -> None:
        """
        鼠标点击操作
        :param x: 目标点x坐标
        :param y: 目标点y坐标
        :param hold_time: 按下到抬起的持续时间(单位：秒)
        :return:
        """
        self.touch_event(EventAction.DOWN, x, y)
        time.sleep(hold_time)
        self.touch_event(EventAction.UP, x, y)


    def touch_swipe(self, x0, y0, x1, y1, move_duration=1, hold_before_release=0, interpolation='linear'):
        """
        鼠标拖动操作
        :param x0: 起始点x坐标
        :param y0: 起始点y坐标
        :param x1: 目标点x坐标
        :param y1: 目标点y坐标
        :param move_duration: 总操作时间(单位：秒)
        :param hold_before_release: 操作完成后等待时间(单位：秒)
        :param interpolation: 选择移动距离与时间关系函数的插值方法 liner：线性插值， spline：样条插值
        :return:
        """
        caps = self.get_input_capabilities()
        if ControllerCapabilities.LOW_LATENCY_INPUT not in caps:
            raise NotImplementedError("default implementation of touch_swipe requires low-latency input")
        interpolate = self.select_interpolation(interpolation)
        # 一帧的时长
        frame_time = 1 / 100
        start_time = time.perf_counter()
        end_time = start_time + move_duration
        self.touch_event(EventAction.DOWN, x0, y0)
        t1 = time.perf_counter()
        step_time = t1 - start_time
        if step_time < frame_time:
            time.sleep(frame_time - step_time)
        while True:
            t0 = time.perf_counter()
            if t0 > end_time:
                break
            # 时间比例
            time_progress = (t0 - start_time) / move_duration
            # 移动比例
            path_progress = interpolate(time_progress)
            self.touch_event(EventAction.MOVE, int(x0 + (x1 - x0) * path_progress), int(y0 + (y1 - y0) * path_progress))
            t1 = time.perf_counter()
            step_time = t1 - t0
            if step_time < frame_time:
                time.sleep(frame_time - step_time)
        # 最后移动到目标位置
        self.touch_event(EventAction.MOVE, x1, y1)
        if hold_before_release > 0:
            time.sleep(hold_before_release)
        self.touch_event(EventAction.UP, x1, y1)

    def select_interpolation(self, interpolation='linear'):
        """
        选择移动距离与时间关系函数的插值方法
        :param interpolation:  liner：线性插值， spline：样条插值
        :return: function函数
        """
        if interpolation == 'linear':
            return lambda x: x
        elif interpolation == 'spline':
            from scipy.interpolate import splev, splrep
            xs = [0, random.uniform(0.7, 0.8), 1, 2]
            ys = [0, random.uniform(0.9, 0.95), 1, 1]
            tck = splrep(xs, ys, s=0)
            return lambda x: splev(x, tck, der=0)
        else:
            # 其他情况默认为线性插值
            return lambda x: x

class ShellInputAdapter(AdbOperate):
    def __init__(self, controller: ADBController, displayid):
        self.controller = controller

        if displayid is not None and displayid != 0:
            if controller.sdk_version >= 29:
                self.input_command = f'input -d {displayid}'
            else:
                raise NotImplementedError('shell input on this device does not support multi display')
        else:
            self.input_command = 'input'
        # `input motionevent` is supported since Android 9 (API 28), however it needs to spawn an 
        # app_process on each event before Android 11 (API 30), resulting in significant delay (~200 ms)
        self.support_motion_events = False
        if controller.sdk_version >= 30:
            self.caps = ControllerCapabilities.LOW_LATENCY_INPUT | ControllerCapabilities.TOUCH_EVENTS
            self.support_motion_events = True
        else:
            self.caps = ControllerCapabilities(0)

    def touch_tap(self, x, y, hold_time=0):
        if hold_time > 0:
            self.controller.adb.exec(f'{self.input_command} swipe {x} {y} {x} {y} {hold_time * 1000:.0f}')
        else:
            self.controller.adb.exec(f'{self.input_command} tap {x} {y}')

    def touch_swipe(self, x0, y0, x1, y1, move_duration=1, hold_before_release=0, interpolation='linear'):
        if self.support_motion_events:
            # use default implementation if `input motionevent` is supported
            return _TouchEventsInputImpl.touch_swipe(self, x0, y0, x1, y1, move_duration, hold_before_release,
                                                     interpolation)
        if hold_before_release > 0:
            warnings.warn(
                'hold_before_release is not supported in shell mode, you may experience unexpected inertia scrolling')
        if interpolation != 'linear':
            warnings.warn('interpolation mode other than linear is not supported in shell mode')
        self.controller.adb.exec(f'{self.input_command} swipe {x0} {y0} {x1} {y1} {move_duration * 1000:.0f}')

    def send_text(self, text):
        escaped_text = shlex.quote(text)
        self.controller.adb.exec(f'{self.input_command} text {escaped_text}')

    def send_key(self, keycode: int, hold_time=0.07):
        self.controller.adb.exec(f'{self.input_command} keyevent {keycode}')

    def touch_event(self, action: EventAction, x: int, y: int, pointer_id=0) -> None:
        if not self.support_motion_events:
            raise io.UnsupportedOperation('touch events is not available')
        if pointer_id != 0:
            raise NotImplementedError("multitouch is not supported")
        if action == EventAction.DOWN:
            self.controller.adb.exec(f'{self.input_command} motionevent DOWN {x} {y}')
        elif action == EventAction.UP:
            self.controller.adb.exec(f'{self.input_command} motionevent UP {x} {y}')
        elif action == EventAction.MOVE:
            self.controller.adb.exec(f'{self.input_command} motionevent MOVE {x} {y}')

    def key_event(self, action: EventAction, keycode: int, metastate: int = 0) -> None:
        raise NotImplementedError

class ScreenshotProtocol():
    def get_screenshot_capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities(0)
    def screenshot(self) -> cvimage.Image:
        raise NotImplementedError
    def close(self) -> None:
        pass

class ShellScreenshotAdapter(ScreenshotProtocol):
    def __init__(self, controller: ADBController, displayid):
        if controller.sdk_version <= 25:
            if displayid is not None and displayid != 0:
                raise NotImplementedError('shell screenshot on this device does not support multi display')
        self.controller = controller
        use_encoding, use_transport = self._select_simulator_image_setting()
        pending_impl = None
        if use_transport == 'adb' and use_encoding == 'raw':
            pending_impl = self._screenshot_adb_raw
        elif use_transport == 'adb' and use_encoding == 'gzip':
            pending_impl = self._screenshot_adb_compressed
        elif use_transport == 'adb' and use_encoding == 'png':
            pending_impl = self._screenshot_adb_png
        elif use_transport == 'vm_network':
            if controller.device_info.nat_to_host_loopback:
                pending_impl = self._screenshot_nc_connect

        self._impl = self._screenshot_adb_raw
        screenshot = None
        if pending_impl is not None:
            try:
                logger.debug('testing quirk implementation %s ', pending_impl.__name__)
                screenshot = pending_impl()
                self._impl = pending_impl
                logger.debug('quirk implementation %s test passed', pending_impl.__name__)
            except:
                logger.debug('quirk implementation failed, falling back to adb raw', exc_info=True)

        if screenshot is None:
            screenshot = self._impl()
            _check_invalid_screenshot(screenshot)

    def _select_simulator_image_setting(self):
        """
        解析模拟器截图图片压缩格式 和 模拟器截图图片传输方式 参数
        :param controller:
        :return: 模拟器截图图片压缩格式, 模拟器截图图片传输方式
        """
        device_info = self.controller.device_info
        # 配置文件中读取[模拟器截图图片压缩格式]和[模拟器截图图片传输方式]
        baseSetting.select_app(ConfigApp.BASE).select_group(GroupName.Simulator)
        use_encoding_name = baseSetting.get(KeyName.AospScreenshotEncoding)
        use_transport_name = baseSetting.get(KeyName.ScreenshotTransport)

        if use_transport_name == ScreenshotTransport.auto.name \
                and device_info.slow_adb_connection() and device_info.emulator_hypervisor:
            use_transport = ScreenshotTransport.vm_network
        else:
            use_transport = ScreenshotTransport.adb

        if use_encoding_name == AospScreencapEncoding.auto.name:
            if use_transport == ScreenshotTransport.vm_network:
                use_encoding = AospScreencapEncoding.raw
            elif device_info.slow_adb_connection:
                use_encoding = AospScreencapEncoding.gzip
            else:
                use_encoding = AospScreencapEncoding.raw
        else:
            use_encoding = AospScreencapEncoding[use_encoding_name]
        use_encoding = use_encoding or AospScreencapEncoding.raw
        return use_encoding.name, use_transport.name


    def __repr__(self):
        return f'<{self.__class__.__name__} {self._impl.__name__}>'

    def _decode_screencap(self, data) -> cvimage.Image:
        w, h, format = struct.unpack_from('<III', data, 0)
        hdrlen = 0
        if self.controller.sdk_version >= 28:
            # new format for Android P
            colorspace = struct.unpack_from('<I', data, 12)[0]
            hdrlen = 16
        else:
            colorspace = 0
            hdrlen = 12
        logger.debug(f'{w=} {h=} {format=} datalen={len(data)}')
        if len(data) < hdrlen + w * h * 4:
            raise ValueError('screencap short read')
        pixels = data[hdrlen:]
        arr: np.ndarray = np.frombuffer(pixels, dtype=np.uint8)
        arr = arr.reshape((h, w, 4))
        im = cvimage.fromarray(arr, 'RGBA')
        if colorspace == 2:
            from ..imgreco.cms import p3_to_srgb_inplace
            im = p3_to_srgb_inplace(im)
        return im

    def _decode_screencap_png(self, pngdata):
        bio = io.BytesIO(pngdata)
        from PIL import Image as PILImage, ImageCms
        img = PILImage.open(bio)
        if icc := img.info.get('icc_profile', ''):
            iccio = io.BytesIO(icc)
            src_profile = ImageCms.ImageCmsProfile(iccio)
            from ..imgreco.cms import srgb_profile
            ImageCms.profileToProfile(img, src_profile, srgb_profile, ImageCms.INTENT_RELATIVE_COLORIMETRIC,
                                      inPlace=True)
        return cvimage.from_pil(img)

    def _screenshot_adb_raw(self):
        sock = self.controller.adb.exec_stream('screencap')
        data = recvall(sock, 8388608, True)
        sock.close()
        return self._decode_screencap(data)

    def _screenshot_adb_png(self):
        sock = self.controller.adb.exec_stream('screencap -p')
        data = recvall(sock, 8388608, True)
        sock.close()
        return self._decode_screencap_png(data)

    def _screenshot_adb_compressed(self):
        sock = self.controller.adb.exec_stream('screencap | gzip -1')
        data = recvall(sock, 8388608, True)
        sock.close()
        data = zlib.decompress(data, zlib.MAX_WBITS | 16, 8388608)
        return self._decode_screencap(data)

    def _screenshot_nc_connect(self):
        nc_command = self.controller.device_info.nc_command
        nat_address = self.controller.device_info.nat_to_host_loopback
        rch = ReverseConnectionHost.get_instance()
        future = rch.register_cookie()
        with self.controller.adb.exec_stream(
                f'(echo {future.cookie.decode()}; screencap) | {nc_command} {nat_address} {rch.port}'):
            with future.result(10) as sock:
                data = recvall(sock, 8388608, True)
        return self._decode_screencap(data)

    def _screenshot_nc_listen(self):
        address = self.controller.device_info.host_l2_reachable
        with self.controller.adb.exec_stream(f'screencap | nc -l -p {self._listen_port}'):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.connect((address, self._listen_port))
                data = recvall(sock, 8388608, True)
        return self._decode_screencap(data)

    def screenshot(self):
        return self._impl()


class AahAgentClientAdapter(_TouchEventsInputImpl, ScreenshotProtocol):
    def __init__(self, controller: ADBController, displayid):
        self.controller = controller
        self.displayid = displayid
        self.display_connected = False
        self.client = ControlAgentClient(controller.adb, displayid)
        self.compress = controller.device_config.aah_agent_compress
        self.connection_types = {'input': 'adb'}

    def __repr__(self):
        if self.connection_types:
            description = ''
            for k, v in self.connection_types.items():
                description += f' {k}({v})'
        else:
            description = ' (not connected)'
        return f'<{self.__class__.__name__}{description}>'

    def open_screenshot_connection(self):
        logger.debug('opening aah-agent screenshot connection')
        try:
            if self.controller.device_config.screenshot_transport != 'adb':
                if loopback := self.controller.device_info.nat_to_host_loopback:
                    logger.debug('applying nat_to_host_loopback quirk')
                    rch = ReverseConnectionHost.get_instance()
                    future = rch.register_cookie()
                    logger.debug('listening for screenshot connection on %s:%d', loopback, rch.port)
                    self.client.open_screenshot('connect', (loopback, rch.port), future.cookie, future)
                    self.connection_types['screenshot'] = 'nat_to_host_loopback'
                    self.display_connected = True
                elif address := self.controller.device_info.host_l2_reachable:
                    logger.debug('applying host_l2_reachable quirk')
                    logger.debug('opening screenshot connection on %s', address)
                    self.client.open_screenshot('listen', (address, 0))
                    self.connection_types['screenshot'] = 'host_l2_reachable'
                    self.display_connected = True
        except:
            logger.debug('error while applying quirk', exc_info=True)
        if not self.display_connected:
            self.client.open_screenshot('adb')
            self.connection_types['screenshot'] = 'adb'
            self.display_connected = True

    def get_input_capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities.TOUCH_EVENTS | ControllerCapabilities.MULTITOUCH_EVENTS | ControllerCapabilities.LOW_LATENCY_INPUT | ControllerCapabilities.KEYBOARD_EVENTS

    def get_screenshot_capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities.SCREENSHOT_TIMESTAMP

    def touch_event(self, action: EventAction, x: int, y: int, pointer_id=0) -> None:
        return self.client.touch_event(action, x, y, pointer_id)

    def key_event(self, action: EventAction, keycode: int, metastate: int = 0) -> None:
        return self.client.key_event(action, keycode, metastate)

    def send_key(self, keycode: int, metastate: int = 0) -> None:
        return self.client.send_key(keycode, metastate)

    def send_text(self, text: str) -> None:
        return self.client.send_text(text)

    def screenshot(self) -> cvimage.Image:
        wrapped_img = self.client.screenshot(compress=self.compress, srgb=True)
        return wrapped_img.image

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None


def _check_invalid_screenshot(image: cvimage.Image):
    alpha_channel: np.ndarray = image.array[..., 3]
    if np.all(alpha_channel == 0):
        raise io.UnsupportedOperation('screenshot with all pixels alpha = 0')


class ADBController:
    def __init__(self, device: ADBDevice, display_id: Optional[int] = None, preload_device_info: dict = {},
                 override_identifier: Optional[str] = None):
        """
        Creates a new ADBController instance.

        :param device: the device to control
        :param display_id: the display id to use for the device, if not specified, the default display id is used
        :param preload_quirks: quirks to preload, preloaded quirks won't be cheked again
        :param override_identifier: overrides the device identifier for quirks store, useful for custom enumerators
        """
        self.adb = device
        self.display_id = display_id
        sdk_version_str = self.adb.exec('getprop ro.build.version.sdk').strip()
        try:
            self.sdk_version = int(sdk_version_str)
        except ValueError:
            self.sdk_version = 19
        self.device_identifier = override_identifier or self._get_device_identifier()
        # 更新驱动信息
        self._probe_quirks(preload_device_info)

        self.input = None
        self._screenshot_adapter = None

        self._last_screenshot = None
        self._last_screenshot_expire = 0
        baseSetting.select_app(ConfigApp.BASE).select_group(GroupName.Simulator)

        if baseSetting.get(KeyName.InputMethod) == InputMethod.aah_agent.name \
                or baseSetting.get(KeyName.ScreenshotMethod) == ScreenshotMethod.aah_agent.name:
            try:
                agent_client = AahAgentClientAdapter(self, self.display_id)
                if self.device_config.input_method == 'aah-agent':
                    self.input = agent_client
                if self.device_config.screenshot_method == 'aah-agent':
                    try:
                        # raise RuntimeError
                        agent_client.open_screenshot_connection()
                        _check_invalid_screenshot(agent_client.screenshot())
                        self._screenshot_adapter = agent_client
                    except io.UnsupportedOperation:
                        if self.device_info.emulator_hypervisor():
                            logger.warning('当前模拟器不支持 aah-agent 截图。如果模拟器显示卡死，请重启模拟器并尝试切换渲染模式，或在设置中关闭 aah-agent 截图。',
                                           exc_info=True)
                        else:
                            logger.warning('当前设备不支持 aah-agent 截图。如果设备显示卡死，请重启设备并在设置中关闭 aah-agent 截图。', exc_info=True)
                        self.device_config.save()
                    except:
                        logger.debug('failed to open aah-agent screenshot connection', exc_info=True)
            except:
                logger.debug('failed to create aah-agent client', exc_info=True)

        if self.input is None:
            self.input = ShellInputAdapter(self, self.display_id)
        if self._screenshot_adapter is None:
            self._screenshot_adapter = ShellScreenshotAdapter(self, self.display_id)

        # make IDEs happy
        self.input = cast(InputProtocol, self.input)
        self._screenshot_adapter = cast(ScreenshotProtocol, self._screenshot_adapter)

        logger.debug('using input adapter %s', self.input)
        logger.debug('using screenshot adapter %s', self._screenshot_adapter)

    def _get_device_identifier(self):
        logger.debug('get_device_identifier: getprop net.hostname')
        hostname = self.adb.exec('getprop net.hostname').decode().strip()
        if hostname:
            return hostname
        logger.debug('get_device_identifier: settings get secure android_id')
        android_id = self.adb.exec('settings get secure android_id').decode().strip()
        if android_id:
            return android_id

    def __repr__(self):
        return f"<{self.__class__.__name__} adb={self.adb} device_info={dict(self.device_info._mapping)} device_config={dict(self.device_config._mapping)} _screenshot_adapter={self._screenshot_adapter} input={self.input}>"

    def __str__(self):
        return self.device_identifier

    def _probe_quirks(self, preload_device_info):
        self.device_info = ADBDeviceInfo(self.adb)
        self.device_info.load_update(preload_device_info)

    @property
    def capabilities(self) -> ControllerCapabilities:
        return self.input.get_input_capabilities() | self._screenshot_adapter.get_screenshot_capabilities()

    def screenshot(self, cached: bool = True) -> cvimage.Image:
        rate_limit = app.config.device.screenshot_rate_limit
        if rate_limit == 0:
            return self._screenshot_adapter.screenshot()
        t0 = time.perf_counter()
        if not cached or self._last_screenshot is None or t0 > self._last_screenshot_expire:
            self._last_screenshot = self._screenshot_adapter.screenshot()
            t1 = time.perf_counter()
            if rate_limit == -1:
                self._last_screenshot_expire = t1 + (t1 - t0)
            else:
                self._last_screenshot_expire = t0 + (1 / rate_limit)
        return self._last_screenshot

    def close(self):
        self.input.close()
        self._screenshot_adapter.close()

    def touch_swipe2(self, origin, movement, duration=None):
        """DEPRECATED: use input.touch_swipe() instead"""
        # sleep(1)
        x1, y1, x2, y2 = origin[0], origin[1], origin[0] + movement[0], origin[1] + movement[1]

        logger.debug("滑动初始坐标:({},{}); 移动距离dX:{}, dy:{}".format(*origin, *movement))
        if duration is None:
            duration = 1000
        self.input.touch_swipe(x1, y1, x2, y2, duration / 1000)

    def touch_tap(self, XY=None, offsets=None):
        """DEPRECATED: use input.touch_tap() instead"""
        # sleep(10)
        # sleep(0.5)
        if offsets is not None:
            final_X = XY[0] + randint(-offsets[0], offsets[0])
            final_Y = XY[1] + randint(-offsets[1], offsets[1])
        else:
            final_X = XY[0] + randint(-1, 1)
            final_Y = XY[1] + randint(-1, 1)
        logger.debug("点击坐标:({},{})".format(final_X, final_Y))
        self.input.touch_tap(final_X, final_Y)

# def _test():
#     app.init()
#     logging.basicConfig(level=logging.NOTSET, force=True)
#     print('foo')
#     t0 = time.perf_counter()
#     dev = ADBServer.DEFAULT.get_device('127.0.0.1:59119')
#
#     print(dev.exec('uname -a').decode())
#     ctrl = ADBController(dev, override_identifier='BlueStacks:Nougat64_nxt22222')
#     t1 = time.perf_counter()
#     print(f"initialization take {t1-t0:.3f} s")
#     import IPython
#     IPython.embed(colors='neutral')
#
# if __name__ == '__main__':
#     _test()
