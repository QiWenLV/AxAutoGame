from enum import IntEnum, Enum, unique, IntFlag, auto, Flag


# class BaseEnum(Enum):
#
#     def for  in ConfigApp:
#


class ConfigApp(Enum):
    BASE = 0
    MBCC = 1
    Arknights = 2


class EventAction(IntEnum):
    DOWN = 0
    UP = 1
    MOVE = 2


class ControllerCapabilities(Flag):
    SCREENSHOT_TIMESTAMP = auto()
    """screenshots include a render timestamp"""

    LOW_LATENCY_INPUT = auto()
    """input is processed immediately, on contrast to the legacy `input` command that spawns an `app_process`"""

    TOUCH_EVENTS = auto()
    """touch events (pointer down/move/up) are supported"""

    KEYBOARD_EVENTS = auto()
    """keyboard events (key down/up) are supported"""

    MULTITOUCH_EVENTS = auto()
    """multitouch events (more than one pointer down/move/up) are supported"""


class EventFlag(IntFlag):
    ASYNC = 0x1
    MERGE_MULTITOUCH_MOVE = 0x2


# 模拟器虚拟化类型
class Hypervisor(Enum):
    VBOX = "vbox"
    HYPER_V = "hyper-v"


# 模拟器截图图片编码格式
class AospScreencapEncoding(Enum):
    auto = "auto"
    raw = "raw"
    gzip = "gzip"
    png = "png"

# 模拟器截图图片传输方式
class ScreenshotTransport(Enum):
    auto = "auto"
    adb = "adb"
    vm_network = "vm_network"

# 输入注入方式
class InputMethod(Enum):
    aah_agent = "aah_agent"
    aosp_input = "aosp_input"

# 输入注入方式
class ScreenshotMethod(Enum):
    aah_agent = "aah_agent"
    aosp_screencap = "aosp_screencap"


class GroupName(Enum):
    Simulator = "Simulator"


class KeyName(Enum):
    Address = "Address"
    AospScreenshotEncoding = "AospScreenshotEncoding"
    ScreenshotTransport = "ScreenshotTransport"
    InputMethod = "InputMethod"
    ScreenshotMethod = "ScreenshotMethod"