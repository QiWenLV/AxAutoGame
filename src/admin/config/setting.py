import json
import logging

from src.admin.common.base import Bean
from ..common.config_enum import *

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
        rstGroup: Group= self.setting.get(app).get(group)
        if rstGroup is None:
            logging.error("当前" + app.name + "没有" + group + "组")
            return None
        else:
            item: Member = rstGroup.members.get(key)
            return item.value


class Member:

    def __init__(self, item: dict):
        self.key = item['key']
        self.title = item['title']
        self.value = item['value']
        self.default_value = item['default_value']
        self.desc = item['desc']
        self.value_type = item['value_type']
        self.properties = item['properties']

    def set_options(self, arr):
        self.options = arr
        return self


class Property(Bean):
    __slots__ = ('display_name', 'key_name', 'value', 'desc')


class Group():

    def __init__(self, data: dict):
        self.app = data['app']
        self.group = data['group']
        self.group_name = data['group_name']
        self.desc = data['desc']
        self.members = {KeyName[item['key']]: Member(item) for item in data['members']}

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
    with open("src/resources/properties.json", encoding="utf-8") as properties_file:
        all_setting = json.load(properties_file)

    print(all_setting)
    # 迭代所有参数，进行转换
    for group in all_setting:
        baseSetting.setting[ConfigApp.BASE][GroupName[group["group"]]] = Group(group)

    return baseSetting


baseSetting = init_setting()
