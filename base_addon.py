# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QWidget

class BaseAddon:
    """所有子功能模块的标准模板"""
    _is_pro_addon = True
    title = "🧩 未命名模块"
    order = 99  # 数字越小，Tab页排在越前面

    def __init__(self, iface, dock_widget, plugin_dir):
        self.iface = iface
        self.dock_widget = dock_widget
        self.plugin_dir = plugin_dir

    def setup_ui(self, parent_widget: QWidget):
        """在这里绘制该模块的界面"""
        pass

    def unload(self):
        """当关闭插件或刷新时，在这里清理定时器、快捷键或线程"""
        pass