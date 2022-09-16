from src.admin.config.setting import baseSetting
from src.admin.common.config_enum import *
from src.admin.adbHandler import BaseAutoHandler
from src.admin.adb.client import get_adb_server_by_address

if __name__ == '__main__':
    # 加载配置
    address = baseSetting.get(BaseKeyName.address, app=ConfigApp.BASE, group=BaseGroupName.link)
    autoHandler = BaseAutoHandler(get_adb_server_by_address(address))

