# -*- coding: utf-8 -*-
import os
import re
import math

# ---------- 第三方：pandas 安全导入 ----------
try:
    import pandas as pd
except ImportError:
    pd = None

from qgis.PyQt.QtCore import Qt, QVariant, QEventLoop, QSize
from qgis.PyQt.QtGui import QImage, QPainter, QColor
from qgis.PyQt.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                                 QLabel, QFileDialog, QSpinBox, QMessageBox,
                                 QComboBox, QLineEdit, QCheckBox, QGroupBox,
                                 QScrollArea, QFrame, QApplication)
from qgis.core import (QgsProject, QgsVectorFileWriter, QgsField, QgsVectorLayer,
                       QgsFeature, QgsGeometry, QgsPointXY, QgsRectangle,
                       QgsMapRendererCustomPainterJob, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsCsException, Qgis)
from qgis.gui import QgsProjectionSelectionWidget, QgsVertexMarker, QgsMapToolEmitPoint

from base_addon import BaseAddon

class ExcelMapAddon(BaseAddon):
    title = "📊 表格转点制图"
    order = 5

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.excel_df = None
        self.markers = []          # 存放图面上的十字高亮标记
        self.map_tool = None       # 图面点击取点工具
        self.prev_map_tool = None  # 记录用户原本使用的地图工具

    def unload(self):
        """模块卸载或热重载时，自动清除图面上的十字标记和取点工具"""
        self.clear_markers()
        if self.map_tool and self.iface.mapCanvas().mapTool() == self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
        self.map_tool = None

    def setup_ui(self, parent_widget):
        # 使用滚动区域包裹，防止屏幕较小时控件挤在一起
        outer_layout = QVBoxLayout(parent_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # =================================================================
        # 专区 A：新增 —— 坐标点快速定位与拾取
        # =================================================================
        group_locator = QGroupBox("📍 坐标点快速定位与图面拾取")
        group_locator.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #b2bec3;
                border-radius: 6px;
                margin-top: 8px;
                background-color: #f8fbff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #0984e3;
            }
        """)
        loc_layout = QVBoxLayout(group_locator)
        loc_layout.setSpacing(6)

        # 1. 快捷 EPSG 搜索栏
        epsg_layout = QHBoxLayout()
        epsg_layout.addWidget(QLabel("快捷EPSG:"))
        self.txt_epsg = QLineEdit()
        self.txt_epsg.setPlaceholderText("输入代码如 4326, 4490, 4547 回车...")
        self.txt_epsg.returnPressed.connect(self.apply_epsg_code)
        btn_epsg = QPushButton("🔍 应用")
        btn_epsg.setFixedWidth(60)
        btn_epsg.setToolTip("根据输入的 EPSG 编号自动匹配坐标系")
        btn_epsg.clicked.connect(self.apply_epsg_code)
        epsg_layout.addWidget(self.txt_epsg)
        epsg_layout.addWidget(btn_epsg)
        loc_layout.addLayout(epsg_layout)

        # 2. QGIS 原生坐标系选择器
        crs_layout = QHBoxLayout()
        crs_layout.addWidget(QLabel("当前坐标系:"))
        self.crs_selector = QgsProjectionSelectionWidget()
        # 默认设为 WGS84 (EPSG:4326)
        default_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        self.crs_selector.setCrs(default_crs)
        self.txt_epsg.setText("4326")
        self.crs_selector.crsChanged.connect(self.on_crs_widget_changed)
        crs_layout.addWidget(self.crs_selector, 1)
        loc_layout.addLayout(crs_layout)

        # 3. 经度(X) / 纬度(Y) 输入框（支持小数、度分秒、智能连粘）
        xy_layout = QHBoxLayout()
        self.txt_x = QLineEdit()
        self.txt_x.setPlaceholderText("经度/X (如 116.39 或 116°23'49\")")
        self.txt_x.textChanged.connect(self.on_x_smart_paste)
        self.txt_x.returnPressed.connect(self.zoom_to_coordinate)

        self.txt_y = QLineEdit()
        self.txt_y.setPlaceholderText("纬度/Y (如 39.90 或 39°54'20\")")
        self.txt_y.returnPressed.connect(self.zoom_to_coordinate)

        btn_swap = QPushButton("⇄")
        btn_swap.setFixedWidth(28)
        btn_swap.setToolTip("一键互换 X 与 Y 坐标（解决经纬度或测绘纵横坐标填反问题）")
        btn_swap.clicked.connect(self.swap_xy)

        xy_layout.addWidget(QLabel("X:"))
        xy_layout.addWidget(self.txt_x, 1)
        xy_layout.addWidget(btn_swap)
        xy_layout.addWidget(QLabel("Y:"))
        xy_layout.addWidget(self.txt_y, 1)
        loc_layout.addLayout(xy_layout)

        # 4. 辅助小工具栏：智能粘贴、复制坐标、图面取点、缩放比例
        tools_layout = QHBoxLayout()
        btn_paste = QPushButton("📋 粘贴解析")
        btn_paste.setToolTip("直接读取剪贴板中的 'X, Y' 坐标文本并自动拆分填入")
        btn_paste.clicked.connect(self.paste_from_clipboard)

        btn_copy = QPushButton("📄 复制")
        btn_copy.setToolTip("将当前输入框中的 X, Y 坐标复制到剪贴板")
        btn_copy.clicked.connect(self.copy_to_clipboard)

        self.btn_pick = QPushButton("🎯 图面取点")
        self.btn_pick.setCheckable(True)
        self.btn_pick.setToolTip("点击后在地图画布上左键单击，即可反查该点在上方所选坐标系下的坐标")
        self.btn_pick.clicked.connect(self.toggle_map_picker)

        self.scale_combo = QComboBox()
        self.scale_combo.setToolTip("跳转定位时的地图缩放比例尺")
        self.scale_combo.addItems([
            "比例尺: 1:2,000",
            "比例尺: 1:500",
            "比例尺: 1:1,000",
            "比例尺: 1:5,000",
            "比例尺: 1:10,000",
            "比例尺: 1:50,000",
            "保持当前比例尺"
        ])

        tools_layout.addWidget(btn_paste)
        tools_layout.addWidget(btn_copy)
        tools_layout.addWidget(self.btn_pick)
        tools_layout.addWidget(self.scale_combo, 1)
        loc_layout.addLayout(tools_layout)

        # 5. 定位跳转与标记清理按钮
        jump_layout = QHBoxLayout()
        self.chk_keep_marker = QCheckBox("显示十字靶心")
        self.chk_keep_marker.setChecked(True)

        btn_jump = QPushButton("🚀 立即定位跳转")
        btn_jump.setMinimumHeight(34)
        btn_jump.setStyleSheet("background-color: #0984e3; color: white; font-weight: bold; border-radius: 4px;")
        btn_jump.clicked.connect(self.zoom_to_coordinate)

        btn_clear_mk = QPushButton("🧹 清除标记")
        btn_clear_mk.setMinimumHeight(34)
        btn_clear_mk.setToolTip("清除图面上所有定位留下的红色十字标记")
        btn_clear_mk.clicked.connect(self.clear_markers)

        jump_layout.addWidget(self.chk_keep_marker)
        jump_layout.addWidget(btn_jump, 1)
        jump_layout.addWidget(btn_clear_mk)
        loc_layout.addLayout(jump_layout)

        layout.addWidget(group_locator)

        # =================================================================
        # 专区 B：原有 —— 表格转点与批量制图
        # =================================================================
        group_excel = QGroupBox("📊 表格批量转点与高清出图")
        group_excel.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #dcdde1;
                border-radius: 6px;
                margin-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #2f3640;
            }
        """)
        excel_layout = QVBoxLayout(group_excel)

        # 1. 选择文件
        file_layout = QHBoxLayout()
        self.excel_txt_file = QLineEdit()
        self.excel_txt_file.setReadOnly(True)
        self.excel_txt_file.setPlaceholderText("选择 Excel 或 CSV 表格...")
        btn_excel_browse = QPushButton(" 浏览 ")
        btn_excel_browse.setFixedWidth(70)
        btn_excel_browse.clicked.connect(self.excel_choose_file)
        file_layout.addWidget(self.excel_txt_file)
        file_layout.addWidget(btn_excel_browse)
        excel_layout.addWidget(QLabel("<b>1. 选择数据源文件:</b>"))
        excel_layout.addLayout(file_layout)

        # 2. 字段映射（经度、纬度、命名列）
        col_layout = QHBoxLayout()
        col_layout.addWidget(QLabel("经度(X):"))
        self.lon_combo = QComboBox()
        col_layout.addWidget(self.lon_combo)
        col_layout.addWidget(QLabel("纬度(Y):"))
        self.lat_combo = QComboBox()
        col_layout.addWidget(self.lat_combo)
        col_layout.addWidget(QLabel("命名列:"))
        self.name_combo = QComboBox()
        col_layout.addWidget(self.name_combo)
        excel_layout.addWidget(QLabel("<b>2. 映射坐标与名字段:</b>"))
        excel_layout.addLayout(col_layout)

        # 3. 矢量输出设置
        excel_layout.addWidget(QLabel("<b>3. 输出与制图选项:</b>"))
        self.chk_save_vector = QCheckBox("同时导出点矢量到本地文件(SHP)")
        self.vector_path_txt = QLineEdit()
        self.vector_path_txt.setEnabled(False)
        self.vector_path_txt.setPlaceholderText("选择 SHP 保存路径...")
        btn_vec_browse = QPushButton("保存至...")
        btn_vec_browse.setEnabled(False)

        self.chk_save_vector.toggled.connect(self.vector_path_txt.setEnabled)
        self.chk_save_vector.toggled.connect(btn_vec_browse.setEnabled)
        btn_vec_browse.clicked.connect(self.excel_choose_vector_save)

        vec_path_layout = QHBoxLayout()
        vec_path_layout.addWidget(self.vector_path_txt)
        vec_path_layout.addWidget(btn_vec_browse)
        excel_layout.addWidget(self.chk_save_vector)
        excel_layout.addLayout(vec_path_layout)

        # 4. 图片集输出设置
        self.chk_export_images = QCheckBox("批量导出点位视图图片集")
        self.chk_export_images.setChecked(True)
        self.img_dir_txt = QLineEdit()
        self.img_dir_txt.setPlaceholderText("选择图片集保存文件夹...")
        btn_img_browse = QPushButton("选择文件夹")

        self.chk_export_images.toggled.connect(self.img_dir_txt.setEnabled)
        self.chk_export_images.toggled.connect(btn_img_browse.setEnabled)
        btn_img_browse.clicked.connect(self.excel_choose_img_folder)

        excel_layout.addWidget(self.chk_export_images)
        img_path_layout = QHBoxLayout()
        img_path_layout.addWidget(self.img_dir_txt)
        img_path_layout.addWidget(btn_img_browse)
        excel_layout.addLayout(img_path_layout)

        # 5. 渲染参数设置 (动态边距 + DPI 清晰度选择)
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel("边距扩展(%):"))
        self.spin_margin = QSpinBox()
        self.spin_margin.setRange(5, 500)
        self.spin_margin.setValue(20)
        param_layout.addWidget(self.spin_margin)

        param_layout.addWidget(QLabel("输出DPI:"))
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["96 DPI ", "150 DPI ", "300 DPI "])
        self.dpi_combo.setCurrentIndex(1)  # 默认 150 DPI
        param_layout.addWidget(self.dpi_combo)
        excel_layout.addLayout(param_layout)

        self.chk_show_points = QCheckBox("图集中显示点位符号(取消可避免遮挡地物)")
        self.chk_show_points.setChecked(True)
        excel_layout.addWidget(self.chk_show_points)

        # 6. 执行按钮
        self.btn_excel_run = QPushButton("📋 开始清洗数据、建点与出图")
        self.btn_excel_run.setStyleSheet(
            "background-color: #2196F3; color: white; font-weight: bold; height:38px; border-radius: 4px;")
        self.btn_excel_run.clicked.connect(self.excel_run_task)
        excel_layout.addWidget(self.btn_excel_run)

        layout.addWidget(group_excel)
        layout.addStretch()

        scroll.setWidget(content_widget)
        outer_layout.addWidget(scroll)

    # =================================================================
    # 逻辑部分 A：坐标点定位、智能防呆校验与图面拾取
    # =================================================================
    def apply_epsg_code(self):
        """根据用户输入的 EPSG 代码搜索并设置坐标系"""
        raw_text = self.txt_epsg.text().strip()
        if not raw_text:
            QMessageBox.warning(self.dock_widget, "输入为空", "请输入 EPSG 编号（例如：4326、4490、3857、4547）！")
            return

        # 提取纯数字部分，兼容用户输入 "EPSG:4326" 或 "4326"
        match = re.search(r'(\d+)', raw_text)
        if not match:
            QMessageBox.warning(
                self.dock_widget, "格式错误",
                f"无法从“{raw_text}”中识别出有效的 EPSG 数字编号！\n\n"
                "💡 常见编号参考：\n"
                "• 4326 : WGS 84 (GPS经纬度)\n"
                "• 4490 : CGCS2000 (国家2000经纬度)\n"
                "• 3857 : Web 墨卡托 (在线瓦片地图)\n"
                "• 4547 : CGCS2000 / 3度分带 114°E"
            )
            return

        epsg_num = match.group(1)
        crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_num}")
        if not crs.isValid():
            QMessageBox.critical(
                self.dock_widget, "未找到坐标系",
                f"QGIS 数据库中不存在【EPSG:{epsg_num}】对应的坐标系！\n"
                "请检查数字是否输错，或点击下方坐标系控件右侧的【地球图标】按名称搜索。"
            )
            return

        self.crs_selector.setCrs(crs)
        self.iface.messageBar().pushMessage(
            "坐标系已切换", f"当前定位坐标系已设为: {crs.authid()} - {crs.description()}",
            level=Qgis.Success, duration=3
        )

    def on_crs_widget_changed(self, crs):
        """当用户在下拉控件里切换坐标系时，同步更新上方的 EPSG 输入框"""
        if crs and crs.isValid():
            auth_id = crs.authid()
            if auth_id.startswith("EPSG:"):
                self.txt_epsg.setText(auth_id.replace("EPSG:", ""))
            else:
                self.txt_epsg.setText(auth_id)

    def on_x_smart_paste(self, text):
        """当用户直接往 X 框里粘贴 '116.397, 39.908' 时，自动拆分到 X 和 Y 两个框"""
        if any(sep in text for sep in [',', '，', ';', '；', '\t']):
            parts = [p.strip() for p in re.split(r'[,，;；\t]+', text) if p.strip()]
            if len(parts) >= 2:
                self.txt_x.blockSignals(True)
                self.txt_x.setText(parts[0])
                self.txt_x.blockSignals(False)
                self.txt_y.setText(parts[1])

    def paste_from_clipboard(self):
        """一键读取系统剪贴板并智能拆分 X, Y 坐标"""
        clip_text = QApplication.clipboard().text().strip()
        if not clip_text:
            QMessageBox.warning(self.dock_widget, "剪贴板为空", "当前系统剪贴板中没有文本内容！")
            return

        # 支持逗号、分号、制表符或空格分隔
        parts = [p.strip() for p in re.split(r'[,，;；\t\s]+', clip_text) if p.strip()]
        if len(parts) >= 2:
            self.txt_x.blockSignals(True)
            self.txt_x.setText(parts[0])
            self.txt_x.blockSignals(False)
            self.txt_y.setText(parts[1])
            self.iface.messageBar().pushMessage("粘贴成功", f"已自动拆分坐标 X={parts[0]}, Y={parts[1]}", level=Qgis.Info, duration=2)
        else:
            QMessageBox.warning(
                self.dock_widget, "解析失败",
                f"剪贴板内容为：“{clip_text[:40]}”\n未能识别出成对的 X、Y 坐标（请用逗号或空格分隔两个坐标值）。"
            )

    def copy_to_clipboard(self):
        """一键复制当前输入框中的坐标"""
        x_str = self.txt_x.text().strip()
        y_str = self.txt_y.text().strip()
        if not x_str or not y_str:
            self.iface.messageBar().pushMessage("提示", "当前坐标输入框为空，无法复制", level=Qgis.Warning, duration=2)
            return
        QApplication.clipboard().setText(f"{x_str}, {y_str}")
        self.iface.messageBar().pushMessage("复制成功", f"已复制坐标: {x_str}, {y_str}", level=Qgis.Success, duration=2)

    def swap_xy(self):
        """一键互换 X 与 Y 输入框内容"""
        x_val = self.txt_x.text()
        y_val = self.txt_y.text()
        self.txt_x.blockSignals(True)
        self.txt_x.setText(y_val)
        self.txt_x.blockSignals(False)
        self.txt_y.setText(x_val)

    def parse_single_coord(self, raw_str):
        """
        解析单个坐标字符串，支持：
        1. 十进制小数: 116.397128, -39.908
        2. 度分秒(DMS): 116°23'49.66", 116度23分49.66秒, 116:23:49.66, E116°23'49"
        返回: (float_value, error_message)
        """
        s = raw_str.strip()
        if not s:
            return None, "输入内容为空"

        # 检查是否包含南纬(S)或西经(W)负号标识
        sign = -1.0 if re.search(r'[sSwW南西\-]', s) else 1.0
        s_clean = re.sub(r'[nNeEsSwW北南东西\+]', '', s).strip()

        # 1. 尝试直接按十进制浮点数解析
        try:
            val = float(s_clean)
            if math.isnan(val) or math.isinf(val):
                return None, "数值无效 (NaN/Inf)"
            return val, None
        except ValueError:
            pass

        # 2. 尝试按度分秒 (DMS) 解析
        dms_match = re.match(
            r'^\s*(\d+(?:\.\d+)?)\s*[°度:：\s]\s*(\d+(?:\.\d+)?)?\s*[\'′分:：\s]?\s*(\d+(?:\.\d+)?)?\s*[\"″秒]?\s*$',
            s_clean
        )
        if dms_match:
            deg = float(dms_match.group(1))
            minutes = float(dms_match.group(2)) if dms_match.group(2) else 0.0
            seconds = float(dms_match.group(3)) if dms_match.group(3) else 0.0
            if minutes >= 60 or seconds >= 60:
                return None, f"度分秒格式中“分({minutes})”或“秒({seconds})”不能大于或等于 60！"
            decimal_val = sign * (deg + minutes / 60.0 + seconds / 3600.0)
            return decimal_val, None

        return None, f"无法识别的坐标格式：“{raw_str}”\n支持格式如：116.3971 或 116°23'49.5\""

    def zoom_to_coordinate(self):
        """核心定位逻辑（含五重防呆报错与动态坐标转换）"""
        # 校验 1：检查所选坐标系是否有效
        source_crs = self.crs_selector.crs()
        if not source_crs or not source_crs.isValid():
            QMessageBox.critical(
                self.dock_widget, "坐标系无效",
                "当前未选择有效的坐标系！\n请先在上方输入有效的 EPSG 代码（如 4326）或从下拉框中选择坐标系。"
            )
            return

        # 校验 2：检查并解析 X 和 Y 输入值
        x_raw = self.txt_x.text().strip()
        y_raw = self.txt_y.text().strip()
        if not x_raw or not y_raw:
            QMessageBox.warning(self.dock_widget, "坐标缺失", "请同时输入 经度(X) 和 纬度(Y) 坐标值！")
            return

        x_val, err_x = self.parse_single_coord(x_raw)
        if err_x:
            QMessageBox.warning(self.dock_widget, "经度(X) 格式错误", f"【经度/X】解析失败：\n{err_x}")
            self.txt_x.setFocus()
            return

        y_val, err_y = self.parse_single_coord(y_raw)
        if err_y:
            QMessageBox.warning(self.dock_widget, "纬度(Y) 格式错误", f"【纬度/Y】解析失败：\n{err_y}")
            self.txt_y.setFocus()
            return

        # 校验 3：地理坐标系（经纬度）与投影坐标系（米）的范围防呆检测
        if source_crs.isGeographic():
            # 情况 3A：用户把经度和纬度填反了（例如 X=39.9, Y=116.4）
            if -90.0 <= x_val <= 90.0 and (90.0 < abs(y_val) <= 180.0):
                reply = QMessageBox.question(
                    self.dock_widget, "智能纠错：经纬度疑似填反",
                    f"检测到您输入的 X={x_val}，Y={y_val}。\n"
                    f"在地理坐标系下，纬度(Y)不能超过 ±90°。\n\n"
                    f"您是否不小心把【经度】和【纬度】填反了？\n"
                    f"点击【Yes】自动互换为 (经度:{y_val}, 纬度:{x_val}) 并立即跳转！",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.swap_xy()
                    x_val, y_val = y_val, x_val
                else:
                    return

            # 情况 3B：在地理坐标系下输入了米制投影大数（如 X=38456789, Y=3245678）
            if not (-180.0 <= x_val <= 180.0 and -90.0 <= y_val <= 90.0):
                QMessageBox.critical(
                    self.dock_widget, "坐标超出经纬度范围",
                    f"当前选择的坐标系【{source_crs.authid()}】是地理坐标系（单位：度）：\n"
                    f"• 经度(X) 必须在 -180° ~ 180° 之间（当前为 {x_val}）\n"
                    f"• 纬度(Y) 必须在 -90° ~ 90° 之间（当前为 {y_val}）\n\n"
                    f"💡 提示：如果您输入的是米制平面坐标（如 2000 高斯投影坐标），"
                    f"请先在上方将坐标系切换为对应的投影坐标系（如 EPSG:4547）！"
                )
                return
        else:
            # 情况 3C：选择了米制投影坐标系，但输入的却是 (116.39, 39.90) 这种经纬度小数
            if -180.0 <= x_val <= 180.0 and -90.0 <= y_val <= 90.0 and (abs(x_val) > 0.01 or abs(y_val) > 0.01):
                reply = QMessageBox.question(
                    self.dock_widget, "坐标系单位提醒",
                    f"您当前选择的【{source_crs.authid()} - {source_crs.description()}】是投影坐标系（单位：米），\n"
                    f"但您输入的数值 ({x_val}, {y_val}) 看起来像经纬度（单位：度）。\n\n"
                    f"• 点击【Yes】：自动帮您临时按 WGS84 经纬度 (EPSG:4326) 解析并跳转\n"
                    f"• 点击【No】：仍然强制按米制坐标跳转",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )
                if reply == QMessageBox.Cancel:
                    return
                elif reply == QMessageBox.Yes:
                    source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
                    self.crs_selector.setCrs(source_crs)

        # 校验 4：执行动态坐标转换（从用户选择的坐标系 -> 当前 QGIS 画布坐标系）
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        input_pt = QgsPointXY(x_val, y_val)
        target_pt = input_pt

        if source_crs != canvas_crs and canvas_crs.isValid():
            try:
                transform = QgsCoordinateTransform(source_crs, canvas_crs, QgsProject.instance())
                target_pt = transform.transform(input_pt)
                if math.isnan(target_pt.x()) or math.isnan(target_pt.y()) or math.isinf(target_pt.x()) or math.isinf(target_pt.y()):
                    raise ValueError("转换结果超出数学定义域 (NaN/Inf)")
            except (QgsCsException, Exception) as e:
                QMessageBox.critical(
                    self.dock_widget, "坐标投影转换失败",
                    f"无法将坐标 ({x_val}, {y_val}) 从【{source_crs.authid()}】转换到当前画布坐标系【{canvas_crs.authid()}】！\n\n"
                    f"常见原因：输入的平面坐标横轴带号与所选分带坐标系不匹配，或测绘 X/Y（北方向/东方向）顺序填反。\n"
                    f"建议点击【⇄】按钮互换 X/Y 后重试。\n\n底层详情: {str(e)}"
                )
                return

        # 5. 移动画布中心并设置缩放比例尺
        canvas.setCenter(target_pt)
        scale_text = self.scale_combo.currentText()
        if "1:" in scale_text:
            try:
                target_scale = int(scale_text.split("1:")[1].replace(",", "").strip())
                canvas.zoomScale(target_scale)
            except Exception:
                pass
        canvas.refresh()

        # 6. 触发 QGIS 原生雷达闪烁特效 + 绘制十字高亮标记
        try:
            canvas.flashGeometries([QgsGeometry.fromPointXY(target_pt)], canvas_crs, flashes=3, duration=500)
        except Exception:
            pass

        self.clear_markers()
        if self.chk_keep_marker.isChecked():
            marker = QgsVertexMarker(canvas)
            marker.setCenter(target_pt)
            marker.setColor(QColor(255, 0, 0))
            marker.setFillColor(QColor(255, 255, 0, 180))
            marker.setIconType(QgsVertexMarker.ICON_CROSS)
            marker.setIconSize(18)
            marker.setPenWidth(3)
            self.markers.append(marker)

        self.iface.messageBar().pushMessage(
            "定位成功",
            f"已跳转至 ({x_val:.6f}, {y_val:.6f}) [{source_crs.authid()}]",
            level=Qgis.Success, duration=3
        )

    def clear_markers(self):
        """清除画布上的所有十字定位标记"""
        canvas = self.iface.mapCanvas()
        for m in self.markers:
            try:
                canvas.scene().removeItem(m)
            except Exception:
                pass
        self.markers.clear()
        canvas.refresh()

    def toggle_map_picker(self, checked):
        """开启/关闭图面点击取点反查坐标工具"""
        canvas = self.iface.mapCanvas()
        if checked:
            self.prev_map_tool = canvas.mapTool()
            self.map_tool = QgsMapToolEmitPoint(canvas)
            self.map_tool.canvasClicked.connect(self.on_canvas_clicked)
            self.map_tool.deactivated.connect(lambda: self.btn_pick.setChecked(False))
            canvas.setMapTool(self.map_tool)
            self.btn_pick.setStyleSheet("background-color: #ffeaa7; color: #d63031; font-weight: bold;")
            self.iface.messageBar().pushMessage("图面取点已开启", "请在地图画布上左键单击任意位置拾取坐标", level=Qgis.Info, duration=3)
        else:
            if self.map_tool and canvas.mapTool() == self.map_tool:
                if self.prev_map_tool:
                    canvas.setMapTool(self.prev_map_tool)
                else:
                    canvas.unsetMapTool(self.map_tool)
            self.btn_pick.setStyleSheet("")

    def on_canvas_clicked(self, point, button):
        """当用户在地图画布上点击时，将画布坐标自动转换为上方选定的坐标系并填入输入框"""
        if button != Qt.LeftButton:
            return

        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        target_crs = self.crs_selector.crs()

        out_pt = point
        if target_crs.isValid() and canvas_crs.isValid() and canvas_crs != target_crs:
            try:
                transform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
                out_pt = transform.transform(point)
            except Exception as e:
                QMessageBox.warning(self.dock_widget, "坐标反算失败", f"无法将画布坐标转换到 {target_crs.authid()}:\n{e}")
                return

        # 地理坐标系保留 6 位小数，投影坐标系保留 3 位小数
        decimals = 6 if target_crs.isGeographic() else 3
        self.txt_x.blockSignals(True)
        self.txt_x.setText(f"{out_pt.x():.{decimals}f}")
        self.txt_x.blockSignals(False)
        self.txt_y.setText(f"{out_pt.y():.{decimals}f}")

        # 在点击处打上标记
        self.clear_markers()
        if self.chk_keep_marker.isChecked():
            marker = QgsVertexMarker(canvas)
            marker.setCenter(point)
            marker.setColor(QColor(255, 0, 0))
            marker.setIconType(QgsVertexMarker.ICON_CROSS)
            marker.setIconSize(18)
            marker.setPenWidth(3)
            self.markers.append(marker)

        # 取完点后恢复原来的漫游工具
        self.btn_pick.setChecked(False)
        self.toggle_map_picker(False)

    # =================================================================
    # 逻辑部分 B：原有表格转点与批量制图（已同步升级支持跨坐标系截图）
    # =================================================================
    def excel_choose_file(self):
        if pd is None:
            QMessageBox.critical(self.dock_widget, "环境缺失",
                                 "当前 QGIS 环境未安装 pandas！\n 请打开 OSGeo4W Shell 执行: pip install pandas")
            return

        file_path, _ = QFileDialog.getOpenFileName(self.dock_widget, "选择表格文件",
                                                   "", "Excel & CSV Files (*.xlsx *.xls *.csv)")
        if file_path:
            self.excel_txt_file.setText(file_path)
            try:
                if file_path.endswith('.csv'):
                    self.excel_df = pd.read_csv(file_path)
                else:
                    self.excel_df = pd.read_excel(file_path)

                columns = ["-- 默认 自动命名 --"] + list(self.excel_df.columns.astype(str))
                self.lon_combo.clear()
                self.lat_combo.clear()
                self.name_combo.clear()

                self.lon_combo.addItems(list(self.excel_df.columns.astype(str)))
                self.lat_combo.addItems(list(self.excel_df.columns.astype(str)))
                self.name_combo.addItems(columns)

                for col in self.excel_df.columns:
                    col_lower = str(col).lower()
                    if any(k in col_lower for k in ['lon', '经度', 'x']):
                        self.lon_combo.setCurrentText(str(col))
                    if any(k in col_lower for k in ['lat', '纬度', 'y']):
                        self.lat_combo.setCurrentText(str(col))

                self.iface.messageBar().pushMessage("成功", f"成功读取表格，共 {len(self.excel_df)} 行数据", level=0,
                                                    duration=3)
            except Exception as e:
                QMessageBox.critical(self.dock_widget, "错误", f"读取表格失败:\n{str(e)}")

    def excel_choose_vector_save(self):
        path, _ = QFileDialog.getSaveFileName(self.dock_widget, "保存点矢量", "", "ESRI Shapefile (*.shp)")
        if path:
            if not path.endswith('.shp'):
                path += '.shp'
            self.vector_path_txt.setText(path)

    def excel_choose_img_folder(self):
        folder = QFileDialog.getExistingDirectory(self.dock_widget, "选择图片集保存文件夹")
        if folder:
            self.img_dir_txt.setText(folder)

    def clean_coordinate_string(self, val):
        if pd.isna(val):
            return None
        val_parsed, err = self.parse_single_coord(str(val))
        return val_parsed

    def excel_run_task(self):
        if self.excel_df is None:
            QMessageBox.warning(self.dock_widget, "提示", "请先选择并加载有效的表格文件！")
            return

        lon_col = self.lon_combo.currentText()
        lat_col = self.lat_combo.currentText()
        name_col = self.name_combo.currentText()

        if not lon_col or not lat_col:
            QMessageBox.warning(self.dock_widget, "提示", "请指定经度和纬度所在的列！")
            return

        source_crs = self.crs_selector.crs()
        if not source_crs or not source_crs.isValid():
            source_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        valid_points = []
        for index, row in self.excel_df.iterrows():
            lon = self.clean_coordinate_string(row[lon_col])
            lat = self.clean_coordinate_string(row[lat_col])

            if lon is not None and lat is not None:
                # 若所选坐标系为地理坐标系，则校验经纬度范围；若为投影坐标系则直接放行
                if source_crs.isGeographic() and not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    continue

                if name_col != "-- 默认 自动命名 --" and name_col in self.excel_df.columns:
                    raw_name = str(row[name_col])
                    safe_name = re.sub(r'[\/:*?"<>|]', "_", raw_name)
                    if not safe_name.strip():
                        safe_name = f"Point_{index + 1}"
                else:
                    safe_name = f"Point_{index + 1}"

                valid_points.append({
                    "name": safe_name,
                    "x": lon,
                    "y": lat
                })

        if not valid_points:
            QMessageBox.warning(
                self.dock_widget, "错误",
                f"没有清洗出任何有效的点位！\n请检查字段匹配，以及上方所选的坐标系（当前：{source_crs.authid()}）是否与表格数据一致。"
            )
            return

        # 2. 如果用户同时勾选了“导出点矢量到本地文件(SHP)”
        if self.chk_save_vector.isChecked() and self.vector_path_txt.text():
            try:
                temp_layer = QgsVectorLayer(f"Point?crs={source_crs.authid()}", "temp_export", "memory")
                prov = temp_layer.dataProvider()
                fields = [QgsField(str(col), QVariant.String) for col in self.excel_df.columns]
                prov.addAttributes(fields)
                temp_layer.updateFields()

                temp_feats = []
                for index, row in self.excel_df.iterrows():
                    lon = self.clean_coordinate_string(row[lon_col])
                    lat = self.clean_coordinate_string(row[lat_col])
                    if lon is not None and lat is not None:
                        feat = QgsFeature(temp_layer.fields())
                        for col in self.excel_df.columns:
                            feat.setAttribute(col, str(row[col]) if not pd.isna(row[col]) else "")
                        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
                        temp_feats.append(feat)
                prov.addFeatures(temp_feats)

                vec_path = self.vector_path_txt.text()
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "ESRI Shapefile"
                options.fileEncoding = "UTF-8"
                QgsVectorFileWriter.writeAsVectorFormatV2(temp_layer, vec_path,
                                                          QgsProject.instance().transformContext(), options)
            except Exception as e:
                print(f"导出SHP出错: {e}")

        # 3. 批量导出图片集（自动适配画布坐标系）
        if self.chk_export_images.isChecked():
            out_dir = self.img_dir_txt.text()
            if not out_dir:
                QMessageBox.warning(self.dock_widget, "警告", "请先选择图片集保存文件夹！")
                return
            os.makedirs(out_dir, exist_ok=True)

            margin_percent = self.spin_margin.value() / 100.0
            dpi_text = self.dpi_combo.currentText()
            dpi = 300 if "300" in dpi_text else (150 if "150" in dpi_text else 96)

            self.btn_excel_run.setEnabled(False)
            self.btn_excel_run.setText("⏳ 正在根据表格坐标与可见图层批量出图...")
            success_count = 0

            canvas = self.iface.mapCanvas()
            canvas_crs = canvas.mapSettings().destinationCrs()
            need_transform = (source_crs != canvas_crs and canvas_crs.isValid())
            if need_transform:
                transform = QgsCoordinateTransform(source_crs, canvas_crs, QgsProject.instance())

            # 自适应基础视野半径：画布是经纬度时取 0.0015 度，画布是米制投影时取 150 米
            base_delta = 0.0015 if canvas_crs.isGeographic() else 150.0

            for pt in valid_points:
                pt_xy = QgsPointXY(pt["x"], pt["y"])
                if need_transform:
                    try:
                        pt_xy = transform.transform(pt_xy)
                    except Exception:
                        continue

                rect = QgsRectangle(pt_xy, pt_xy)
                rect.grow(base_delta * (1 + margin_percent))

                base_size = canvas.size()
                scale_factor = dpi / 96.0
                img_width = int(base_size.width() * scale_factor)
                img_height = int(base_size.height() * scale_factor)

                map_settings = canvas.mapSettings()
                map_settings.setExtent(rect)
                map_settings.setOutputSize(QSize(img_width, img_height))

                image = QImage(QSize(img_width, img_height), QImage.Format_ARGB32_Premultiplied)
                image.setDotsPerMeterX(int(dpi / 0.0254))
                image.setDotsPerMeterY(int(dpi / 0.0254))
                image.fill(Qt.white)

                painter = QPainter(image)
                painter.setRenderHint(QPainter.Antialiasing)

                job = QgsMapRendererCustomPainterJob(map_settings, painter)
                loop = QEventLoop()
                job.finished.connect(loop.quit)
                job.start()
                loop.exec_()
                painter.end()

                out_path = os.path.join(out_dir, f"{pt['name']}.png")
                try:
                    image.save(out_path, "PNG")
                    success_count += 1
                except Exception:
                    pass

            self.btn_excel_run.setEnabled(True)
            self.btn_excel_run.setText("📋 开始清洗数据、建点与出图")
            QMessageBox.information(self.dock_widget, "导出完成",
                                    f"成功处理 {len(valid_points)} 个坐标点\n成功基于当前可见图层导出图片: {success_count} 张\n路径: {out_dir}")
        else:
            QMessageBox.information(self.dock_widget, "完成", f"已成功解析 {len(valid_points)} 个坐标点数据！")