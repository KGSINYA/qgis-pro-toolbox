# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QShortcut
from qgis.core import QgsProject, Qgis

from base_addon import BaseAddon

class LayerSwitchAddon(BaseAddon):
    title = tr("🗂️ 图层切换", "🗂️ Layer switcher")
    order = 2

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.ls_is_active = False
        self.ls_sc_left = None
        self.ls_sc_right = None

    def unload(self):
        if self.ls_is_active:
            self.ls_toggle_status()

    def setup_ui(self, parent_widget):
        layout = QVBoxLayout(parent_widget)

        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel(tr("📁 目标图层组:", "📁 Target layer group:")))
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.ls_refresh_groups()
        group_layout.addWidget(self.group_combo)

        refresh_btn = QPushButton(tr("🔄 刷新", "🔄 Refresh"))
        refresh_btn.setToolTip(tr("重新读取 QGIS 图层组", "Reload layer groups from QGIS"))
        refresh_btn.clicked.connect(self.ls_refresh_groups)
        group_layout.addWidget(refresh_btn)

        layout.addLayout(group_layout)

        tips = QLabel(tr("快捷键: 【左方向键】上一张 / 【右方向键】下一张\n(注意: 开启后属性表内将无法使用左右键移动光标)", "Shortcuts: [Left arrow] previous / [Right arrow] next\n(Note: while enabled, arrow keys won't move the attribute table cursor)"))
        tips.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(tips)

        self.btn_ls_toggle = QPushButton(tr("🟩 点击开启快捷键 (当前: 关)", "🟩 Enable shortcuts (currently off)"))
        self.btn_ls_toggle.setMinimumHeight(40)
        self.btn_ls_toggle.setStyleSheet("font-weight: bold;")
        self.btn_ls_toggle.clicked.connect(self.ls_toggle_status)
        layout.addWidget(self.btn_ls_toggle)

        layout.addStretch()

    def ls_refresh_groups(self):
        self.group_combo.clear()
        root = QgsProject.instance().layerTreeRoot()
        groups = [child.name() for child in root.children() if child.nodeType() == 0]
        self.group_combo.addItems(groups)

        if tr("影像对比", "Image comparison") in groups:
            self.group_combo.setCurrentText(tr("影像对比", "Image comparison"))

    def ls_toggle_status(self):
        if self.ls_is_active:
            if self.ls_sc_left:
                self.ls_sc_left.setEnabled(False)
                self.ls_sc_left.deleteLater()
            if self.ls_sc_right:
                self.ls_sc_right.setEnabled(False)
                self.ls_sc_right.deleteLater()
            self.ls_sc_left = None
            self.ls_sc_right = None

            self.ls_is_active = False
            self.btn_ls_toggle.setText(tr("🟩 点击开启快捷键 (当前: 关)", "🟩 Enable shortcuts (currently off)"))
            self.btn_ls_toggle.setStyleSheet("font-weight: bold;")
        else:
            self.ls_sc_left = QShortcut(QKeySequence(Qt.Key_Left), self.iface.mainWindow())
            self.ls_sc_left.setContext(Qt.ApplicationShortcut)
            self.ls_sc_left.activated.connect(lambda: self.ls_switch_layer("prev"))

            self.ls_sc_right = QShortcut(QKeySequence(Qt.Key_Right), self.iface.mainWindow())
            self.ls_sc_right.setContext(Qt.ApplicationShortcut)
            self.ls_sc_right.activated.connect(lambda: self.ls_switch_layer("next"))

            self.ls_is_active = True
            self.btn_ls_toggle.setText(tr("🟦 点击关闭快捷键 (当前: 开)", "🟦 Disable shortcuts (currently on)"))
            self.btn_ls_toggle.setStyleSheet("background-color: #c8e6c9; color: #2e7d32; font-weight: bold;")

    def ls_switch_layer(self, direction):
        group_name = self.group_combo.currentText()
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)

        if not group:
            self.iface.messageBar().pushMessage(tr("错误", "Error"), tr(f"找不到图层组 '{group_name}'", f"Layer group '{group_name}' not found"), level=Qgis.Warning, duration=3)
            return

        layers = group.findLayers()
        if not layers:
            return

        current_index = -1
        for i, l in enumerate(layers):
            if l.isVisible():
                current_index = i
                break

        if direction == "next":
            next_index = (current_index + 1) % len(layers)
        else:
            next_index = (current_index - 1) % len(layers)

        current_layer_name = ""
        for i, l in enumerate(layers):
            is_target = (i == next_index)
            l.setItemVisibilityChecked(is_target)
            if is_target:
                current_layer_name = l.name()

        self.iface.messageBar().pushMessage(tr("切换成功", "Layer switched"), tr(f"当前显示: {current_layer_name}", f"Now showing: {current_layer_name}"), level=Qgis.Success,
                                            duration=1)