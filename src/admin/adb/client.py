from adb_service import ADBServer
from typing import Optional
from functools import lru_cache
import logging
from typing import Protocol
from adb_service import ADBControllerTarget

logger = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def get_adb_server_by_address(server: str) -> ADBServer:
    ip, port = server.split(':', 1)
    port = int(port)
    if ip == '127.0.0.1' and port == 5037:
        return ADBServer.DEFAULT
    return ADBServer((ip, port))


def get_target_from_adb_serial(serial, enumerated_targets: Optional[list[Protocol]] = None):
    if enumerated_targets is None:
        enumerated_targets = enum_targets()
    for target in enumerated_targets:
        if isinstance(target, ADBControllerTarget) and target.adb_serial == serial:
            return target
    server = get_adb_server_by_address()
    return ADBControllerTarget(server, serial, 'unknown adb target', None, 0, 0)

def enum_targets():
    import app
    result = []
    if app.config.device.extra_enumerators.bluestacks_hyperv:
        from .bluestacks_hyperv import enum as enum_bluestacks_hyperv
        result.extend(enum_bluestacks_hyperv())
    if app.config.device.extra_enumerators.vbox_emulators:
        from .vbox import enum as enum_vbox
        result.extend(enum_vbox())
    from .devices import enum as enum_adb
    result.extend(enum_adb())
    if app.config.device.extra_enumerators.append:
        from .append import enum as enum_append
        result.extend(enum_append())
    from ..target import dedup_targets
    return dedup_targets(result)