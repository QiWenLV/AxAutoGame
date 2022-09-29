import logging

from src.admin.utils import cvimage

logger = logging.getLogger('link')


class BaseAutoHandler():

    def __init__(self, device_conn, s):
        self.device_conn = device_conn
        pass

    def link_check(self):
        pass

    def link_device(self):
        if self.device_conn is not None:
            # from automator.control.adb.targets import get_target_from_adb_serial
            # self._controller = get_target_from_adb_serial(adb_serial).create_controller()
            self.link_check()

    # def screenshot(self, cached: bool = True) -> cvimage.Image:
