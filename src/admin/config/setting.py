from src.admin.common.base import Bean
from ..common.config_enum import *
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class BaseSetting:

    def __init__(self):
        self.setting = {}
        self.setting[ConfigApp.BASE] = {}

        self.currApp = ConfigApp.BASE
        self.currGroup = ""

    def put(self, app, group, key, value):
        self.setting.get(app)

    def select_app(self, app: ConfigApp):
        self.currApp = app
        return self

    def select_group(self, group: GroupName):
        self.currGroup = group
        return self

    def get(self, key: KeyName, app: ConfigApp = None, group: GroupName = None):
        if app is None:
            app = self.currApp
        if group is None:
            group = self.currGroup
        rstGroup = self.setting.get(app).get(group)
        if rstGroup is None:
            logging.error("当前" + app.name + "没有" + group + "组")
            return None
        else:
            return rstGroup.get(key)


class Member(Bean):
    __slots__ = ('key', 'value', 'default_value')

    def __init__(self, **kwargs):
        super(Member, self).__init__(**kwargs)


class Group(Bean):
    __slots__ = ('app', 'group_name', 'members')

    def __init__(self, **kwargs):
        super(Group, self).__init__(**kwargs)
        self.members = {}

    def add_member(self, member: Member):
        self.members[member.key] = member
        return self

    def get(self, key):
        rst: Member = self.members.get(key)
        if rst is None:
            return None
        if rst.value is None or "".__eq__(rst.value):
            return rst.default_value
        else:
            return rst.value


def init_setting():
    baseSetting = BaseSetting()
    app = ConfigApp.BASE

    linkGroup = Group(app=app, group_name=BaseGroupName.link) \
        .add_member(Member(key=BaseKeyName.address, default_value="127.0.0.1:62001"))

    baseGroup = [linkGroup]
    for group in baseGroup:
        baseSetting.setting[ConfigApp.BASE][group.group_name] = group
    return baseSetting


baseSetting = init_setting()
