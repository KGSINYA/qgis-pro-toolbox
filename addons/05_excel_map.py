# -*- coding: utf-8 -*-
import os
import re
import math

# ---------- Third party: safe import of pandas ----------
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
    title = tr("📊 表格转点制图", "📊 Table to Points")
    order = 5

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.excel_df = None
        self.markers = []          # Crosshair highlight markers drawn on the canvas
        self.map_tool = None       # Click-to-pick coordinate tool
        self.prev_map_tool = None  # Map tool the user had active before picking

    def unload(self):
        """Remove the crosshair markers and the pick tool when the module unloads or hot-reloads"""
        self.clear_markers()
        if self.map_tool and self.iface.mapCanvas().mapTool() == self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
        self.map_tool = None

    def setup_ui(self, parent_widget):
        # Wrap everything in a scroll area so the controls do not crowd on small screens
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
        # Section A: quick coordinate locator and pick on canvas
        # =================================================================
        group_locator = QGroupBox(tr("📍 坐标点快速定位与图面拾取", "📍 Quick coordinate locator and pick on canvas"))
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

        # 1. Quick EPSG search bar
        epsg_layout = QHBoxLayout()
        epsg_layout.addWidget(QLabel(tr("快捷EPSG:", "Quick EPSG:")))
        self.txt_epsg = QLineEdit()
        self.txt_epsg.setPlaceholderText(tr("输入代码如 4326, 4490, 4547 回车...", "Enter a code such as 4326, 4490, 4547 and press Enter..."))
        self.txt_epsg.returnPressed.connect(self.apply_epsg_code)
        btn_epsg = QPushButton(tr("🔍 应用", "🔍 Apply"))
        btn_epsg.setFixedWidth(60)
        btn_epsg.setToolTip(tr("根据输入的 EPSG 编号自动匹配坐标系", "Match a CRS automatically from the EPSG code you enter"))
        btn_epsg.clicked.connect(self.apply_epsg_code)
        epsg_layout.addWidget(self.txt_epsg)
        epsg_layout.addWidget(btn_epsg)
        loc_layout.addLayout(epsg_layout)

        # 2. Native QGIS CRS selector
        crs_layout = QHBoxLayout()
        crs_layout.addWidget(QLabel(tr("当前坐标系:", "Current CRS:")))
        self.crs_selector = QgsProjectionSelectionWidget()
        # WGS 84 (EPSG:4326) by default
        default_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        self.crs_selector.setCrs(default_crs)
        self.txt_epsg.setText("4326")
        self.crs_selector.crsChanged.connect(self.on_crs_widget_changed)
        crs_layout.addWidget(self.crs_selector, 1)
        loc_layout.addLayout(crs_layout)

        # 3. Longitude (X) / latitude (Y) fields (decimal, DMS and smart paste)
        xy_layout = QHBoxLayout()
        self.txt_x = QLineEdit()
        self.txt_x.setPlaceholderText(tr("经度/X (如 116.39 或 116°23'49\")", "Longitude/X (e.g. 116.39 or 116°23'49\")"))
        self.txt_x.textChanged.connect(self.on_x_smart_paste)
        self.txt_x.returnPressed.connect(self.zoom_to_coordinate)

        self.txt_y = QLineEdit()
        self.txt_y.setPlaceholderText(tr("纬度/Y (如 39.90 或 39°54'20\")", "Latitude/Y (e.g. 39.90 or 39°54'20\")"))
        self.txt_y.returnPressed.connect(self.zoom_to_coordinate)

        btn_swap = QPushButton("⇄")
        btn_swap.setFixedWidth(28)
        btn_swap.setToolTip(tr("一键互换 X 与 Y 坐标（解决经纬度或测绘纵横坐标填反问题）", "Swap the X and Y coordinates in one click (fixes reversed lon/lat or survey northing/easting)"))
        btn_swap.clicked.connect(self.swap_xy)

        xy_layout.addWidget(QLabel("X:"))
        xy_layout.addWidget(self.txt_x, 1)
        xy_layout.addWidget(btn_swap)
        xy_layout.addWidget(QLabel("Y:"))
        xy_layout.addWidget(self.txt_y, 1)
        loc_layout.addLayout(xy_layout)

        # 4. Helper toolbar: smart paste, copy coordinates, pick on canvas, zoom scale
        tools_layout = QHBoxLayout()
        btn_paste = QPushButton(tr("📋 粘贴解析", "📋 Paste & parse"))
        btn_paste.setToolTip(tr("直接读取剪贴板中的 'X, Y' 坐标文本并自动拆分填入", "Read an 'X, Y' pair from the clipboard and split it into the fields"))
        btn_paste.clicked.connect(self.paste_from_clipboard)

        btn_copy = QPushButton(tr("📄 复制", "📄 Copy"))
        btn_copy.setToolTip(tr("将当前输入框中的 X, Y 坐标复制到剪贴板", "Copy the current X, Y coordinates to the clipboard"))
        btn_copy.clicked.connect(self.copy_to_clipboard)

        self.btn_pick = QPushButton(tr("🎯 图面取点", "🎯 Pick on canvas"))
        self.btn_pick.setCheckable(True)
        self.btn_pick.setToolTip(tr("点击后在地图画布上左键单击，即可反查该点在上方所选坐标系下的坐标", "After enabling, left-click on the map canvas to read the coordinates of that point in the CRS selected above"))
        self.btn_pick.clicked.connect(self.toggle_map_picker)

        self.scale_combo = QComboBox()
        self.scale_combo.setToolTip(tr("跳转定位时的地图缩放比例尺", "Map scale applied when zooming to the coordinate"))
        self.scale_combo.addItems([
            tr("比例尺: 1:2,000", "Scale 1:2,000"),
            tr("比例尺: 1:500", "Scale 1:500"),
            tr("比例尺: 1:1,000", "Scale 1:1,000"),
            tr("比例尺: 1:5,000", "Scale 1:5,000"),
            tr("比例尺: 1:10,000", "Scale 1:10,000"),
            tr("比例尺: 1:50,000", "Scale 1:50,000"),
            tr("保持当前比例尺", "Keep current scale")
        ])

        tools_layout.addWidget(btn_paste)
        tools_layout.addWidget(btn_copy)
        tools_layout.addWidget(self.btn_pick)
        tools_layout.addWidget(self.scale_combo, 1)
        loc_layout.addLayout(tools_layout)

        # 5. Zoom-to button and marker cleanup
        jump_layout = QHBoxLayout()
        self.chk_keep_marker = QCheckBox(tr("显示十字靶心", "Show crosshair marker"))
        self.chk_keep_marker.setChecked(True)

        btn_jump = QPushButton(tr("🚀 立即定位跳转", "🚀 Zoom to coordinate"))
        btn_jump.setMinimumHeight(34)
        btn_jump.setStyleSheet("background-color: #0984e3; color: white; font-weight: bold; border-radius: 4px;")
        btn_jump.clicked.connect(self.zoom_to_coordinate)

        btn_clear_mk = QPushButton(tr("🧹 清除标记", "🧹 Clear markers"))
        btn_clear_mk.setMinimumHeight(34)
        btn_clear_mk.setToolTip(tr("清除图面上所有定位留下的红色十字标记", "Remove all red crosshair markers left on the canvas"))
        btn_clear_mk.clicked.connect(self.clear_markers)

        jump_layout.addWidget(self.chk_keep_marker)
        jump_layout.addWidget(btn_jump, 1)
        jump_layout.addWidget(btn_clear_mk)
        loc_layout.addLayout(jump_layout)

        layout.addWidget(group_locator)

        # =================================================================
        # Section B: table to points and batch map export
        # =================================================================
        group_excel = QGroupBox(tr("📊 表格批量转点与高清出图", "📊 Batch table to points and high-resolution export"))
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

        # 1. Choose the file
        file_layout = QHBoxLayout()
        self.excel_txt_file = QLineEdit()
        self.excel_txt_file.setReadOnly(True)
        self.excel_txt_file.setPlaceholderText(tr("选择 Excel 或 CSV 表格...", "Choose an Excel or CSV table..."))
        btn_excel_browse = QPushButton(tr(" 浏览 ", " Browse "))
        btn_excel_browse.setFixedWidth(70)
        btn_excel_browse.clicked.connect(self.excel_choose_file)
        file_layout.addWidget(self.excel_txt_file)
        file_layout.addWidget(btn_excel_browse)
        excel_layout.addWidget(QLabel(tr("<b>1. 选择数据源文件:</b>", "<b>1. Choose the source file:</b>")))
        excel_layout.addLayout(file_layout)

        # 2. Field mapping (longitude, latitude, name column)
        col_layout = QHBoxLayout()
        col_layout.addWidget(QLabel(tr("经度(X):", "Longitude (X):")))
        self.lon_combo = QComboBox()
        col_layout.addWidget(self.lon_combo)
        col_layout.addWidget(QLabel(tr("纬度(Y):", "Latitude (Y):")))
        self.lat_combo = QComboBox()
        col_layout.addWidget(self.lat_combo)
        col_layout.addWidget(QLabel(tr("命名列:", "Name column:")))
        self.name_combo = QComboBox()
        col_layout.addWidget(self.name_combo)
        excel_layout.addWidget(QLabel(tr("<b>2. 映射坐标与名字段:</b>", "<b>2. Map the coordinate and name fields:</b>")))
        excel_layout.addLayout(col_layout)

        # 3. Vector output settings
        excel_layout.addWidget(QLabel(tr("<b>3. 输出与制图选项:</b>", "<b>3. Output and map export options:</b>")))
        self.chk_save_vector = QCheckBox(tr("同时导出点矢量到本地文件(SHP)", "Also export the point layer to a local file (SHP)"))
        self.vector_path_txt = QLineEdit()
        self.vector_path_txt.setEnabled(False)
        self.vector_path_txt.setPlaceholderText(tr("选择 SHP 保存路径...", "Choose where to save the SHP..."))
        btn_vec_browse = QPushButton(tr("保存至...", "Save to..."))
        btn_vec_browse.setEnabled(False)

        self.chk_save_vector.toggled.connect(self.vector_path_txt.setEnabled)
        self.chk_save_vector.toggled.connect(btn_vec_browse.setEnabled)
        btn_vec_browse.clicked.connect(self.excel_choose_vector_save)

        vec_path_layout = QHBoxLayout()
        vec_path_layout.addWidget(self.vector_path_txt)
        vec_path_layout.addWidget(btn_vec_browse)
        excel_layout.addWidget(self.chk_save_vector)
        excel_layout.addLayout(vec_path_layout)

        # 4. Image set output
        self.chk_export_images = QCheckBox(tr("批量导出点位视图图片集", "Batch export an image set of the point views"))
        self.chk_export_images.setChecked(True)
        self.img_dir_txt = QLineEdit()
        self.img_dir_txt.setPlaceholderText(tr("选择图片集保存文件夹...", "Choose the folder for the image set..."))
        btn_img_browse = QPushButton(tr("选择文件夹", "Choose folder"))

        self.chk_export_images.toggled.connect(self.img_dir_txt.setEnabled)
        self.chk_export_images.toggled.connect(btn_img_browse.setEnabled)
        btn_img_browse.clicked.connect(self.excel_choose_img_folder)

        excel_layout.addWidget(self.chk_export_images)
        img_path_layout = QHBoxLayout()
        img_path_layout.addWidget(self.img_dir_txt)
        img_path_layout.addWidget(btn_img_browse)
        excel_layout.addLayout(img_path_layout)

        # 5. Render settings (dynamic margin + DPI)
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel(tr("边距扩展(%):", "Margin buffer (%):")))
        self.spin_margin = QSpinBox()
        self.spin_margin.setRange(5, 500)
        self.spin_margin.setValue(20)
        param_layout.addWidget(self.spin_margin)

        param_layout.addWidget(QLabel(tr("输出DPI:", "Output DPI:")))
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["96 DPI ", "150 DPI ", "300 DPI "])
        self.dpi_combo.setCurrentIndex(1)  # 150 DPI by default
        param_layout.addWidget(self.dpi_combo)
        excel_layout.addLayout(param_layout)

        self.chk_show_points = QCheckBox(tr("图集中显示点位符号(取消可避免遮挡地物)", "Show point symbols in the exported maps (clear to avoid covering features)"))
        self.chk_show_points.setChecked(True)
        excel_layout.addWidget(self.chk_show_points)

        # 6. Run button
        self.btn_excel_run = QPushButton(tr("📋 开始清洗数据、建点与出图", "📋 Clean data, build points and export maps"))
        self.btn_excel_run.setStyleSheet(
            "background-color: #2196F3; color: white; font-weight: bold; height:38px; border-radius: 4px;")
        self.btn_excel_run.clicked.connect(self.excel_run_task)
        excel_layout.addWidget(self.btn_excel_run)

        layout.addWidget(group_excel)
        layout.addStretch()

        scroll.setWidget(content_widget)
        outer_layout.addWidget(scroll)

    # =================================================================
    # Logic A: coordinate locating, input validation and pick on canvas
    # =================================================================
    def apply_epsg_code(self):
        """Look up the CRS from the EPSG code entered by the user and set it"""
        raw_text = self.txt_epsg.text().strip()
        if not raw_text:
            QMessageBox.warning(self.dock_widget, tr("输入为空", "Empty input"), tr("请输入 EPSG 编号（例如：4326、4490、3857、4547）！", "Enter an EPSG code (for example 4326, 4490, 3857, 4547)!"))
            return

        # Extract just the digits so that both "EPSG:4326" and "4326" are accepted
        match = re.search(r'(\d+)', raw_text)
        if not match:
            QMessageBox.warning(
                self.dock_widget, tr("格式错误", "Invalid format"),
                tr(
                    f"无法从“{raw_text}”中识别出有效的 EPSG 数字编号！\n\n"
                    "💡 常见编号参考：\n"
                    "• 4326 : WGS 84 (GPS经纬度)\n"
                    "• 4490 : CGCS2000 (国家2000经纬度)\n"
                    "• 3857 : Web 墨卡托 (在线瓦片地图)\n"
                    "• 4547 : CGCS2000 / 3度分带 114°E",
                    f"Could not find a valid EPSG number in '{raw_text}'.\n\n"
                    "💡 Common codes:\n"
                    "• 4326 : WGS 84 (GPS lon/lat)\n"
                    "• 4490 : CGCS2000 (national 2000 lon/lat)\n"
                    "• 3857 : Web Mercator (online tile maps)\n"
                    "• 4547 : CGCS2000 / 3-degree zone 114°E"
                )
            )
            return

        epsg_num = match.group(1)
        crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_num}")
        if not crs.isValid():
            QMessageBox.critical(
                self.dock_widget, tr("未找到坐标系", "CRS not found"),
                tr(
                    f"QGIS 数据库中不存在【EPSG:{epsg_num}】对应的坐标系！\n"
                    "请检查数字是否输错，或点击下方坐标系控件右侧的【地球图标】按名称搜索。",
                    f"No CRS matching [EPSG:{epsg_num}] exists in the QGIS database!\n"
                    "Check the number, or use the globe icon on the right of the CRS selector below to search by name."
                )
            )
            return

        self.crs_selector.setCrs(crs)
        self.iface.messageBar().pushMessage(
            tr("坐标系已切换", "CRS changed"), tr(f"当前定位坐标系已设为: {crs.authid()} - {crs.description()}", f"The locator CRS is now: {crs.authid()} - {crs.description()}"),
            level=Qgis.Success, duration=3
        )

    def on_crs_widget_changed(self, crs):
        """Keep the EPSG field in sync when the CRS is changed in the selector widget"""
        if crs and crs.isValid():
            auth_id = crs.authid()
            if auth_id.startswith("EPSG:"):
                self.txt_epsg.setText(auth_id.replace("EPSG:", ""))
            else:
                self.txt_epsg.setText(auth_id)

    def on_x_smart_paste(self, text):
        """Split '116.397, 39.908' into the X and Y fields when it is pasted into the X field"""
        if any(sep in text for sep in [',', '\uff0c', ';', '\uff1b', '\t']):
            parts = [p.strip() for p in re.split(r'[,\uff0c;\uff1b\t]+', text) if p.strip()]
            if len(parts) >= 2:
                self.txt_x.blockSignals(True)
                self.txt_x.setText(parts[0])
                self.txt_x.blockSignals(False)
                self.txt_y.setText(parts[1])

    def paste_from_clipboard(self):
        """Read the system clipboard and split it into X and Y coordinates"""
        clip_text = QApplication.clipboard().text().strip()
        if not clip_text:
            QMessageBox.warning(self.dock_widget, tr("剪贴板为空", "Clipboard is empty"), tr("当前系统剪贴板中没有文本内容！", "The system clipboard contains no text!"))
            return

        # Accept commas, semicolons, tabs or spaces as separators
        parts = [p.strip() for p in re.split(r'[,\uff0c;\uff1b\t\s]+', clip_text) if p.strip()]
        if len(parts) >= 2:
            self.txt_x.blockSignals(True)
            self.txt_x.setText(parts[0])
            self.txt_x.blockSignals(False)
            self.txt_y.setText(parts[1])
            self.iface.messageBar().pushMessage(tr("粘贴成功", "Pasted"), tr(f"已自动拆分坐标 X={parts[0]}, Y={parts[1]}", f"Coordinates split into X={parts[0]}, Y={parts[1]}"), level=Qgis.Info, duration=2)
        else:
            QMessageBox.warning(
                self.dock_widget, tr("解析失败", "Could not parse"),
                tr(f"剪贴板内容为：“{clip_text[:40]}”\n未能识别出成对的 X、Y 坐标（请用逗号或空格分隔两个坐标值）。", f"Clipboard content: '{clip_text[:40]}'\nNo pair of X and Y values was found (separate the two values with a comma or a space).")
            )

    def copy_to_clipboard(self):
        """Copy the coordinates in the input fields to the clipboard"""
        x_str = self.txt_x.text().strip()
        y_str = self.txt_y.text().strip()
        if not x_str or not y_str:
            self.iface.messageBar().pushMessage(tr("提示", "Notice"), tr("当前坐标输入框为空，无法复制", "The coordinate fields are empty, nothing to copy"), level=Qgis.Warning, duration=2)
            return
        QApplication.clipboard().setText(f"{x_str}, {y_str}")
        self.iface.messageBar().pushMessage(tr("复制成功", "Copied"), tr(f"已复制坐标: {x_str}, {y_str}", f"Coordinates copied: {x_str}, {y_str}"), level=Qgis.Success, duration=2)

    def swap_xy(self):
        """Swap the contents of the X and Y fields"""
        x_val = self.txt_x.text()
        y_val = self.txt_y.text()
        self.txt_x.blockSignals(True)
        self.txt_x.setText(y_val)
        self.txt_x.blockSignals(False)
        self.txt_y.setText(x_val)

    def parse_single_coord(self, raw_str):
        """
        Parse a single coordinate string. Supported formats:
        1. Decimal degrees: 116.397128, -39.908
        2. DMS: 116°23'49.66", 116:23:49.66, E116°23'49" (Chinese degree/minute/second suffixes also work)
        Returns: (float_value, error_message)
        """
        s = raw_str.strip()
        if not s:
            return None, tr("输入内容为空", "The input is empty")

        # Detect a southern (S) or western (W) hemisphere marker
        sign = -1.0 if re.search(r'[sSwW\u5357\u897f\-]', s) else 1.0
        s_clean = re.sub(r'[nNeEsSwW\u5317\u5357\u4e1c\u897f\+]', '', s).strip()

        # 1. Try to parse it as a plain decimal number
        try:
            val = float(s_clean)
            if math.isnan(val) or math.isinf(val):
                return None, tr("数值无效 (NaN/Inf)", "Invalid value (NaN/Inf)")
            return val, None
        except ValueError:
            pass

        # 2. Try to parse it as DMS
        dms_match = re.match(
            r'^\s*(\d+(?:\.\d+)?)\s*[°\u5ea6:\uff1a\s]\s*(\d+(?:\.\d+)?)?\s*[\'\u2032\u5206:\uff1a\s]?\s*(\d+(?:\.\d+)?)?\s*[\"\u2033\u79d2]?\s*$',
            s_clean
        )
        if dms_match:
            deg = float(dms_match.group(1))
            minutes = float(dms_match.group(2)) if dms_match.group(2) else 0.0
            seconds = float(dms_match.group(3)) if dms_match.group(3) else 0.0
            if minutes >= 60 or seconds >= 60:
                return None, tr(f"度分秒格式中“分({minutes})”或“秒({seconds})”不能大于或等于 60！", f"In DMS the minutes ({minutes}) and seconds ({seconds}) cannot be 60 or more!")
            decimal_val = sign * (deg + minutes / 60.0 + seconds / 3600.0)
            return decimal_val, None

        return None, tr(f"无法识别的坐标格式：“{raw_str}”\n支持格式如：116.3971 或 116°23'49.5\"", f"Unrecognized coordinate format: '{raw_str}'\nSupported formats include 116.3971 or 116°23'49.5\"")

    def zoom_to_coordinate(self):
        """Core locator logic (layered input validation and dynamic coordinate transformation)"""
        # Check 1: make sure the selected CRS is valid
        source_crs = self.crs_selector.crs()
        if not source_crs or not source_crs.isValid():
            QMessageBox.critical(
                self.dock_widget, tr("坐标系无效", "Invalid CRS"),
                tr("当前未选择有效的坐标系！\n请先在上方输入有效的 EPSG 代码（如 4326）或从下拉框中选择坐标系。", "No valid CRS is selected!\nEnter a valid EPSG code above (for example 4326) or choose a CRS from the selector.")
            )
            return

        # Check 2: parse the X and Y inputs
        x_raw = self.txt_x.text().strip()
        y_raw = self.txt_y.text().strip()
        if not x_raw or not y_raw:
            QMessageBox.warning(self.dock_widget, tr("坐标缺失", "Missing coordinates"), tr("请同时输入 经度(X) 和 纬度(Y) 坐标值！", "Enter both the longitude (X) and latitude (Y) values!"))
            return

        x_val, err_x = self.parse_single_coord(x_raw)
        if err_x:
            QMessageBox.warning(self.dock_widget, tr("经度(X) 格式错误", "Invalid longitude (X)"), tr(f"【经度/X】解析失败：\n{err_x}", f"Could not parse [longitude/X]:\n{err_x}"))
            self.txt_x.setFocus()
            return

        y_val, err_y = self.parse_single_coord(y_raw)
        if err_y:
            QMessageBox.warning(self.dock_widget, tr("纬度(Y) 格式错误", "Invalid latitude (Y)"), tr(f"【纬度/Y】解析失败：\n{err_y}", f"Could not parse [latitude/Y]:\n{err_y}"))
            self.txt_y.setFocus()
            return

        # Check 3: range validation for geographic (degrees) and projected (metres) CRSs
        if source_crs.isGeographic():
            # Case 3A: longitude and latitude were entered the wrong way round (for example X=39.9, Y=116.4)
            if -90.0 <= x_val <= 90.0 and (90.0 < abs(y_val) <= 180.0):
                reply = QMessageBox.question(
                    self.dock_widget, tr("智能纠错：经纬度疑似填反", "Smart fix: longitude/latitude look swapped"),
                    tr(
                        f"检测到您输入的 X={x_val}，Y={y_val}。\n"
                        f"在地理坐标系下，纬度(Y)不能超过 ±90°。\n\n"
                        f"您是否不小心把【经度】和【纬度】填反了？\n"
                        f"点击【Yes】自动互换为 (经度:{y_val}, 纬度:{x_val}) 并立即跳转！",
                        f"You entered X={x_val}, Y={y_val}.\n"
                        f"In a geographic CRS the latitude (Y) cannot exceed ±90°.\n\n"
                        f"Did you swap longitude and latitude by mistake?\n"
                        f"Click Yes to swap them to (longitude: {y_val}, latitude: {x_val}) and zoom there immediately!"
                    ),
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.swap_xy()
                    x_val, y_val = y_val, x_val
                else:
                    return

            # Case 3B: projected metre values were entered in a geographic CRS (for example X=38456789, Y=3245678)
            if not (-180.0 <= x_val <= 180.0 and -90.0 <= y_val <= 90.0):
                QMessageBox.critical(
                    self.dock_widget, tr("坐标超出经纬度范围", "Coordinates outside the longitude/latitude range"),
                    tr(
                        f"当前选择的坐标系【{source_crs.authid()}】是地理坐标系（单位：度）：\n"
                        f"• 经度(X) 必须在 -180° ~ 180° 之间（当前为 {x_val}）\n"
                        f"• 纬度(Y) 必须在 -90° ~ 90° 之间（当前为 {y_val}）\n\n"
                        f"💡 提示：如果您输入的是米制平面坐标（如 2000 高斯投影坐标），"
                        f"请先在上方将坐标系切换为对应的投影坐标系（如 EPSG:4547）！",
                        f"The selected CRS [{source_crs.authid()}] is geographic (units: degrees):\n"
                        f"• Longitude (X) must be between -180° and 180° (currently {x_val})\n"
                        f"• Latitude (Y) must be between -90° and 90° (currently {y_val})\n\n"
                        f"💡 Tip: if you entered projected metre coordinates (such as CGCS2000 Gauss-Kruger),"
                        f"switch the CRS above to the matching projected CRS (for example EPSG:4547) first!"
                    )
                )
                return
        else:
            # Case 3C: a projected metre CRS is selected but the values look like degrees (116.39, 39.90)
            if -180.0 <= x_val <= 180.0 and -90.0 <= y_val <= 90.0 and (abs(x_val) > 0.01 or abs(y_val) > 0.01):
                reply = QMessageBox.question(
                    self.dock_widget, tr("坐标系单位提醒", "CRS unit reminder"),
                    tr(
                        f"您当前选择的【{source_crs.authid()} - {source_crs.description()}】是投影坐标系（单位：米），\n"
                        f"但您输入的数值 ({x_val}, {y_val}) 看起来像经纬度（单位：度）。\n\n"
                        f"• 点击【Yes】：自动帮您临时按 WGS84 经纬度 (EPSG:4326) 解析并跳转\n"
                        f"• 点击【No】：仍然强制按米制坐标跳转",
                        f"The selected CRS [{source_crs.authid()} - {source_crs.description()}] is projected (units: metres),\n"
                        f"but the values you entered ({x_val}, {y_val}) look like longitude/latitude (units: degrees).\n\n"
                        f"• Click Yes: treat them as WGS 84 longitude/latitude (EPSG:4326) and zoom there\n"
                        f"• Click No: force the zoom using the metre coordinates"
                    ),
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )
                if reply == QMessageBox.Cancel:
                    return
                elif reply == QMessageBox.Yes:
                    source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
                    self.crs_selector.setCrs(source_crs)

        # Check 4: run the dynamic transformation (selected CRS -> current canvas CRS)
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        input_pt = QgsPointXY(x_val, y_val)
        target_pt = input_pt

        if source_crs != canvas_crs and canvas_crs.isValid():
            try:
                transform = QgsCoordinateTransform(source_crs, canvas_crs, QgsProject.instance())
                target_pt = transform.transform(input_pt)
                if math.isnan(target_pt.x()) or math.isnan(target_pt.y()) or math.isinf(target_pt.x()) or math.isinf(target_pt.y()):
                    raise ValueError(tr("转换结果超出数学定义域 (NaN/Inf)", "The result is outside the mathematical domain (NaN/Inf)"))
            except (QgsCsException, Exception) as e:
                QMessageBox.critical(
                    self.dock_widget, tr("坐标投影转换失败", "Coordinate transformation failed"),
                    tr(
                        f"无法将坐标 ({x_val}, {y_val}) 从【{source_crs.authid()}】转换到当前画布坐标系【{canvas_crs.authid()}】！\n\n"
                        f"常见原因：输入的平面坐标横轴带号与所选分带坐标系不匹配，或测绘 X/Y（北方向/东方向）顺序填反。\n"
                        f"建议点击【⇄】按钮互换 X/Y 后重试。\n\n底层详情: {str(e)}",
                        f"Could not transform ({x_val}, {y_val}) from [{source_crs.authid()}] to the canvas CRS [{canvas_crs.authid()}]!\n\n"
                        f"Common causes: the zone number of the projected easting does not match the selected zoned CRS, or the survey X/Y (northing/easting) order is reversed.\n"
                        f"Try the [⇄] button to swap X/Y and then retry.\n\nDetails: {str(e)}"
                    )
                )
                return

        # 5. Move the canvas centre and apply the zoom scale
        canvas.setCenter(target_pt)
        scale_text = self.scale_combo.currentText()
        if "1:" in scale_text:
            try:
                target_scale = int(scale_text.split("1:")[1].replace(",", "").strip())
                canvas.zoomScale(target_scale)
            except Exception:
                pass
        canvas.refresh()

        # 6. Trigger the native QGIS flash animation and draw the crosshair marker
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
            tr("定位成功", "Located"),
            tr(f"已跳转至 ({x_val:.6f}, {y_val:.6f}) [{source_crs.authid()}]", f"Zoomed to ({x_val:.6f}, {y_val:.6f}) [{source_crs.authid()}]"),
            level=Qgis.Success, duration=3
        )

    def clear_markers(self):
        """Remove all crosshair location markers from the canvas"""
        canvas = self.iface.mapCanvas()
        for m in self.markers:
            try:
                canvas.scene().removeItem(m)
            except Exception:
                pass
        self.markers.clear()
        canvas.refresh()

    def toggle_map_picker(self, checked):
        """Enable or disable the click-to-pick coordinate tool"""
        canvas = self.iface.mapCanvas()
        if checked:
            self.prev_map_tool = canvas.mapTool()
            self.map_tool = QgsMapToolEmitPoint(canvas)
            self.map_tool.canvasClicked.connect(self.on_canvas_clicked)
            self.map_tool.deactivated.connect(lambda: self.btn_pick.setChecked(False))
            canvas.setMapTool(self.map_tool)
            self.btn_pick.setStyleSheet("background-color: #ffeaa7; color: #d63031; font-weight: bold;")
            self.iface.messageBar().pushMessage(tr("图面取点已开启", "Pick on canvas enabled"), tr("请在地图画布上左键单击任意位置拾取坐标", "Left-click anywhere on the map canvas to pick coordinates"), level=Qgis.Info, duration=3)
        else:
            if self.map_tool and canvas.mapTool() == self.map_tool:
                if self.prev_map_tool:
                    canvas.setMapTool(self.prev_map_tool)
                else:
                    canvas.unsetMapTool(self.map_tool)
            self.btn_pick.setStyleSheet("")

    def on_canvas_clicked(self, point, button):
        """Convert a click on the map canvas to the CRS selected above and fill in the fields"""
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
                QMessageBox.warning(self.dock_widget, tr("坐标反算失败", "Inverse transformation failed"), tr(f"无法将画布坐标转换到 {target_crs.authid()}:\n{e}", f"Could not transform the canvas coordinate to {target_crs.authid()}:\n{e}"))
                return

        # 6 decimals for a geographic CRS, 3 for a projected one
        decimals = 6 if target_crs.isGeographic() else 3
        self.txt_x.blockSignals(True)
        self.txt_x.setText(f"{out_pt.x():.{decimals}f}")
        self.txt_x.blockSignals(False)
        self.txt_y.setText(f"{out_pt.y():.{decimals}f}")

        # Mark the clicked point
        self.clear_markers()
        if self.chk_keep_marker.isChecked():
            marker = QgsVertexMarker(canvas)
            marker.setCenter(point)
            marker.setColor(QColor(255, 0, 0))
            marker.setIconType(QgsVertexMarker.ICON_CROSS)
            marker.setIconSize(18)
            marker.setPenWidth(3)
            self.markers.append(marker)

        # Restore the previous pan tool once the point has been picked
        self.btn_pick.setChecked(False)
        self.toggle_map_picker(False)

    # =================================================================
    # Logic B: table to points and batch map export (cross-CRS rendering supported)
    # =================================================================
    def excel_choose_file(self):
        if pd is None:
            QMessageBox.critical(self.dock_widget, tr("环境缺失", "Missing dependency"),
                                 tr("当前 QGIS 环境未安装 pandas！\n 请打开 OSGeo4W Shell 执行: pip install pandas", "pandas is not installed in this QGIS environment!\n Open the OSGeo4W Shell and run: pip install pandas"))
            return

        file_path, _ = QFileDialog.getOpenFileName(self.dock_widget, tr("选择表格文件", "Choose table file"),
                                                   "", "Excel & CSV Files (*.xlsx *.xls *.csv)")
        if file_path:
            self.excel_txt_file.setText(file_path)
            try:
                if file_path.endswith('.csv'):
                    self.excel_df = pd.read_csv(file_path)
                else:
                    self.excel_df = pd.read_excel(file_path)

                columns = [tr("-- 默认 自动命名 --", "-- Auto-name (default) --")] + list(self.excel_df.columns.astype(str))
                self.lon_combo.clear()
                self.lat_combo.clear()
                self.name_combo.clear()

                self.lon_combo.addItems(list(self.excel_df.columns.astype(str)))
                self.lat_combo.addItems(list(self.excel_df.columns.astype(str)))
                self.name_combo.addItems(columns)

                for col in self.excel_df.columns:
                    col_lower = str(col).lower()
                    if any(k in col_lower for k in ['lon', '\u7ecf\u5ea6', 'x']):
                        self.lon_combo.setCurrentText(str(col))
                    if any(k in col_lower for k in ['lat', '\u7eac\u5ea6', 'y']):
                        self.lat_combo.setCurrentText(str(col))

                self.iface.messageBar().pushMessage(tr("成功", "Success"), tr(f"成功读取表格，共 {len(self.excel_df)} 行数据", f"Table loaded, {len(self.excel_df)} rows"), level=0,
                                                    duration=3)
            except Exception as e:
                QMessageBox.critical(self.dock_widget, tr("错误", "Error"), tr(f"读取表格失败:\n{str(e)}", f"Failed to read the table:\n{str(e)}"))

    def excel_choose_vector_save(self):
        path, _ = QFileDialog.getSaveFileName(self.dock_widget, tr("保存点矢量", "Save point layer"), "", "ESRI Shapefile (*.shp)")
        if path:
            if not path.endswith('.shp'):
                path += '.shp'
            self.vector_path_txt.setText(path)

    def excel_choose_img_folder(self):
        folder = QFileDialog.getExistingDirectory(self.dock_widget, tr("选择图片集保存文件夹", "Choose folder for the image set"))
        if folder:
            self.img_dir_txt.setText(folder)

    def clean_coordinate_string(self, val):
        if pd.isna(val):
            return None
        val_parsed, err = self.parse_single_coord(str(val))
        return val_parsed

    def excel_run_task(self):
        if self.excel_df is None:
            QMessageBox.warning(self.dock_widget, tr("提示", "Notice"), tr("请先选择并加载有效的表格文件！", "Choose and load a valid table file first!"))
            return

        lon_col = self.lon_combo.currentText()
        lat_col = self.lat_combo.currentText()
        name_col = self.name_combo.currentText()

        if not lon_col or not lat_col:
            QMessageBox.warning(self.dock_widget, tr("提示", "Notice"), tr("请指定经度和纬度所在的列！", "Specify the columns that hold the longitude and latitude!"))
            return

        source_crs = self.crs_selector.crs()
        if not source_crs or not source_crs.isValid():
            source_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        valid_points = []
        for index, row in self.excel_df.iterrows():
            lon = self.clean_coordinate_string(row[lon_col])
            lat = self.clean_coordinate_string(row[lat_col])

            if lon is not None and lat is not None:
                # Validate the lon/lat range for a geographic CRS; projected coordinates pass straight through
                if source_crs.isGeographic() and not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    continue

                if name_col != tr("-- 默认 自动命名 --", "-- Auto-name (default) --") and name_col in self.excel_df.columns:
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
                self.dock_widget, tr("错误", "Error"),
                tr(f"没有清洗出任何有效的点位！\n请检查字段匹配，以及上方所选的坐标系（当前：{source_crs.authid()}）是否与表格数据一致。", f"No valid points were extracted!\nCheck the field mapping and whether the CRS selected above (currently: {source_crs.authid()}) matches the table data.")
            )
            return

        # 2. Also export the point layer to a local file (SHP) if that option is checked
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
                print(tr(f"导出SHP出错: {e}", f"Error exporting the SHP: {e}"))

        # 3. Batch export the image set (automatically adapted to the canvas CRS)
        if self.chk_export_images.isChecked():
            out_dir = self.img_dir_txt.text()
            if not out_dir:
                QMessageBox.warning(self.dock_widget, tr("警告", "Warning"), tr("请先选择图片集保存文件夹！", "Choose the folder for the image set first!"))
                return
            os.makedirs(out_dir, exist_ok=True)

            margin_percent = self.spin_margin.value() / 100.0
            dpi_text = self.dpi_combo.currentText()
            dpi = 300 if "300" in dpi_text else (150 if "150" in dpi_text else 96)

            self.btn_excel_run.setEnabled(False)
            self.btn_excel_run.setText(tr("⏳ 正在根据表格坐标与可见图层批量出图...", "⏳ Rendering maps for the table coordinates and visible layers..."))
            success_count = 0

            canvas = self.iface.mapCanvas()
            canvas_crs = canvas.mapSettings().destinationCrs()
            need_transform = (source_crs != canvas_crs and canvas_crs.isValid())
            if need_transform:
                transform = QgsCoordinateTransform(source_crs, canvas_crs, QgsProject.instance())

            # Adaptive base view radius: 0.0015 degrees for a geographic canvas, 150 metres for a projected one
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
            self.btn_excel_run.setText(tr("📋 开始清洗数据、建点与出图", "📋 Clean data, build points and export maps"))
            QMessageBox.information(self.dock_widget, tr("导出完成", "Export finished"),
                                    tr(f"成功处理 {len(valid_points)} 个坐标点\n成功基于当前可见图层导出图片: {success_count} 张\n路径: {out_dir}", f"Processed {len(valid_points)} coordinate points\nRendered {success_count} images from the currently visible layers\nFolder: {out_dir}"))
        else:
            QMessageBox.information(self.dock_widget, tr("完成", "Done"), tr(f"已成功解析 {len(valid_points)} 个坐标点数据！", f"Parsed {len(valid_points)} coordinate points successfully!"))