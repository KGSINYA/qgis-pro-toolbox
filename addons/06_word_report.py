# -*- coding: utf-8 -*-
import os
import sys
import shutil
import zipfile

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                                 QLabel, QFileDialog, QSpinBox, QMessageBox,
                                 QComboBox, QLineEdit, QTableWidget,
                                 QTableWidgetItem, QHeaderView, QStackedWidget,
                                 QGroupBox)
from qgis.core import QgsProject, QgsMapLayer, Qgis

from base_addon import BaseAddon

# 全局变量占位
Document = None
Cm = None
Inches = None
WD_TABLE_ALIGNMENT = None

def load_docx_from_libs(plugin_dir):
    """
    【内网离线免安装引擎】
    自动扫描插件目录下的 libs 文件夹，将里面的 .whl 文件自动解压并挂载到 Python 路径中。
    无需 OSGeo4W Shell，无需 pip，无需联网！
    """
    global Document, Cm, Inches, WD_TABLE_ALIGNMENT
    if Document is not None:
        return True, ""

    libs_dir = os.path.join(plugin_dir, "libs")
    os.makedirs(libs_dir, exist_ok=True)

    # 1. 自动将 libs 目录下的所有 .whl 文件原地解压（.whl 本质就是 zip 压缩包）
    for fname in os.listdir(libs_dir):
        if fname.lower().endswith(".whl"):
            whl_path = os.path.join(libs_dir, fname)
            stamp_file = whl_path + ".unpacked"
            if not os.path.exists(stamp_file):
                try:
                    with zipfile.ZipFile(whl_path, 'r') as zf:
                        zf.extractall(libs_dir)
                    with open(stamp_file, 'w', encoding='utf-8') as f:
                        f.write("ok")
                except Exception as e:
                    print(f"[WordReport] 自动解压 {fname} 失败: {e}")

    # 2. 将 libs 目录加入到 Python 模块搜索路径的最前面
    if libs_dir not in sys.path:
        sys.path.insert(0, libs_dir)

    # 3. 尝试导入 python-docx
    try:
        from docx import Document as _Document
        from docx.shared import Cm as _Cm, Inches as _Inches
        from docx.enum.table import WD_TABLE_ALIGNMENT as _WD_TABLE_ALIGNMENT
        Document = _Document
        Cm = _Cm
        Inches = _Inches
        WD_TABLE_ALIGNMENT = _WD_TABLE_ALIGNMENT
        return True, ""
    except Exception as e:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        err_msg = (
            f"底层报错: {type(e).__name__}: {e}\n"
            f"当前 QGIS 内置 Python 版本: {py_ver}"
        )
        return False, err_msg

class WordReportAddon(BaseAddon):
    title = "📝 Word报表"
    order = 6

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.word_template_path = ""
        self.current_layer = None
        self.map_types = ["不填充", "矢量字段", "外部图片"]
        # 初始化时自动尝试从 libs 文件夹免安装加载
        load_docx_from_libs(self.plugin_dir)

    def setup_ui(self, parent_widget):
        main_layout = QVBoxLayout(parent_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- 区域 1: Word 模板解析 ---
        group_template = QGroupBox("1. 模板解析")
        group_template.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #dcdde1;
                border-radius: 6px;
                margin-top: 8px;
                background-color: #fafbfc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #2f3640;
            }
        """)
        layout_template = QVBoxLayout(group_template)

        btn_word = QPushButton("📂 选择 Word 模板并提取表头")
        btn_word.setMinimumHeight(36)
        btn_word.setStyleSheet("""
            QPushButton {
                background-color: #0984e3;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #74b9ff;
            }
            QPushButton:pressed {
                background-color: #0984e3;
            }
        """)
        btn_word.clicked.connect(self.word_load_template)
        layout_template.addWidget(btn_word)

        self.lbl_word_path = QLabel("当前未选择模板文件")
        self.lbl_word_path.setStyleSheet("color: #718093; font-size: 11px; margin-top: 2px;")
        self.lbl_word_path.setWordWrap(True)
        layout_template.addWidget(self.lbl_word_path)

        main_layout.addWidget(group_template)

        # --- 区域 2: 动态映射表 ---
        group_mapping = QGroupBox("2. 动态表格列映射配置")
        group_mapping.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #dcdde1;
                border-radius: 6px;
                margin-top: 8px;
                background-color: #fafbfc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #2f3640;
            }
        """)
        layout_mapping = QVBoxLayout(group_mapping)

        # === 新增：刷新图层按钮 ===
        self.btn_refresh_layers = QPushButton("🔄 刷新 QGIS 图层与字段")
        self.btn_refresh_layers.setStyleSheet("""
            QPushButton {
                background-color: #f1f2f6;
                color: #2f3640;
                border: 1px solid #dcdde1;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #dfe6e9; }
        """)
        self.btn_refresh_layers.clicked.connect(self.word_refresh_layers)
        layout_mapping.addWidget(self.btn_refresh_layers, 0, Qt.AlignRight)  # 靠右对齐，更美观
        # ==========================

        self.word_table_config = QTableWidget(0, 3)
        self.word_table_config.setHorizontalHeaderLabels(["Word 表头", "填充类型", "数据源与详细配置"])

        self.word_table_config.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.word_table_config.setColumnWidth(1, 120)
        self.word_table_config.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.word_table_config.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        self.word_table_config.setSelectionMode(QTableWidget.NoSelection)
        self.word_table_config.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid #dfe6e9;
                gridline-color: #f1f2f6;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #f1f2f6;
                color: #2f3640;
                padding: 6px;
                border: none;
                font-weight: bold;
            }
        """)
        layout_mapping.addWidget(self.word_table_config)

        main_layout.addWidget(group_mapping)

        # --- 区域 3: 执行按钮 ---
        self.btn_run_word = QPushButton("🪄 一键生成专业 Word 报表")
        self.btn_run_word.setMinimumHeight(42)
        self.btn_run_word.setStyleSheet("""
            QPushButton {
                background-color: #00b894;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #55efc4;
                color: #2d3436;
            }
            QPushButton:pressed {
                background-color: #00b894;
            }
        """)
        self.btn_run_word.clicked.connect(self.word_generate_report)
        main_layout.addWidget(self.btn_run_word)

    def check_and_install_whl(self):
        """如果未检测到 python-docx，引导用户直接选择存放那 3 个 .whl 的文件夹自动装配"""
        ok, err_detail = load_docx_from_libs(self.plugin_dir)
        if ok:
            return True

        reply = QMessageBox.question(
            self.dock_widget,
            "缺少 Word 报表组件 (支持一键离线导入)",
            f"当前环境尚未加载 python-docx 库！\n({err_detail})\n\n"
            "💡 您无需打开 OSGeo4W Shell 敲命令行！\n"
            "点击【Yes】直接选择您电脑上存放那 3 个 .whl 离线包（lxml、python_docx、typing_extensions）的文件夹，"
            "插件将自动为您完成内置挂载！",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            whl_dir = QFileDialog.getExistingDirectory(self.dock_widget, "选择存放 3 个 .whl 文件的文件夹")
            if whl_dir:
                libs_dir = os.path.join(self.plugin_dir, "libs")
                os.makedirs(libs_dir, exist_ok=True)
                copied_count = 0
                for fname in os.listdir(whl_dir):
                    if fname.lower().endswith(".whl"):
                        shutil.copy2(os.path.join(whl_dir, fname), os.path.join(libs_dir, fname))
                        copied_count += 1

                if copied_count == 0:
                    QMessageBox.warning(self.dock_widget, "未找到文件", "您选择的文件夹中没有找到任何 .whl 文件！")
                    return False

                # 清理之前可能失败的半加载模块缓存，重新挂载
                for mod_name in list(sys.modules.keys()):
                    if mod_name.startswith(('docx', 'lxml', 'typing_extensions')):
                        sys.modules.pop(mod_name, None)

                ok2, err2 = load_docx_from_libs(self.plugin_dir)
                if ok2:
                    self.iface.messageBar().pushMessage(
                        "离线装配成功", f"已成功内置挂载 {copied_count} 个 .whl 离线包，现在可以直接使用了！",
                        level=Qgis.Success, duration=4
                    )
                    return True
                else:
                    QMessageBox.critical(
                        self.dock_widget, "装配失败",
                        f"已复制 .whl 文件但加载仍然失败：\n{err2}\n\n"
                        "请检查 lxml 的 cp 版本号是否与当前 QGIS 的 Python 版本一致（例如 cp312 仅限 Python 3.12 使用）。"
                    )
        return False

    def word_browse_folder(self, line_edit):
        path = QFileDialog.getExistingDirectory(self.dock_widget, "选择图片所在文件夹")
        if path:
            line_edit.setText(path)

    def word_load_template(self):
        if Document is None:
            if not self.check_and_install_whl():
                return

        path, _ = QFileDialog.getOpenFileName(self.dock_widget, "选择Word模板", "", "Word (*.docx)")
        if not path:
            return

        try:
            doc = Document(path)
            if len(doc.tables) == 0:
                QMessageBox.warning(self.dock_widget, "错误", "该 Word 文档中没有找到表格！")
                return

            table = doc.tables[0]
            headers = [cell.text.strip() for cell in table.rows[0].cells]

            self.word_template_path = path
            self.lbl_word_path.setText(f"已加载: {os.path.basename(path)}")
            self.word_table_config.setRowCount(0)

            layers = [layer for layer in QgsProject.instance().mapLayers().values() if
                      layer.type() == QgsMapLayer.VectorLayer]

            combo_style = """
                QComboBox {
                    background-color: #f7f9fa;
                    color: #2f3640;
                    border: 1px solid #b2bec3;
                    border-radius: 4px;
                    padding: 4px 6px;
                    min-height: 20px;
                }
                QComboBox:hover {
                    border: 1px solid #0984e3;
                    background-color: #ffffff;
                }
            """

            for i, header_text in enumerate(headers):
                row = self.word_table_config.rowCount()
                self.word_table_config.insertRow(row)

                # 第 0 列: 表头名称
                item_header = QTableWidgetItem(f"列 {i + 1}: {header_text}")
                item_header.setFlags(item_header.flags() & ~Qt.ItemIsEditable)
                item_header.setData(Qt.UserRole, i)
                self.word_table_config.setItem(row, 0, item_header)

                # 第 1 列: 类型选择
                combo_type = QComboBox()
                combo_type.addItems(self.map_types)
                combo_type.setStyleSheet(combo_style)
                self.word_table_config.setCellWidget(row, 1, combo_type)

                # 第 2 列: 动态堆叠面板
                stack = QStackedWidget()

                # 状态 0: 不填充
                lbl_none = QLabel("  - 无需配置 -")
                lbl_none.setStyleSheet("color: #b2bec3; font-style: italic;")
                stack.addWidget(lbl_none)

                # 状态 1: 矢量字段 (独立图层 + 字段)
                w_field_widget = QWidget()
                w_field_layout = QHBoxLayout(w_field_widget)
                w_field_layout.setContentsMargins(2, 2, 2, 2)

                combo_layer_sub = QComboBox()
                combo_layer_sub.setObjectName("layer_combo")
                combo_layer_sub.setStyleSheet(combo_style)
                for lyr in layers:
                    combo_layer_sub.addItem(lyr.name(), lyr.id())

                combo_field_sub = QComboBox()
                combo_field_sub.setObjectName("field_combo")
                combo_field_sub.setStyleSheet(combo_style)

                def on_sub_layer_changed(idx, c_lyr=combo_layer_sub, c_fld=combo_field_sub):
                    c_fld.clear()
                    l_id = c_lyr.currentData()
                    if l_id:
                        lyr_obj = QgsProject.instance().mapLayer(l_id)
                        if lyr_obj:
                            c_fld.addItems([f.name() for f in lyr_obj.fields()])

                combo_layer_sub.currentIndexChanged.connect(on_sub_layer_changed)
                on_sub_layer_changed(0)

                w_field_layout.addWidget(combo_layer_sub, 1)
                w_field_layout.addWidget(combo_field_sub, 1)
                stack.addWidget(w_field_widget)

                # 状态 2: 外部图片 (双行自适应布局)
                w_img_widget = QWidget()
                w_img_layout = QVBoxLayout(w_img_widget)
                w_img_layout.setContentsMargins(2, 2, 2, 2)
                w_img_layout.setSpacing(4)

                # 第一行：图层与字段选择
                top_img_layout = QHBoxLayout()
                top_img_layout.setContentsMargins(0, 0, 0, 0)
                top_img_layout.setSpacing(4)
                combo_img_layer = QComboBox()
                combo_img_layer.setObjectName("img_layer_combo")
                combo_img_layer.setStyleSheet(combo_style)
                for lyr in layers:
                    combo_img_layer.addItem(lyr.name(), lyr.id())

                combo_img_field = QComboBox()
                combo_img_field.setObjectName("img_field_combo")
                combo_img_field.setStyleSheet(combo_style)

                def on_img_sub_layer_changed(idx, c_lyr=combo_img_layer, c_fld=combo_img_field):
                    c_fld.clear()
                    l_id = c_lyr.currentData()
                    if l_id:
                        lyr_obj = QgsProject.instance().mapLayer(l_id)
                        if lyr_obj:
                            c_fld.addItems([f.name() for f in lyr_obj.fields()])

                combo_img_layer.currentIndexChanged.connect(on_img_sub_layer_changed)
                on_img_sub_layer_changed(0)

                top_img_layout.addWidget(combo_img_layer, 1)
                top_img_layout.addWidget(combo_img_field, 1)

                # 第二行：文件夹路径 + 浏览按钮 + 图片宽度调整
                bottom_img_layout = QHBoxLayout()
                bottom_img_layout.setContentsMargins(0, 0, 0, 0)
                bottom_img_layout.setSpacing(4)

                line_folder = QLineEdit()
                line_folder.setPlaceholderText("选择图片文件夹路径...")
                line_folder.setObjectName("folder_input")
                line_folder.setStyleSheet(
                    "padding: 4px 6px; border: 1px solid #b2bec3; border-radius: 4px; background: white; color: #2f3640;")

                btn_folder = QPushButton("📁")
                btn_folder.setFixedWidth(28)
                btn_folder.setStyleSheet("padding: 4px; background: #dfe6e9; border-radius: 4px; font-weight: bold;")
                btn_folder.clicked.connect(lambda checked, le=line_folder: self.word_browse_folder(le))

                spin_width = QSpinBox()
                spin_width.setObjectName("width_spin")
                spin_width.setRange(1, 20)
                spin_width.setValue(4)
                spin_width.setSuffix(" cm")
                spin_width.setStyleSheet(
                    "padding: 3px; border: 1px solid #b2bec3; border-radius: 4px; background: white; color: #2f3640;")

                bottom_img_layout.addWidget(line_folder, 3)
                bottom_img_layout.addWidget(btn_folder)
                bottom_img_layout.addWidget(QLabel("宽度:"))
                bottom_img_layout.addWidget(spin_width)

                w_img_layout.addLayout(top_img_layout)
                w_img_layout.addLayout(bottom_img_layout)

                stack.addWidget(w_img_widget)

                self.word_table_config.setCellWidget(row, 2, stack)

                def on_type_changed(idx, s=stack, r_idx=row):
                    s.setCurrentIndex(idx)
                    self.word_table_config.resizeRowToContents(r_idx)

                combo_type.currentIndexChanged.connect(on_type_changed)
                on_type_changed(0)

            self.word_table_config.resizeRowsToContents()

        except Exception as e:
            QMessageBox.critical(self.dock_widget, "解析错误", f"无法读取模板: {str(e)}")

    def word_generate_report(self):
        if not hasattr(self, 'word_template_path') or not self.word_template_path:
            QMessageBox.warning(self.dock_widget, "提示", "请先加载并选择 Word 模板！")
            return

        save_path, _ = QFileDialog.getSaveFileName(self.dock_widget, "保存报表", "", "Word (*.docx)")
        if not save_path:
            return

        try:
            doc = Document(self.word_template_path)
            if not doc.tables:
                QMessageBox.warning(self.dock_widget, "错误", "Word 模板中没有表格！")
                return
            table = doc.tables[0]

            while len(table.rows) > 1:
                row_to_del = table.rows[-1]._element
                row_to_del.getparent().remove(row_to_del)

            main_layer = None
            for config_row in range(self.word_table_config.rowCount()):
                type_idx = self.word_table_config.cellWidget(config_row, 1).currentIndex()
                if type_idx == 1:
                    stack = self.word_table_config.cellWidget(config_row, 2)
                    sub_w = stack.widget(1)
                    c_lyr = sub_w.findChild(QComboBox, "layer_combo") if sub_w else None
                    if c_lyr and c_lyr.currentData():
                        main_layer = QgsProject.instance().mapLayer(c_lyr.currentData())
                        break

            if not main_layer:
                QMessageBox.warning(self.dock_widget, "提示", "请至少在一列中配置一个有效的“矢量字段”作为数据循环基准！")
                return

            features = list(main_layer.getFeatures())

            for feat in features:
                new_row = table.add_row()

                for config_row in range(self.word_table_config.rowCount()):
                    header_item = self.word_table_config.item(config_row, 0)
                    if not header_item:
                        continue
                    col_idx = header_item.data(Qt.UserRole)

                    type_idx = self.word_table_config.cellWidget(config_row, 1).currentIndex()
                    stack = self.word_table_config.cellWidget(config_row, 2)

                    if col_idx >= len(new_row.cells) or type_idx == 0:
                        continue

                    cell = new_row.cells[col_idx]
                    if cell.paragraphs:
                        cell.paragraphs[0].paragraph_format.alignment = WD_TABLE_ALIGNMENT.CENTER

                    if type_idx == 1:
                        sub_w = stack.widget(1)
                        c_lyr = sub_w.findChild(QComboBox, "layer_combo") if sub_w else None
                        c_fld = sub_w.findChild(QComboBox, "field_combo") if sub_w else None

                        if c_lyr and c_fld:
                            target_field = c_fld.currentText()
                            target_lyr_id = c_lyr.currentData()
                            target_lyr = QgsProject.instance().mapLayer(target_lyr_id) if target_lyr_id else main_layer

                            if target_lyr == main_layer:
                                val = feat[target_field] if target_field in feat.fields().names() else ""
                                cell.text = str(val) if val is not None else ""
                            else:
                                cell.text = "[跨图层字段]"

                    elif type_idx == 2:
                        sub_w = stack.widget(2)
                        c_lyr = sub_w.findChild(QComboBox, "img_layer_combo") if sub_w else None
                        c_fld = sub_w.findChild(QComboBox, "img_field_combo") if sub_w else None
                        line_folder = sub_w.findChild(QLineEdit, "folder_input") if sub_w else None
                        spin_w = sub_w.findChild(QSpinBox, "width_spin") if sub_w else None

                        img_dir = line_folder.text().strip() if line_folder else ""
                        img_width_cm = spin_w.value() if spin_w else 4

                        if not img_dir or not os.path.exists(img_dir):
                            cell.text = "文件夹无效"
                            continue

                        img_match_name = ""
                        if c_lyr and c_fld:
                            img_lyr_id = c_lyr.currentData()
                            img_fld_name = c_fld.currentText()
                            img_lyr = QgsProject.instance().mapLayer(img_lyr_id) if img_lyr_id else main_layer

                            if img_lyr == main_layer:
                                img_match_name = str(
                                    feat[img_fld_name]) if img_fld_name in feat.fields().names() else ""
                            else:
                                img_match_name = ""

                        if not img_match_name:
                            continue

                        img_path = ""
                        for ext in ['.jpg', '.png', '.jpeg', '.JPG', '.PNG']:
                            tmp = os.path.join(img_dir, img_match_name + ext)
                            if os.path.exists(tmp):
                                img_path = tmp
                                break

                        if img_path:
                            cell.text = ""
                            run = cell.paragraphs[0].add_run()
                            run.add_picture(img_path, width=Cm(img_width_cm))
                            cell.paragraphs[0].alignment = WD_TABLE_ALIGNMENT.CENTER
                        else:
                            cell.text = "无图片"

            doc.save(save_path)
            QMessageBox.information(self.dock_widget, "成功", f"专业版 Word 报表已生成！共导出 {len(features)} 条记录。")

        except Exception as e:
            QMessageBox.critical(self.dock_widget, "生成失败", f"错误详情: {str(e)}")

            def word_refresh_layers(self):
                """动态刷新下拉框中的图层和字段列表"""
                # 1. 重新获取 QGIS 中最新的矢量图层
                layers = [layer for layer in QgsProject.instance().mapLayers().values() if
                          layer.type() == QgsMapLayer.VectorLayer]

                if self.word_table_config.rowCount() == 0:
                    QMessageBox.information(self.dock_widget, "提示",
                                            f"已检测到 {len(layers)} 个图层。请先加载 Word 模板。")
                    return

                # 2. 遍历当前表格的所有行，更新里面的下拉框
                for row in range(self.word_table_config.rowCount()):
                    stack = self.word_table_config.cellWidget(row, 2)
                    if not stack:
                        continue

                    # --- 更新状态 1 (矢量字段) 的图层下拉框 ---
                    sub_w_field = stack.widget(1)
                    c_lyr_field = sub_w_field.findChild(QComboBox, "layer_combo") if sub_w_field else None
                    if c_lyr_field:
                        current_id = c_lyr_field.currentData()  # 记住刷新前选中的图层 ID
                        c_lyr_field.blockSignals(True)  # 暂时屏蔽信号，防止清空时引发报错
                        c_lyr_field.clear()
                        for lyr in layers:
                            c_lyr_field.addItem(lyr.name(), lyr.id())

                        # 如果之前选的图层还在，就恢复选中状态
                        idx = c_lyr_field.findData(current_id)
                        if idx >= 0:
                            c_lyr_field.setCurrentIndex(idx)
                        c_lyr_field.blockSignals(False)  # 恢复信号
                        # 手动触发一次信号，让它连带把“字段下拉框”也刷新了
                        c_lyr_field.currentIndexChanged.emit(c_lyr_field.currentIndex())

                    # --- 更新状态 2 (外部图片) 的图层下拉框 ---
                    sub_w_img = stack.widget(2)
                    c_lyr_img = sub_w_img.findChild(QComboBox, "img_layer_combo") if sub_w_img else None
                    if c_lyr_img:
                        current_id = c_lyr_img.currentData()
                        c_lyr_img.blockSignals(True)
                        c_lyr_img.clear()
                        for lyr in layers:
                            c_lyr_img.addItem(lyr.name(), lyr.id())

                        idx = c_lyr_img.findData(current_id)
                        if idx >= 0:
                            c_lyr_img.setCurrentIndex(idx)
                        c_lyr_img.blockSignals(False)
                        c_lyr_img.currentIndexChanged.emit(c_lyr_img.currentIndex())

                QMessageBox.information(self.dock_widget, "刷新成功",
                                        f"已同步最新数据，当前共有 {len(layers)} 个矢量图层可用。")

    def word_refresh_layers(self):
        """动态刷新下拉框中的图层和字段列表"""
        # 1. 重新获取 QGIS 中最新的矢量图层
        layers = [layer for layer in QgsProject.instance().mapLayers().values() if
                  layer.type() == QgsMapLayer.VectorLayer]

        if self.word_table_config.rowCount() == 0:
            QMessageBox.information(self.dock_widget, "提示", f"已检测到 {len(layers)} 个图层。请先加载 Word 模板。")
            return

        # 2. 遍历当前表格的所有行，更新里面的下拉框
        for row in range(self.word_table_config.rowCount()):
            stack = self.word_table_config.cellWidget(row, 2)
            if not stack:
                continue

            # --- 更新状态 1 (矢量字段) 的图层下拉框 ---
            sub_w_field = stack.widget(1)
            c_lyr_field = sub_w_field.findChild(QComboBox, "layer_combo") if sub_w_field else None
            if c_lyr_field:
                current_id = c_lyr_field.currentData()  # 记住刷新前选中的图层 ID
                c_lyr_field.blockSignals(True)  # 暂时屏蔽信号，防止清空时引发报错
                c_lyr_field.clear()
                for lyr in layers:
                    c_lyr_field.addItem(lyr.name(), lyr.id())

                # 如果之前选的图层还在，就恢复选中状态
                idx = c_lyr_field.findData(current_id)
                if idx >= 0:
                    c_lyr_field.setCurrentIndex(idx)
                c_lyr_field.blockSignals(False)  # 恢复信号
                # 手动触发一次信号，让它连带把“字段下拉框”也刷新了
                c_lyr_field.currentIndexChanged.emit(c_lyr_field.currentIndex())

            # --- 更新状态 2 (外部图片) 的图层下拉框 ---
            sub_w_img = stack.widget(2)
            c_lyr_img = sub_w_img.findChild(QComboBox, "img_layer_combo") if sub_w_img else None
            if c_lyr_img:
                current_id = c_lyr_img.currentData()
                c_lyr_img.blockSignals(True)
                c_lyr_img.clear()
                for lyr in layers:
                    c_lyr_img.addItem(lyr.name(), lyr.id())

                idx = c_lyr_img.findData(current_id)
                if idx >= 0:
                    c_lyr_img.setCurrentIndex(idx)
                c_lyr_img.blockSignals(False)
                c_lyr_img.currentIndexChanged.emit(c_lyr_img.currentIndex())

        QMessageBox.information(self.dock_widget, "刷新成功", f"已同步最新数据，当前共有 {len(layers)} 个矢量图层可用。")
