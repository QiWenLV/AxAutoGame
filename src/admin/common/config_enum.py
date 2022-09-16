from enum import IntEnum, Enum, unique


# class BaseEnum(Enum):
#
#     def for  in ConfigApp:
#

class ConfigApp(Enum):
    BASE = 0
    MBCC = 1
    Arknights = 2


class GroupName(Enum):
    pass


class BaseGroupName(GroupName):
    link = "连接"


class KeyName(Enum):
    pass


class BaseKeyName(KeyName):
    address = "地址"
