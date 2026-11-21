# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QShortcut
from qgis.core import QgsProject, QgsField, QgsFeatureRequest

from base_addon import BaseAddon

class QaqcAddon(BaseAddon):
    title = tr("✅ 属性审查", "✅ Attribute Review")
    order = 4

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.qaqc_shortcut = None
        self.qaqc_target_layer = None

    def unload(self):
        if self.qaqc_shortcut:
            self.qaqc_shortcut.setEnabled(False)
            self.qaqc_shortcut.deleteLater()
            self.qaqc_shortcut = None

    def setup_ui(self, parent_widget):
        layout = QVBoxLayout(parent_widget)

        layer_top_layout = QHBoxLayout()
        layer_top_layout.addWidget(QLabel(tr("<b>1. 选择目标图层:</b>", "<b>1. Select target layer:</b>")))
        self.qaqc_refresh_btn = QPushButton(tr("🔄 刷新列表", "🔄 Refresh list"))
        self.qaqc_refresh_btn.clicked.connect(self.qaqc_populate_layers)
        layer_top_layout.addWidget(self.qaqc_refresh_btn)
        layout.addLayout(layer_top_layout)

        self.qaqc_layer_combo = QComboBox()
        self.qaqc_populate_layers()
        layout.addWidget(self.qaqc_layer_combo)

        self.qaqc_init_btn = QPushButton(tr("2. 初始化 (自动创建 QA_Status 字段)", "2. Initialize (auto-create QA_Status field)"))
        self.qaqc_init_btn.setStyleSheet("background-color: #f0f0f0; font-weight: bold;")
        self.qaqc_init_btn.clicked.connect(self.qaqc_init_layer)
        layout.addWidget(self.qaqc_init_btn)

        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel(tr("<b>3. 触发快捷键:</b>", "<b>3. Trigger hotkey:</b>")))
        self.qaqc_key_combo = QComboBox()
        self.qaqc_key_combo.addItems(["F4", "F5", "Space", "F8"])
        key_layout.addWidget(self.qaqc_key_combo)
        layout.addLayout(key_layout)

        self.qaqc_start_btn = QPushButton(tr("4. 启动审查任务", "4. Start review task"))
        self.qaqc_start_btn.setCheckable(True)
        self.qaqc_start_btn.setStyleSheet("background-color: #e6f3ff; font-weight: bold; height: 35px;")
        self.qaqc_start_btn.clicked.connect(self.qaqc_toggle_shortcut)
        layout.addWidget(self.qaqc_start_btn)

        self.qaqc_status_label = QLabel(tr("当前状态: 未启动", "Status: not started"))
        self.qaqc_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.qaqc_status_label)
        layout.addStretch()

    def qaqc_populate_layers(self):
        current_id = self.qaqc_layer_combo.currentData()
        self.qaqc_layer_combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == 0:
                status = tr(" [编辑中]", " [Editing]") if layer.isEditable() else ""
                self.qaqc_layer_combo.addItem(layer.name() + status, layer.id())
        if current_id:
            idx = self.qaqc_layer_combo.findData(current_id)
            if idx != -1:
                self.qaqc_layer_combo.setCurrentIndex(idx)

    def qaqc_init_layer(self):
        layer_id = self.qaqc_layer_combo.currentData()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer.fields().indexOf("QA_Status") == -1:
            layer.dataProvider().addAttributes([QgsField("QA_Status", QVariant.Int)])
            layer.updateFields()
            self.iface.messageBar().pushMessage(tr("操作成功", "Success"), tr("已在图层中创建 QA_Status 字段。", "QA_Status field created in the layer."), level=0)
        else:
            self.iface.messageBar().pushMessage(tr("系统提示", "Notice"), tr("状态字段 QA_Status 已存在，无需重复创建。", "The QA_Status field already exists; no need to create it again."), level=0)

    def qaqc_toggle_shortcut(self, checked):
        if checked:
            layer_id = self.qaqc_layer_combo.currentData()
            self.qaqc_target_layer = QgsProject.instance().mapLayer(layer_id)
            if not self.qaqc_target_layer or not self.qaqc_target_layer.isEditable():
                self.iface.messageBar().pushMessage(tr("警告", "Warning"), tr("目标图层未开启编辑模式，请先开启！", "The target layer is not in edit mode. Enable editing first."), level=2)
                self.qaqc_start_btn.setChecked(False)
                return
            key = self.qaqc_key_combo.currentText()
            self.qaqc_shortcut = QShortcut(QKeySequence(key), self.iface.mainWindow())
            self.qaqc_shortcut.activated.connect(self.qaqc_run_logic)
            self.qaqc_start_btn.setText(tr("⏹ 停止审查任务", "⏹ Stop review task"))
            self.qaqc_start_btn.setStyleSheet("background-color: #ffe6e6; font-weight: bold; height: 35px;")
            self.qaqc_status_label.setText(tr(f"当前状态: 运行中 (监听快捷键: {key})", f"Status: running (hotkey: {key})"))
            self.qaqc_status_label.setStyleSheet("color: #0066cc; font-weight: bold;")
            self.qaqc_layer_combo.setEnabled(False)
            self.qaqc_refresh_btn.setEnabled(False)
            self.qaqc_key_combo.setEnabled(False)
        else:
            if self.qaqc_shortcut:
                self.qaqc_shortcut.setEnabled(False)
                self.qaqc_shortcut.deleteLater()
                self.qaqc_shortcut = None
            self.qaqc_start_btn.setText(tr("4. 启动审查任务", "4. Start review task"))
            self.qaqc_start_btn.setStyleSheet("background-color: #e6f3ff; font-weight: bold; height: 35px;")
            self.qaqc_status_label.setText(tr("当前状态: 未启动", "Status: not started"))
            self.qaqc_status_label.setStyleSheet("color: black;")
            self.qaqc_layer_combo.setEnabled(True)
            self.qaqc_refresh_btn.setEnabled(True)
            self.qaqc_key_combo.setEnabled(True)
            self.qaqc_populate_layers()

    def qaqc_run_logic(self):
        layer = self.qaqc_target_layer
        if not layer or not layer.isEditable():
            self.iface.messageBar().pushMessage(tr("警告", "Warning"), tr("目标图层已退出编辑模式，任务中止。", "The target layer left edit mode. Task aborted."), level=2)
            self.qaqc_start_btn.click()
            return

        selected_ids = layer.selectedFeatureIds()
        if not selected_ids:
            self.qaqc_jump_to_next(layer)
            return

        field_idx = layer.fields().indexOf('QA_Status')
        if field_idx == -1:
            self.iface.messageBar().pushMessage(tr("错误", "Error"), tr("未找到 QA_Status 字段，请先执行初始化。", "QA_Status field not found. Run initialization first."), level=2)
            return

        layer.beginEditCommand("Update QA Status")
        for fid in selected_ids:
            layer.changeAttributeValue(fid, field_idx, 1)
        layer.endEditCommand()
        layer.removeSelection()
        self.qaqc_jump_to_next(layer)

    def qaqc_jump_to_next(self, layer):
        request = QgsFeatureRequest().setFilterExpression('"QA_Status" IS NULL')
        request.setLimit(1)
        next_features = list(layer.getFeatures(request))
        if next_features:
            layer.select(next_features[0].id())
            self.iface.mapCanvas().zoomToSelected()
        else:
            self.iface.messageBar().pushMessage(tr("任务完成", "Task complete"), tr("当前图层所有要素已审查完毕。", "All features in the current layer have been reviewed."), level=0)