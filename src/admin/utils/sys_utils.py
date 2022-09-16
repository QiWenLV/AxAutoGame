from __future__ import annotations
import logging
import os
from pathlib import Path
import socket
import time
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


def find_adb_from_android_sdk():
    import platform
    system = platform.system()
    root = ''
    base = 'adb'

    try:
        if system == 'Windows':
            root = Path(os.environ['LOCALAPPDATA']).joinpath('Android', 'Sdk')
            base = 'adb.exe'
        elif system == 'Linux':
            root = Path(os.environ['HOME']).joinpath('Android', 'Sdk')
        elif system == 'Darwin':
            root = Path(os.environ['HOME']).joinpath('Library', 'Android', 'sdk')

        if 'ANDROID_SDK_ROOT' in os.environ:
            root = Path(os.environ['ANDROID_SDK_ROOT'])

        adbpath = root.joinpath('platform-tools', base)

        if adbpath.exists():
            return adbpath

    except:
        return None
