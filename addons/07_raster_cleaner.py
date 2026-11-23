# -*- coding: utf-8 -*-
"""
07_raster_cleaner.py - Raster batch processing with smart black/white border removal.
Follows the BaseAddon interface used by ProToolboxPlugin (main.py) exactly:
  - order = 7
  - title = tr(...)
  - __init__(self, iface, dock_widget, plugin_dir)
  - setup_ui(self, parent_widget)
  - unload(self)
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QLineEdit, QCheckBox, QComboBox, QSlider,
    QRadioButton, QMessageBox, QSpinBox
)
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsRasterRange,
    QgsRasterTransparency, QgsContrastEnhancement,
    QgsBilinearRasterResampler, QgsCubicRasterResampler,
    Qgis
)

from base_addon import BaseAddon, tr

class RasterCleanerAddon(BaseAddon):
    order = 7
    title = tr("🖼️ 影像去黑边", "🖼️ Raster NoData")

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.title = tr("🖼️ 影像去黑边", "🖼️ Raster NoData")
        self.auto_clean_enabled = False
        self._signal_connected = False

    def setup_ui(self, parent_widget):
        """Mount all widgets directly onto the tab_widget passed in by main.py."""
        layout = QVBoxLayout(parent_widget)
        layout.setSpacing(10)

        # ==================== 1. Target scope ====================
        scope_group = QGroupBox(tr("🎯 1. 批量处理作用范围", "🎯 1. Target Raster Scope"))
        scope_layout = QHBoxLayout(scope_group)

        self.rb_all = QRadioButton(tr("工程中所有栅格影像 (TIF等)", "All Raster Layers in Project"))
        self.rb_selected = QRadioButton(tr("仅图层树中选中的栅格", "Only Selected Raster Layers"))
        self.rb_all.setChecked(True)

        scope_layout.addWidget(self.rb_all)
        scope_layout.addWidget(self.rb_selected)
        layout.addWidget(scope_group)

        # ==================== 2. Core feature: batch remove black/white borders ====================
        nodata_group = QGroupBox(tr("✂️ 2. 批量去除影像黑边 / 背景值 (NoData)", "✂️ 2. Batch Remove Black/White Borders (NoData)"))
        nodata_layout = QVBoxLayout(nodata_group)

        # Preset quick values + custom input
        val_layout = QHBoxLayout()
        val_layout.addWidget(QLabel(tr("背景像素值:", "Background Value:")))

        self.combo_preset = QComboBox()
        self.combo_preset.addItems([
            tr("0 (标准黑边 - 最常用)", "0 (Black Border - Common)"),
            tr("255 (标准白边)", "255 (White Border)"),
            tr("-9999 (DEM/高程异常值)", "-9999 (DEM NoData)"),
            tr("自定义数值...", "Custom Value...")
        ])
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        val_layout.addWidget(self.combo_preset, 1)

        self.edit_val = QLineEdit("0")
        self.edit_val.setFixedWidth(80)
        self.edit_val.setPlaceholderText(tr("输入数值", "Value"))
        val_layout.addWidget(self.edit_val)
        nodata_layout.addLayout(val_layout)

        # Mode: additional NoData value vs exact RGB transparency list (avoids dark speckles)
        self.chk_nodata_attr = QCheckBox(
            tr("设为附加无数据值 (等同于在符号系统手动填 0)",
               "Set as Additional NoData value (Band NoData = 0)")
        )
        self.chk_nodata_attr.setChecked(True)
        nodata_layout.addWidget(self.chk_nodata_attr)

        self.chk_rgb_exact = QCheckBox(
            tr("同时注入 RGB 透明像素表 (防彩色影像内部单波段为 0 出现透明麻点)",
               "Add to RGB Transparency Pixel List (Prevent inner dark-pixel holes)")
        )
        self.chk_rgb_exact.setChecked(True)
        nodata_layout.addWidget(self.chk_rgb_exact)

        # Tolerance (lossy-compressed TIF borders are often 1~5, not pure 0)
        tol_layout = QHBoxLayout()
        tol_layout.addWidget(QLabel(tr("压缩杂边容差 (0~15, 清除黑边残留灰黑毛刺):", "Border Tolerance (0~15 for lossy edges):")))
        self.spin_tol = QSpinBox()
        self.spin_tol.setRange(0, 50)
        self.spin_tol.setValue(0)
        tol_layout.addWidget(self.spin_tol)
        tol_layout.addStretch()
        nodata_layout.addLayout(tol_layout)

        # Apply and reset buttons
        btn_layout = QHBoxLayout()
        self.btn_apply_nodata = QPushButton(tr("🚀 一键批量去黑边/背景值", "🚀 Batch Remove Background Now"))
        self.btn_apply_nodata.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; font-weight: bold; padding: 7px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1B5E20; }"
        )
        self.btn_apply_nodata.clicked.connect(self.batch_remove_background)

        self.btn_reset_nodata = QPushButton(tr("🔄 恢复原始背景", "🔄 Reset Background"))
        self.btn_reset_nodata.setStyleSheet("padding: 7px;")
        self.btn_reset_nodata.clicked.connect(self.batch_reset_background)

        btn_layout.addWidget(self.btn_apply_nodata, 2)
        btn_layout.addWidget(self.btn_reset_nodata, 1)
        nodata_layout.addLayout(btn_layout)

        # Auto-watch toggle
        self.chk_auto_watch = QCheckBox(
            tr("⚡ 开启后台哨兵：后续新拖入 QGIS 的 TIF 影像自动去黑边",
               "⚡ Auto-Watch: Automatically remove black border for newly added TIFs")
        )
        self.chk_auto_watch.setStyleSheet("color: #D97706; font-weight: bold; margin-top: 4px;")
        self.chk_auto_watch.toggled.connect(self._toggle_auto_watch)
        nodata_layout.addWidget(self.chk_auto_watch)

        layout.addWidget(nodata_group)

        # ==================== 3. Advanced: image smoothing and color stretch ====================
        enhance_group = QGroupBox(tr("✨ 3. 影像画质增强与平滑渲染 (解决灰暗/马赛克)", "✨ 3. Quality Enhancement & Smooth Resampling"))
        enhance_layout = QVBoxLayout(enhance_group)

        # 3.1 Resampling smoothness
        resamp_layout = QHBoxLayout()
        resamp_layout.addWidget(QLabel(tr("放大抗锯齿:", "Zoom Resampling:")))
        self.combo_resamp = QComboBox()
        self.combo_resamp.addItems([
            tr("双线性平滑 (Bilinear - 推荐，消除锯齿)", "Bilinear (Smooth - Recommended)"),
            tr("立方卷积 (Cubic - 最清晰柔和)", "Cubic (Sharp & Smooth)"),
            tr("最近邻 (Nearest - 原始像素马赛克)", "Nearest Neighbour (Raw Pixels)")
        ])
        resamp_layout.addWidget(self.combo_resamp, 1)

        btn_resamp = QPushButton(tr("应用平滑", "Apply Smooth"))
        btn_resamp.clicked.connect(self.batch_apply_resampling)
        resamp_layout.addWidget(btn_resamp)
        enhance_layout.addLayout(resamp_layout)

        # 3.2 Automatic contrast stretch
        btn_stretch = QPushButton(tr("☀️ 批量最小-最大色彩高亮拉伸 (拯救灰暗遥感图)", "☀️ Batch MinMax Contrast Stretch (Fix Dark Rasters)"))
        btn_stretch.clicked.connect(self.batch_stretch_contrast)
        enhance_layout.addWidget(btn_stretch)

        # 3.3 Batch overall opacity slider
        opa_layout = QHBoxLayout()
        opa_layout.addWidget(QLabel(tr("批量整体不透明度:", "Batch Opacity:")))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.setValue(100)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setFixedWidth(40)
        self.slider_opacity.valueChanged.connect(lambda v: self.lbl_opacity.setText(f"{v}%"))

        btn_opa = QPushButton(tr("同步透明度", "Sync Opacity"))
        btn_opa.clicked.connect(self.batch_set_opacity)

        opa_layout.addWidget(self.slider_opacity, 1)
        opa_layout.addWidget(self.lbl_opacity)
        opa_layout.addWidget(btn_opa)
        enhance_layout.addLayout(opa_layout)

        layout.addWidget(enhance_group)
        layout.addStretch()

    def unload(self):
        """Safely disconnect background signal listeners on unload or hot reload."""
        if self._signal_connected:
            try:
                QgsProject.instance().layersAdded.disconnect(self._on_layers_added)
            except Exception:
                pass
            self._signal_connected = False

    # ==================== Internal logic ====================
    def _on_preset_changed(self, idx):
        presets = ["0", "255", "-9999"]
        if idx < len(presets):
            self.edit_val.setText(presets[idx])

    def _get_target_rasters(self):
        """Return the list of target raster layers."""
        if self.rb_selected.isChecked():
            layers = self.iface.layerTreeView().selectedLayers()
        else:
            layers = list(QgsProject.instance().mapLayers().values())
        return [lyr for lyr in layers if isinstance(lyr, QgsRasterLayer) and lyr.isValid()]

    def _clean_single_raster(self, lyr: QgsRasterLayer, bg_val: float, tol: int = 0,
                             use_nodata_attr: bool = True, use_rgb_list: bool = True):
        """Remove the background value from a single raster layer."""
        provider = lyr.dataProvider()
        renderer = lyr.renderer()
        if not provider or not renderer:
            return False

        # 1. Set provider-level additional NoData value (Layer Properties -> Transparency -> Additional NoData Value)
        if use_nodata_attr:
            r_range = QgsRasterRange(bg_val - tol, bg_val + tol)
            for band in range(1, lyr.bandCount() + 1):
                provider.setUseSourceNoDataValue(band, True)
                provider.setUserNoDataValue(band, [r_range])
        else:
            for band in range(1, lyr.bandCount() + 1):
                provider.setUserNoDataValue(band, [])

        # 2. Set renderer transparency pixel list
        if use_rgb_list:
            rt = QgsRasterTransparency()
            band_count = lyr.bandCount()
            if band_count >= 3:
                px_list = []
                if tol == 0:
                    px = QgsRasterTransparency.TransparentThreeValuePixel()
                    px.red = bg_val
                    px.green = bg_val
                    px.blue = bg_val
                    px.percentTransparent = 100.0
                    px_list.append(px)
                else:
                    step = 1 if tol <= 5 else max(1, tol // 4)
                    for v in range(max(0, int(bg_val - tol)), int(bg_val + tol) + 1, step):
                        px = QgsRasterTransparency.TransparentThreeValuePixel()
                        px.red = float(v)
                        px.green = float(v)
                        px.blue = float(v)
                        px.percentTransparent = 100.0
                        px_list.append(px)
                rt.setTransparentThreeValuePixelList(px_list)
            else:
                px = QgsRasterTransparency.TransparentSingleValuePixel()
                px.min = bg_val - tol
                px.max = bg_val + tol
                px.percentTransparent = 100.0
                rt.setTransparentSingleValuePixelList([px])

            renderer.setRasterTransparency(rt)

        lyr.triggerRepaint()
        return True

    def batch_remove_background(self):
        rasters = self._get_target_rasters()
        if not rasters:
            self.iface.messageBar().pushMessage(
                tr("提示", "Info"),
                tr("未找到可处理的栅格影像(TIF)图层！", "No target raster layers found!"),
                level=Qgis.Warning, duration=3
            )
            return

        try:
            bg_val = float(self.edit_val.text().strip())
        except ValueError:
            QMessageBox.warning(self.dock_widget, tr("参数错误", "Invalid Input"),
                                tr("请输入有效的数字背景值（如 0 或 255）！", "Please enter a valid number (e.g., 0 or 255)!"))
            return

        tol = self.spin_tol.value()
        use_nodata = self.chk_nodata_attr.isChecked()
        use_rgb = self.chk_rgb_exact.isChecked()

        count = 0
        for lyr in rasters:
            if self._clean_single_raster(lyr, bg_val, tol, use_nodata, use_rgb):
                count += 1

        self.iface.mapCanvas().refreshAllLayers()
        self.iface.messageBar().pushMessage(
            tr("去黑边成功", "Success"),
            tr(f"已批量去除 {count} 个栅格图层的背景值 ({bg_val})！",
               f"Successfully removed background ({bg_val}) for {count} raster layers!"),
            level=Qgis.Success, duration=4
        )

    def batch_reset_background(self):
        rasters = self._get_target_rasters()
        if not rasters:
            return
        for lyr in rasters:
            provider = lyr.dataProvider()
            renderer = lyr.renderer()
            if provider:
                for band in range(1, lyr.bandCount() + 1):
                    provider.setUserNoDataValue(band, [])
            if renderer:
                renderer.setRasterTransparency(QgsRasterTransparency())
            lyr.triggerRepaint()

        self.iface.mapCanvas().refreshAllLayers()
        self.iface.messageBar().pushMessage(
            tr("已恢复", "Reset"),
            tr(f"已清除 {len(rasters)} 个栅格图层的附加透明背景设置。",
               f"Cleared custom transparency for {len(rasters)} raster layers."),
            level=Qgis.Info, duration=3
        )

    def _toggle_auto_watch(self, checked):
        self.auto_clean_enabled = checked
        if checked and not self._signal_connected:
            QgsProject.instance().layersAdded.connect(self._on_layers_added)
            self._signal_connected = True
            self.iface.messageBar().pushMessage(
                tr("自动去黑边已开启", "Auto-Clean Enabled"),
                tr("现在拖入 QGIS 的任何新 TIF 影像都将自动去除背景值！",
                   "Newly added raster layers will automatically have background removed!"),
                level=Qgis.Success, duration=3
            )

    def _on_layers_added(self, layers):
        if not self.auto_clean_enabled:
            return
        try:
            bg_val = float(self.edit_val.text().strip())
        except ValueError:
            bg_val = 0.0
        tol = self.spin_tol.value()

        cleaned = 0
        for lyr in layers:
            if isinstance(lyr, QgsRasterLayer) and lyr.isValid():
                self._clean_single_raster(
                    lyr, bg_val, tol,
                    self.chk_nodata_attr.isChecked(),
                    self.chk_rgb_exact.isChecked()
                )
                cleaned += 1
        if cleaned > 0:
            self.iface.messageBar().pushMessage(
                tr("自动去黑边", "Auto NoData"),
                tr(f"已自动为新导入的 {cleaned} 个影像去除黑边 (值={bg_val})！",
                   f"Auto-removed border ({bg_val}) for {cleaned} new raster(s)!"),
                level=Qgis.Info, duration=3
            )

    def batch_apply_resampling(self):
        rasters = self._get_target_rasters()
        if not rasters:
            return
        idx = self.combo_resamp.currentIndex()
        for lyr in rasters:
            pipe = lyr.pipe()
            if not pipe or not pipe.resampler():
                continue
            resampler = pipe.resampler()
            if idx == 0:
                resampler.setZoomedInResampler(QgsBilinearRasterResampler())
                resampler.setZoomedOutResampler(QgsBilinearRasterResampler())
            elif idx == 1:
                resampler.setZoomedInResampler(QgsCubicRasterResampler())
                resampler.setZoomedOutResampler(QgsBilinearRasterResampler())
            else:
                resampler.setZoomedInResampler(None)
                resampler.setZoomedOutResampler(None)
            lyr.triggerRepaint()

        self.iface.mapCanvas().refreshAllLayers()
        self.iface.messageBar().pushMessage(
            tr("平滑已应用", "Resampling Applied"),
            tr(f"已更新 {len(rasters)} 个影像的重采样平滑渲染模式！",
               f"Updated resampling mode for {len(rasters)} raster layers!"),
            level=Qgis.Success, duration=3
        )

    def batch_stretch_contrast(self):
        rasters = self._get_target_rasters()
        if not rasters:
            return
        count = 0
        for lyr in rasters:
            lyr.setContrastEnhancement(QgsContrastEnhancement.StretchToMinimumMaximum)
            lyr.triggerRepaint()
            count += 1
        self.iface.mapCanvas().refreshAllLayers()
        self.iface.messageBar().pushMessage(
            tr("色彩拉伸完成", "Contrast Stretched"),
            tr(f"已对 {count} 个栅格图层执行动态对比度高亮拉伸！",
               f"Applied contrast enhancement to {count} raster layers!"),
            level=Qgis.Success, duration=3
        )

    def batch_set_opacity(self):
        rasters = self._get_target_rasters()
        if not rasters:
            return
        opacity = self.slider_opacity.value() / 100.0
        for lyr in rasters:
            if lyr.renderer():
                lyr.renderer().setOpacity(opacity)
                lyr.triggerRepaint()
        self.iface.mapCanvas().refreshAllLayers()