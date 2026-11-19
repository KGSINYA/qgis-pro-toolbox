# -*- coding: utf-8 -*-
import os
import sys
import inspect
import importlib.util

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                                 QPushButton, QLabel, QTabWidget, QAction)
from qgis.core import Qgis

# 确保插件目录在系统路径中，方便子插件直接导入 BaseAddon
current_dir = os.path.dirname(__file__)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from base_addon import BaseAddon

class ProToolboxPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.addons_dir = os.path.join(self.plugin_dir, "addons")
        self.dock_widget = None
        self.action = None
        self.loaded_addons = []

    def initGui(self):
        """QGIS 启动时初始化"""
        self.action = QAction('🛠️ Pro Toolbox 生产提效工具箱', self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_window)
        self.iface.addPluginToMenu("Pro Toolbox", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """QGIS 关闭或卸载插件时清理垃圾"""
        self.unload_all_addons()

        if self.action:
            self.iface.removePluginMenu("Pro Toolbox", self.action)
            self.iface.removeToolBarIcon(self.action)

        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

    def unload_all_addons(self):
        """通知所有已加载的子模块清理自己的定时器、快捷键和线程"""
        for addon in self.loaded_addons:
            try:
                addon.unload()
            except Exception as e:
                print(f"[ProToolbox] 卸载模块 {addon.title} 时出错: {e}")
        self.loaded_addons.clear()
        if hasattr(self, 'tabs') and self.tabs:
            self.tabs.clear()

    def toggle_window(self):
        """开关工具箱窗口"""
        if not self.dock_widget:
            self.build_ui()
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
            self.dock_widget.setFloating(True)

        if self.dock_widget.isVisible():
            self.dock_widget.hide()
        else:
            self.dock_widget.show()
            self.dock_widget.raise_()

    def build_ui(self):
        """构建主界面（自动扫描 addons 文件夹）"""
        self.dock_widget = QDockWidget("Pro Toolbox 生产提效工具箱", self.iface.mainWindow())
        self.dock_widget.setAllowedAreas(Qt.AllDockWidgetAreas)

        def on_floating_changed(is_floating):
            if is_floating:
                self.dock_widget.setWindowFlags(
                    Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
                self.dock_widget.show()
            else:
                self.dock_widget.setWindowFlags(Qt.Widget)
                self.dock_widget.show()

        self.dock_widget.topLevelChanged.connect(on_floating_changed)

        # 主容器
        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # 顶部控制栏：以后往 addons 放新文件，点一下按钮就能加载，不用重启 QGIS
        top_bar = QHBoxLayout()
        self.lbl_status = QLabel("已加载模块: 0")
        self.lbl_status.setStyleSheet("color: #666; font-size: 12px;")

        btn_reload = QPushButton("🔄 重新扫描加载模块")
        btn_reload.setToolTip("往 addons 文件夹放入新模块后，点击此按钮即可立即生效")
        btn_reload.setStyleSheet("padding: 3px 8px; font-weight: bold;")
        btn_reload.clicked.connect(self.load_all_addons)

        top_bar.addWidget(self.lbl_status)
        top_bar.addStretch()
        top_bar.addWidget(btn_reload)
        main_layout.addLayout(top_bar)

        # Tab 页容器
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setUsesScrollButtons(True)
        main_layout.addWidget(self.tabs)

        self.dock_widget.setWidget(main_container)
        self.dock_widget.resize(400, 650)

        # 扫描并加载所有子模块
        self.load_all_addons()

    def load_all_addons(self):
        """核心引擎：自动读取 addons 文件夹下的所有 .py 文件并生成 Tab 页"""
        self.unload_all_addons()

        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)

        addon_classes = []

        for filename in sorted(os.listdir(self.addons_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            filepath = os.path.join(self.addons_dir, filename)
            module_name = f"qgis_pro_addon_{filename[:-3]}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if getattr(obj, '_is_pro_addon', False) and obj is not BaseAddon and obj.__name__ != 'BaseAddon':
                        addon_classes.append(obj)
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    "模块读取失败", f"{filename} 存在错误: {e}", level=Qgis.Warning, duration=5
                )

        # 按 order 数字从小到大排序
        addon_classes.sort(key=lambda cls: getattr(cls, 'order', 99))

        for cls in addon_classes:
            try:
                addon_instance = cls(self.iface, self.dock_widget, self.plugin_dir)
                tab_widget = QWidget()
                addon_instance.setup_ui(tab_widget)
                self.tabs.addTab(tab_widget, addon_instance.title)
                self.loaded_addons.append(addon_instance)
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    "模块启动失败", f"{getattr(cls, 'title', cls.__name__)} 报错: {e}", level=Qgis.Critical, duration=5
                )

        self.lbl_status.setText(f"已加载模块: {len(self.loaded_addons)} 个")