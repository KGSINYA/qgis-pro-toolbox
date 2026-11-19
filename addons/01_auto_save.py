# -*- coding: utf-8 -*-
import os
import shutil
import datetime

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                                 QFileDialog, QSpinBox, QMessageBox, QLineEdit,
                                 QFrame, QListWidget, QListWidgetItem, QAbstractItemView)
from qgis.core import QgsProject, QgsVectorFileWriter, QgsMapLayer, Qgis

from base_addon import BaseAddon

class AutoSaveAddon(BaseAddon):
    title = "💾 自动存档"
    order = 1

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.timer = QTimer()
        self.timer.timeout.connect(self.execute_save)
        self.save_history = []
        self.save_folder = ""

    def unload(self):
        if self.timer.isActive():
            self.timer.stop()

    def setup_ui(self, parent_widget):
        layout = QVBoxLayout(parent_widget)

        btn_folder = QPushButton("📁 选择存档路径")
        btn_folder.clicked.connect(self.choose_folder)

        self.txt_folder = QLineEdit()
        self.txt_folder.setReadOnly(True)
        self.txt_folder.setPlaceholderText("尚未选择存档文件夹...")
        self.txt_folder.setStyleSheet(
            "background-color: #f5f5f5; color: #555; border: 1px solid #ccc; border-radius: 3px;")

        layout_interval = QHBoxLayout()
        layout_interval.addWidget(QLabel("每"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 120)
        self.spin_interval.setValue(10)
        self.spin_interval.setFixedWidth(60)
        layout_interval.addWidget(self.spin_interval)
        layout_interval.addWidget(QLabel("分钟存一次"))
        layout_interval.addStretch()

        layout_max = QHBoxLayout()
        layout_max.addWidget(QLabel("最多保留"))
        self.spin_max_saves = QSpinBox()
        self.spin_max_saves.setRange(1, 50)
        self.spin_max_saves.setValue(5)
        self.spin_max_saves.setFixedWidth(60)
        layout_max.addWidget(self.spin_max_saves)
        layout_max.addWidget(QLabel("个文件"))
        layout_max.addStretch()

        self.btn_toggle = QPushButton("▶ 开启守护")
        self.btn_toggle.setMinimumHeight(40)
        self.btn_toggle.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_toggle.clicked.connect(self.toggle_timer)

        layout.addWidget(btn_folder)
        layout.addWidget(self.txt_folder)
        layout.addSpacing(10)
        layout.addLayout(layout_interval)
        layout.addLayout(layout_max)
        layout.addSpacing(10)
        layout.addWidget(self.btn_toggle)

        self.btn_restore = QPushButton("⏪ 紧急回退到上一存档")
        self.btn_restore.setMinimumHeight(35)
        self.btn_restore.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold;")
        self.btn_restore.clicked.connect(self.restore_save)
        layout.addWidget(self.btn_restore)

        # --- 分割线 ---
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setContentsMargins(0, 5, 0, 5)
        layout.addWidget(line)

        # --- 批量导出功能 UI ---
        layout.addWidget(QLabel("<b>📦 批量数据导出 (Shapefile)</b>"))

        btn_layout = QHBoxLayout()
        self.btn_get_selected = QPushButton("📥 获取选中图层")
        self.btn_get_selected.clicked.connect(self.populate_selected_layers)

        self.btn_get_memory = QPushButton("📝 获取临时图层")
        self.btn_get_memory.clicked.connect(self.populate_memory_layers)

        btn_layout.addWidget(self.btn_get_selected)
        btn_layout.addWidget(self.btn_get_memory)
        layout.addLayout(btn_layout)

        self.export_list = QListWidget()
        self.export_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.export_list.setFixedHeight(100)
        layout.addWidget(self.export_list)

        self.btn_do_export = QPushButton("🚀 执行批量导出")
        self.btn_do_export.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold; height: 35px;")
        self.btn_do_export.clicked.connect(self.execute_batch_export)
        layout.addWidget(self.btn_do_export)

        layout.addStretch()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self.dock_widget, "选择存档路径")
        if folder:
            self.save_folder = folder
            self.txt_folder.setText(self.save_folder)
            self.txt_folder.setToolTip(f"完整路径:\n{self.save_folder}")
            self.txt_folder.setCursorPosition(len(self.save_folder))

    def toggle_timer(self):
        if not self.save_folder:
            QMessageBox.warning(self.dock_widget, "警告", "请先选择存档文件夹！")
            return

        if self.timer.isActive():
            self.timer.stop()
            self.btn_toggle.setText("▶ 开启守护")
            self.btn_toggle.setStyleSheet("background-color: #4CAF50; color: white;")
        else:
            self.timer.start(self.spin_interval.value() * 60 * 1000)
            self.btn_toggle.setText("⏹ 停止守护")
            self.btn_toggle.setStyleSheet("background-color: #f44336; color: white;")

    def execute_save(self):
        if not self.save_folder:
            return

        layers = QgsProject.instance().mapLayers().values()
        editing_layers = [lyr for lyr in layers if lyr.type() == QgsMapLayer.VectorLayer and lyr.isEditable()]

        if not editing_layers:
            return

        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir_name = f"Backup_{now_str}"
        current_backup_path = os.path.join(self.save_folder, backup_dir_name)

        try:
            os.makedirs(current_backup_path, exist_ok=True)
        except Exception:
            return

        for layer in editing_layers:
            safe_layer_name = "".join(c for c in layer.name() if c.isalnum() or c in (' ', '.', '_')).rstrip()
            file_name = f"{safe_layer_name}.gpkg"
            save_path = os.path.join(current_backup_path, file_name)

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer.name()
            context = QgsProject.instance().transformContext()

            QgsVectorFileWriter.writeAsVectorFormatV2(layer, save_path, context, options)

        self.save_history.append(current_backup_path)

        while len(self.save_history) > self.spin_max_saves.value():
            old_dir = self.save_history.pop(0)
            if os.path.exists(old_dir):
                try:
                    shutil.rmtree(old_dir)
                except Exception:
                    pass

        self.iface.statusBarIface().showMessage(f"已自动备份 {len(editing_layers)} 个编辑中图层", 3000)

    def restore_save(self):
        if not self.save_history:
            QMessageBox.warning(self.dock_widget, "警告", "当前没有任何可用的存档记录！")
            return

        last_backup_dir = self.save_history[-1]

        if not os.path.exists(last_backup_dir):
            QMessageBox.warning(self.dock_widget, "错误", "最近的存档文件夹已丢失！")
            return

        reply = QMessageBox.question(self.dock_widget, "确认回溯",
                                     f"将加载上一存档文件夹中的所有图层: \n{os.path.basename(last_backup_dir)}\n确认执行？",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            loaded_count = 0
            for file_name in os.listdir(last_backup_dir):
                if file_name.endswith(".gpkg"):
                    file_path = os.path.join(last_backup_dir, file_name)
                    layer_name = f"回溯_{file_name.replace('.gpkg', '')}"
                    layer = self.iface.addVectorLayer(file_path, layer_name, "ogr")
                    if layer:
                        loaded_count += 1

            if loaded_count > 0:
                self.iface.messageBar().pushMessage("回溯成功", f"已成功加载 {loaded_count} 个历史图层",
                                                    level=Qgis.Success, duration=5)
            else:
                self.iface.messageBar().pushMessage("回溯失败", "存档文件夹中没有找到有效数据", level=Qgis.Warning,
                                                    duration=3)

    def populate_selected_layers(self):
        """获取用户在 QGIS 图层树中选中的图层"""
        self.export_list.clear()
        selected_layers = self.iface.layerTreeView().selectedLayers()
        for layer in selected_layers:
            if layer.type() == QgsMapLayer.VectorLayer:
                item = QListWidgetItem(f"📄 {layer.name()}")
                item.setData(Qt.UserRole, layer.id())
                self.export_list.addItem(item)
        if self.export_list.count() == 0:
            self.iface.messageBar().pushMessage("提示", "未在图层树中选中任何矢量图层", level=1, duration=2)

    def populate_memory_layers(self):
        """获取所有临时图层"""
        self.export_list.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == QgsMapLayer.VectorLayer and layer.dataProvider().name() == 'memory':
                item = QListWidgetItem(f"📝 {layer.name()} [临时]")
                item.setData(Qt.UserRole, layer.id())
                self.export_list.addItem(item)
        if self.export_list.count() == 0:
            self.iface.messageBar().pushMessage("提示", "当前项目中没有找到临时图层", level=1, duration=2)

    def execute_batch_export(self):
        """执行导出逻辑"""
        if self.export_list.count() == 0:
            self.iface.messageBar().pushMessage("提示", "导出列表为空，请先点击获取图层按钮", level=1)
            return

        export_dir = QFileDialog.getExistingDirectory(self.dock_widget, "选择导出文件夹")
        if not export_dir:
            return

        success_count = 0
        error_count = 0

        for i in range(self.export_list.count()):
            item = self.export_list.item(i)
            layer_id = item.data(Qt.UserRole)
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                safe_name = "".join(c for c in layer.name() if c not in r'\/:*?"<>|')
                path = os.path.join(export_dir, f"{safe_name}.shp")
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "ESRI Shapefile"
                options.fileEncoding = "UTF-8"

                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, path, QgsProject.instance().transformContext(), options
                )

                error_code = result[0] if isinstance(result, tuple) else result

                if error_code == QgsVectorFileWriter.NoError:
                    success_count += 1
                else:
                    error_count += 1

        self.export_list.clear()

        if error_count == 0:
            self.iface.messageBar().pushMessage("导出成功", f"成功导出 {success_count} 个图层至: {export_dir}", level=0,
                                                duration=5)
        else:
            self.iface.messageBar().pushMessage("完成", f"成功: {success_count} 个，失败: {error_count} 个", level=1,
                                                duration=5)