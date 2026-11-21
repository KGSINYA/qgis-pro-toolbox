# -*- coding: utf-8 -*-
import os
import json
import time
import ctypes
from ctypes import wintypes

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QCheckBox

from base_addon import BaseAddon, tr

# ---------- Windows low-level key hooks and simulated input ----------
IS_WINDOWS = os.name == "nt"
# user32 exists only on Windows; on other platforms the module is flagged as a non-addon and the host skips it
user32 = ctypes.WinDLL('user32', use_last_error=True) if IS_WINDOWS else None
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_NUMPAD = {1: 0x61, 2: 0x62, 3: 0x63, 4: 0x64, 5: 0x65}

class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p))

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT), ("mi", ctypes.c_byte * 28), ("hi", ctypes.c_byte * 32))

    _anonymous_ = ("_input",)
    _fields_ = (("type", wintypes.DWORD), ("_input", _INPUT))

def release_modifier_keys():
    inputs = (INPUT * 6)()
    for i, vk in enumerate([VK_SHIFT, VK_CONTROL, VK_MENU]):
        inputs[i].type, inputs[i].ki.wVk, inputs[i].ki.dwFlags = INPUT_KEYBOARD, vk, KEYEVENTF_KEYUP
    user32.SendInput(3, ctypes.byref(inputs), ctypes.sizeof(INPUT))

def send_virtual_input(text, auto_enter=False, delay_ms=5):
    release_modifier_keys()
    time.sleep(0.02)
    delay_sec = delay_ms / 1000.0
    for char in text:
        inputs = (INPUT * 2)()
        if char == '\n':
            inputs[0].type, inputs[0].ki.wVk, inputs[0].ki.dwFlags = INPUT_KEYBOARD, VK_RETURN, 0
            inputs[1].type, inputs[1].ki.wVk, inputs[1].ki.dwFlags = INPUT_KEYBOARD, VK_RETURN, KEYEVENTF_KEYUP
        else:
            inputs[0].type, inputs[0].ki.wVk, inputs[0].ki.wScan, inputs[0].ki.dwFlags = INPUT_KEYBOARD, 0, ord(
                char), KEYEVENTF_UNICODE
            inputs[1].type, inputs[1].ki.wVk, inputs[1].ki.wScan, inputs[1].ki.dwFlags = INPUT_KEYBOARD, 0, ord(
                char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        if delay_sec > 0:
            time.sleep(delay_sec)
    if auto_enter:
        inputs = (INPUT * 2)()
        inputs[0].type, inputs[0].ki.wVk, inputs[0].ki.dwFlags = INPUT_KEYBOARD, VK_RETURN, 0
        inputs[1].type, inputs[1].ki.wVk, inputs[1].ki.dwFlags = INPUT_KEYBOARD, VK_RETURN, KEYEVENTF_KEYUP
        user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))

class HotkeyThread(QThread):
    macro_triggered = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.is_running = True

    def run(self):
        for i in range(1, 6):
            user32.RegisterHotKey(None, i, 0, VK_NUMPAD[i])
        msg = wintypes.MSG()
        while self.is_running:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_HOTKEY:
                    self.macro_triggered.emit(msg.wParam)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.01)
        for i in range(1, 6):
            user32.UnregisterHotKey(None, i)

    def stop(self):
        self.is_running = False
        self.wait()

# ---------- Addon body ----------
class NumpadMacroAddon(BaseAddon):
    title = tr("⚡ 快捷输入", "⚡ Quick Input")
    order = 3
    # Hide this addon entirely on non-Windows platforms (the host filters on _is_pro_addon)
    _is_pro_addon = IS_WINDOWS

    def __init__(self, iface, dock_widget, plugin_dir):
        super().__init__(iface, dock_widget, plugin_dir)
        self.shortcut_thread = None
        self.text_boxes = {}
        self.active_macros = {}
        self.config_file = os.path.join(self.plugin_dir, "numpad_macro_config.json")

    def unload(self):
        if self.shortcut_thread and self.shortcut_thread.isRunning():
            self.shortcut_thread.stop()
            self.shortcut_thread = None

    def setup_ui(self, parent_widget):
        layout = QVBoxLayout(parent_widget)
        layout.setContentsMargins(10, 10, 10, 10)

        for i in range(1, 6):
            h_layout = QHBoxLayout()
            lbl = QLabel(tr(f"数字键 {i}", f"Key {i}"))
            lbl.setFixedWidth(50)
            txt = QTextEdit()
            txt.setFixedHeight(45)
            txt.setPlaceholderText(tr(f"小键盘 {i} 输出内容...", f"Numpad {i} output..."))
            self.text_boxes[i] = txt

            h_layout.addWidget(lbl)
            h_layout.addWidget(txt)
            layout.addLayout(h_layout)

        self.auto_enter_chk = QCheckBox(tr("输出完毕后自动发送【回车键】", "Press Enter automatically after sending"))
        layout.addWidget(self.auto_enter_chk)
        layout.addSpacing(5)

        btn_layout = QHBoxLayout()
        self.btn_macro_toggle = QPushButton(tr("▶ 启动快捷服务", "▶ Start hotkey service"))
        self.btn_macro_toggle.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        self.btn_macro_toggle.clicked.connect(self.toggle_macro)

        btn_macro_save = QPushButton(tr("💾 保存配置", "💾 Save configuration"))
        btn_macro_save.setStyleSheet("padding: 8px;")
        btn_macro_save.clicked.connect(self.save_macro_config)

        btn_layout.addWidget(self.btn_macro_toggle)
        btn_layout.addWidget(btn_macro_save)
        layout.addLayout(btn_layout)

        self.macro_status_lbl = QLabel(tr("⚫ 当前状态: 休眠中", "⚫ Status: idle"))
        self.macro_status_lbl.setStyleSheet("color: gray; font-weight: bold; margin-top: 10px;")
        self.macro_status_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.macro_status_lbl)
        layout.addStretch()
        self.load_macro_config()

    def toggle_macro(self):
        if self.shortcut_thread is None or not self.shortcut_thread.isRunning():
            self.save_macro_config()
            self.active_macros.clear()
            for i, box in self.text_boxes.items():
                self.active_macros[i] = box.toPlainText()

            self.shortcut_thread = HotkeyThread()
            self.shortcut_thread.macro_triggered.connect(self.execute_macro)
            self.shortcut_thread.start()

            self.btn_macro_toggle.setText(tr("⏹ 停止快捷服务", "⏹ Stop hotkey service"))
            self.btn_macro_toggle.setStyleSheet(
                "background-color: #f44336; color: white; font-weight: bold; padding: 8px;")
            self.macro_status_lbl.setText(tr("🟢 当前状态: 运行中 (小键盘拦截已开启)", "🟢 Status: running (numpad capture enabled)"))
            self.macro_status_lbl.setStyleSheet("color: #4CAF50; font-weight: bold; margin-top: 10px;")
            for box in self.text_boxes.values():
                box.setEnabled(False)
        else:
            self.shortcut_thread.stop()
            self.shortcut_thread = None

            self.btn_macro_toggle.setText(tr("▶ 启动快捷服务", "▶ Start hotkey service"))
            self.btn_macro_toggle.setStyleSheet(
                "background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
            self.macro_status_lbl.setText(tr("⚫ 当前状态: 休眠中", "⚫ Status: idle"))
            self.macro_status_lbl.setStyleSheet("color: gray; font-weight: bold; margin-top: 10px;")
            for box in self.text_boxes.values():
                box.setEnabled(True)

    def execute_macro(self, hotkey_id):
        text = self.active_macros.get(hotkey_id, "")
        if text:
            send_virtual_input(text, self.auto_enter_chk.isChecked(), delay_ms=5)

    def save_macro_config(self):
        data = {
            "auto_enter": self.auto_enter_chk.isChecked(),
            "macros": {str(k): v.toPlainText() for k, v in self.text_boxes.items()}
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.iface.messageBar().pushMessage(tr("成功", "Success"), tr("快捷输入配置已保存", "Quick input configuration saved"), level=0, duration=2)
        except Exception:
            pass

    def load_macro_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.auto_enter_chk.setChecked(data.get("auto_enter", False))
                macros = data.get("macros", {})
                for k, v in macros.items():
                    key_id = int(k)
                    if key_id in self.text_boxes:
                        self.text_boxes[key_id].setPlainText(v)
            except Exception:
                pass