from datetime import datetime
import re
import os
import json
import subprocess
import urllib.request
import urllib.parse
import sys
import platform
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTextEdit, QLineEdit,
                             QComboBox, QLabel, QMessageBox, QSplitter,
                             QGroupBox, QCheckBox, QMenu)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QFont, QPalette

# ==========================================
# КОНСТАНТЫ И ПУТИ
# ==========================================
def get_base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_app_data_dir() -> str:
    system = platform.system()
    if system == 'Windows':
        appdata = os.getenv('APPDATA') or os.path.expanduser('~\\AppData\\Roaming')
        data_dir = os.path.join(appdata, 'BobcatProxyNaive')
    else:
        xdg_config = os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        data_dir = os.path.join(xdg_config, 'BobcatProxyNaive')
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

DATA_DIR = get_app_data_dir()
BASE_DIR = get_base_dir()

NAIVE_CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
NAIVE_BINARY_NAME = "naive"
KEYS_DB_PATH = os.path.join(DATA_DIR, "configs.json")

LOCAL_PROXY_HOST = "127.0.0.1"
LOCAL_PROXY_PORT = 25443

# ==========================================
# ОПРЕДЕЛЕНИЕ ТЕМЫ
# ==========================================
def get_system_theme() -> str:
    try:
        app = QApplication.instance()
        if app and app.palette().color(QPalette.ColorRole.Window).lightness() < 128:
            return 'dark'
    except Exception:
        pass
    return 'light'

# ==========================================
# УТИЛИТЫ
# ==========================================
def load_json_file(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json_file(path: str, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def normalize_key(key_string: str) -> str:
    """Нормализует ключ для сравнения (без фрагмента)."""
    if '#' in key_string:
        return key_string.split('#')[0].strip()
    return key_string.strip()

def is_valid_naive_key(key_string: str) -> bool:
    """Проверяет валидность Naive ключа."""
    if not key_string.startswith("naive+"):
        return False
    url_part = key_string[6:]
    if not url_part.startswith("https://"):
        return False
    try:
        parsed = urllib.parse.urlparse(url_part)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        return True
    except Exception:
        return False

def parse_naive_key(key_string: str) -> Dict[str, str]:
    """Парсит Naive ключ для отображения."""
    result = {"host": "unknown", "port": "443", "hashtag": "", "url": ""}
    try:
        url_part = key_string[6:]
        if '#' in url_part:
            url_part, hashtag = url_part.split('#', 1)
            result["hashtag"] = urllib.parse.unquote(hashtag)
        parsed = urllib.parse.urlparse(url_part)
        result["host"] = parsed.hostname or "unknown"
        result["port"] = str(parsed.port or 443)
        result["url"] = url_part
        if not result["hashtag"]:
            result["hashtag"] = parsed.hostname or ""
    except Exception:
        pass
    return result

# ==========================================
# СИСТЕМНЫЙ ПРОКСИ
# ==========================================
def set_system_proxy(enable: bool, host: str = "127.0.0.1", port: int = 25443):
    system = platform.system()
    if system == 'Windows':
        try:
            import winreg
            import ctypes
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
                else:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            try:
                ctypes.windll.wininet.InternetSetOptionW(None, 39, None, 0)
                ctypes.windll.wininet.InternetSetOptionW(None, 37, None, 0)
            except Exception:
                pass
            return True
        except Exception:
            return False
    else:
        try:
            mode = "manual" if enable else "none"
            subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy', 'mode', mode],
                          check=False, capture_output=True, timeout=5)
            if enable:
                for proto in ['socks', 'http', 'https']:
                    subprocess.run(['gsettings', 'set', f'org.gnome.system.proxy.{proto}', 'host', host],
                                  check=False, capture_output=True, timeout=5)
                    subprocess.run(['gsettings', 'set', f'org.gnome.system.proxy.{proto}', 'port', str(port)],
                                  check=False, capture_output=True, timeout=5)
            return True
        except Exception:
            return False

# ==========================================
# NAIVEPROXY WORKER (реальный лог в реальном времени)
# ==========================================
class NaiveProxyWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, config_path):
        super().__init__()
        self.config_path = config_path
        self.process = None
        self.is_running = False

    def run(self):
        naive_path = shutil.which(NAIVE_BINARY_NAME)
        if not naive_path:
            for check_dir in [BASE_DIR, DATA_DIR]:
                candidate = os.path.join(check_dir, NAIVE_BINARY_NAME)
                if os.path.exists(candidate):
                    naive_path = candidate
                    break
        
        if not naive_path:
            self.log_signal.emit("❌ naiveproxy не найден")
            self.log_signal.emit(f"Скачайте с https://github.com/klzgrad/naiveproxy/releases")
            self.log_signal.emit(f"И поместите в {DATA_DIR}")
            self.finished_signal.emit()
            return

        self.log_signal.emit(f"📍 Найден: {naive_path}")

        try:
            self.process = subprocess.Popen(
                [naive_path, self.config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                close_fds=True,
                start_new_session=True
            )
            self.is_running = True
            self.log_signal.emit("✅ NaiveProxy запущен")

            # Читаем вывод в реальном времени
            if self.process.stdout:
                for line in iter(self.process.stdout.readline, ''):
                    if not self.is_running:
                        break
                    line = line.strip()
                    if line:
                        self.log_signal.emit(line)

        except Exception as e:
            self.log_signal.emit(f"❌ ОШИБКА: {str(e)}")
        finally:
            if self.process:
                try:
                    self.process.stdout.close()
                except Exception:
                    pass
            self.finished_signal.emit()

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass

# ==========================================
# МЕНЕДЖЕР КЛЮЧЕЙ (без подписок)
# ==========================================
class KeyManager:
    def __init__(self, keys_path: str):
        self.keys_path = keys_path
        self.keys = self._load_keys()

    def _load_keys(self) -> list:
        raw = load_json_file(self.keys_path, [])
        if raw and isinstance(raw, list) and len(raw) > 0:
            if isinstance(raw[0], str):
                converted = []
                for key in raw:
                    if key.startswith("naive+"):
                        converted.append({
                            "key": key,
                            "added": datetime.now().isoformat(),
                            "id": str(uuid.uuid4())[:8]
                        })
                self._save_keys(converted)
                return converted
        return [k for k in raw if isinstance(k, dict) and k.get("key", "").startswith("naive+")]

    def _save_keys(self, keys: list = None):
        if keys is not None:
            self.keys = keys
        save_json_file(self.keys_path, self.keys)

    def add_key(self, key_string: str) -> bool:
        if not is_valid_naive_key(key_string):
            return False
        if any(normalize_key(k["key"]) == normalize_key(key_string) for k in self.keys):
            return False
        self.keys.append({
            "key": key_string,
            "added": datetime.now().isoformat(),
            "id": str(uuid.uuid4())[:8]
        })
        self._save_keys()
        return True

    def remove_key(self, key_id: str) -> bool:
        before = len(self.keys)
        self.keys = [k for k in self.keys if k.get("id") != key_id]
        if len(self.keys) < before:
            self._save_keys()
            return True
        return False

    def remove_all_keys(self):
        self.keys.clear()
        self._save_keys()

# ==========================================
# ОСНОВНОЙ КЛАСС
# ==========================================
class NaiveProxyClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bobcat Naive Proxy — Прокси отключен")
        self.setFont(QFont("Arial"))
        self.setMinimumSize(900, 650)

        self.key_manager = KeyManager(KEYS_DB_PATH)
        self.naive_thread = None
        self.system_proxy_enabled = False
        self.current_key_index = -1

        self.log_styles = {
            "dark": "background-color: #1e1e1e; color: #c0c0c0;",
            "light": "background-color: #ffffff; color: #000000;",
        }
        self.current_theme = get_system_theme()

        self.init_ui()
        self.refresh_keys_list()
        self.update_status(False)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Левая панель
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Верхняя панель
        top_bar_layout = QHBoxLayout()
        self.btn_settings = QPushButton("⚙️ Настройки")
        self.btn_settings.clicked.connect(self.show_settings_menu)
        self.chk_system_proxy = QCheckBox("Системный прокси")
        self.chk_system_proxy.setChecked(False)
        top_bar_layout.addWidget(self.btn_settings)
        top_bar_layout.addWidget(self.chk_system_proxy)
        top_bar_layout.addStretch()
        left_layout.addLayout(top_bar_layout)

        # Группа добавления ключа
        keys_group = QGroupBox("NaiveProxy ключи")
        keys_layout = QVBoxLayout(keys_group)

        input_layout = QHBoxLayout()
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("naive+https://user:pass@host:port")
        self.key_input.returnPressed.connect(self.add_key)
        self.btn_add = QPushButton("➕ Добавить")
        self.btn_add.clicked.connect(self.add_key)
        input_layout.addWidget(self.key_input)
        input_layout.addWidget(self.btn_add)
        keys_layout.addLayout(input_layout)

        self.key_selector = QComboBox()
        self.key_selector.setEditable(False)
        self.key_selector.currentIndexChanged.connect(self._on_key_selected)
        keys_layout.addWidget(self.key_selector)

        delete_layout = QHBoxLayout()
        self.btn_delete = QPushButton("🗑️ Удалить")
        self.btn_delete.clicked.connect(self.delete_selected_key)
        self.btn_delete.setStyleSheet("background-color: #FF1800; color: white;")
        self.btn_delete_all = QPushButton("🗑️ Удалить все")
        self.btn_delete_all.clicked.connect(self.delete_all_keys)
        self.btn_delete_all.setStyleSheet("background-color: #FF1800; color: white;")
        delete_layout.addWidget(self.btn_delete)
        delete_layout.addWidget(self.btn_delete_all)
        keys_layout.addLayout(delete_layout)

        left_layout.addWidget(keys_group)

        # Лог
        log_group = QGroupBox("Лог NaiveProxy")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Monospace", 9))
        self.log_text.setStyleSheet(self.log_styles[self.current_theme])
        log_layout.addWidget(self.log_text)
        left_layout.addWidget(log_group, stretch=1)

        # Правая панель
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addStretch()

        self.btn_power = QPushButton("ВКЛЮЧИТЬ")
        self.btn_power.setFixedSize(150, 150)
        self.btn_power.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71; color: white; border-radius: 75px;
                font-size: 20px; font-weight: bold; border: 4px solid #27ae60;
            }
            QPushButton:hover { background-color: #27ae60; }
        """)
        self.btn_power_off_style = """
            QPushButton {
                background-color: #e74c3c; color: white; border-radius: 75px;
                font-size: 20px; font-weight: bold; border: 4px solid #c0392b;
            }
            QPushButton:hover { background-color: #c0392b; }
        """
        self.btn_power.clicked.connect(self.toggle_proxy)
        right_layout.addWidget(self.btn_power, alignment=Qt.AlignmentFlag.AlignCenter)

        info = QLabel(f"Прокси: SOCKS5 :{LOCAL_PROXY_PORT}\nHTTP :8080")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(info, alignment=Qt.AlignmentFlag.AlignCenter)

        self.key_info = QLabel("")
        self.key_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_info.setStyleSheet("color: #888; font-size: 9pt;")
        right_layout.addWidget(self.key_info)

        right_layout.addStretch()

        # Сплиттер
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    def show_settings_menu(self):
        menu = QMenu(self)
        menu.setFont(QFont("Arial", 10))
        about_action = QAction("ℹ️ О программе", self)
        about_action.triggered.connect(self.show_about)
        menu.addAction(about_action)
        menu.exec(self.btn_settings.mapToGlobal(self.btn_settings.rect().bottomLeft()))

    def show_about(self):
        QMessageBox.information(
            self, "О программе",
            "Bobcat Proxy NaiveProxy GUI\n\n"
            "Клиент для NaiveProxy\n"
            "SOCKS5 + HTTP прокси\n\n"
            "https://github.com/klzgrad/naiveproxy"
        )

    def append_log(self, text: str):
        # Все сообщения показываются, разные цвета для разных типов
        if "❌" in text or "ERROR" in text.upper() or "CRITICAL" in text:
            txt = f"<span style='color:#ff6b6b;font-weight:bold'>{text}</span>"
        elif "✅" in text:
            txt = f"<span style='color:#51cf66'>{text}</span>"
        elif "⚠️" in text or "WARN" in text.upper():
            txt = f"<span style='color:#ffa94d'>{text}</span>"
        elif "📍" in text or "🔄" in text or "🚀" in text or "⏹️" in text:
            txt = f"<span style='color:#00bcd4'>{text}</span>"
        else:
            txt = f"<span style='color:#888888'>{text}</span>"
        
        self.log_text.append(txt)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def _on_key_selected(self, index: int):
        self.current_key_index = index
        if 0 <= index < len(self.key_manager.keys):
            key_data = self.key_manager.keys[index]
            parsed = parse_naive_key(key_data["key"])
            self.key_info.setText(f"{parsed['host']}:{parsed['port']}")
        else:
            self.key_info.setText("")

    def refresh_keys_list(self):
        self.key_selector.clear()
        for i, key_data in enumerate(self.key_manager.keys):
            parsed = parse_naive_key(key_data["key"])
            name = parsed.get("hashtag", "")
            if name:
                if len(name) > 35:
                    name = name[:32] + "..."
                display = f"🏷️ {name}"
            else:
                display = f"🟡 {parsed['host']}:{parsed['port']}"
            self.key_selector.addItem(f"{i+1}. {display}")
        
        has_keys = len(self.key_manager.keys) > 0
        self.btn_delete.setEnabled(has_keys)
        self.btn_delete_all.setEnabled(has_keys)

    def add_key(self):
        text = self.key_input.text().strip()
        if not text:
            return
        
        if text.startswith("naive+"):
            if not is_valid_naive_key(text):
                self.append_log("❌ Невалидный ключ. Формат: naive+https://user:pass@host:port")
                return
            if self.key_manager.add_key(text):
                self.append_log("✅ Ключ добавлен")
                self.refresh_keys_list()
            else:
                self.append_log("⚠️ Ключ уже в списке")
        else:
            self.append_log("❌ Неверный формат. Ожидается naive+https://...")
        
        self.key_input.clear()

    def delete_selected_key(self):
        idx = self.key_selector.currentIndex()
        if idx == -1 or not self.key_manager.keys:
            QMessageBox.warning(self, "Внимание", "Нет выбранного ключа!")
            return
        
        key_data = self.key_manager.keys[idx]
        parsed = parse_naive_key(key_data["key"])
        preview = f"{parsed['host']}:{parsed['port']}"
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить ключ?\n{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.key_manager.remove_key(key_data["id"])
            self.refresh_keys_list()
            self.append_log("🗑️ Ключ удалён")
            
            if not self.key_manager.keys and self.naive_thread and self.naive_thread.isRunning():
                self.toggle_proxy()

    def delete_all_keys(self):
        if not self.key_manager.keys:
            QMessageBox.information(self, "Информация", "Список уже пуст!")
            return
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить ВСЕ ключи ({len(self.key_manager.keys)})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.key_manager.remove_all_keys()
            self.refresh_keys_list()
            self.append_log("🗑️ Все ключи удалены!")
            
            if self.naive_thread and self.naive_thread.isRunning():
                self.toggle_proxy()

    def generate_naive_config(self, key_string: str) -> bool:
        try:
            if not key_string.startswith("naive+"):
                self.append_log("❌ Неверный формат ключа")
                return False

            https_url = key_string[6:]
            if '#' in https_url:
                https_url = https_url.split('#')[0]

            if not https_url.startswith("https://"):
                self.append_log("❌ После naive+ должна быть https:// ссылка")
                return False

            config = {
                "listen": [
                    "socks://127.0.0.1:25443",
                    "http://127.0.0.1:8080"
                ],
                "proxy": https_url,
                "log": ""
            }

            with open(NAIVE_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            parsed = urllib.parse.urlparse(https_url)
            self.append_log(f"✅ Конфиг создан: {parsed.hostname}:{parsed.port or 443}")
            return True

        except Exception as e:
            self.append_log(f"❌ Ошибка создания конфига: {e}")
            return False

    def toggle_proxy(self):
        # Остановка
        if self.naive_thread and self.naive_thread.isRunning():
            self.append_log("⏹️ Остановка...")
            if self.chk_system_proxy.isChecked():
                self.cleanup_system_proxy()
            self.naive_thread.stop()
            self.naive_thread.wait()
            self.naive_thread = None
            self.update_status(False)
            return

        # Запуск
        idx = self.key_selector.currentIndex()
        if idx == -1 or not self.key_manager.keys:
            QMessageBox.warning(self, "Ошибка", "Выберите ключ!")
            return

        key_data = self.key_manager.keys[idx]
        key = key_data["key"]

        if not self.generate_naive_config(key):
            return

        self.append_log("🚀 Запуск NaiveProxy...")
        
        self.naive_thread = NaiveProxyWorker(NAIVE_CONFIG_PATH)
        self.naive_thread.log_signal.connect(self.append_log)
        self.naive_thread.finished_signal.connect(self.on_naive_finished)
        self.naive_thread.start()

        if self.chk_system_proxy.isChecked():
            if set_system_proxy(True, LOCAL_PROXY_HOST, LOCAL_PROXY_PORT):
                self.system_proxy_enabled = True
                self.append_log(f"🔌 Системный прокси: {LOCAL_PROXY_HOST}:{LOCAL_PROXY_PORT}")

        self.update_status(True)

    def on_naive_finished(self):
        if self.system_proxy_enabled:
            self.cleanup_system_proxy()
        self.update_status(False)
        self.append_log("🔚 Процесс завершён")

    def cleanup_system_proxy(self):
        if self.system_proxy_enabled:
            set_system_proxy(False)
            self.system_proxy_enabled = False
            self.append_log("🔌 Системный прокси отключён")

    def update_status(self, is_active: bool):
        if is_active:
            self.btn_power.setText("ВЫКЛЮЧИТЬ")
            self.btn_power.setStyleSheet(self.btn_power_off_style)
            self.setWindowTitle("Bobcat Proxy 2.5 pre1 — Naive Proxy отключен")
            self.key_selector.setEnabled(False)
            self.btn_add.setEnabled(False)
            self.key_input.setEnabled(False)
            self.chk_system_proxy.setEnabled(False)
            self.btn_delete.setEnabled(False)
            self.btn_delete_all.setEnabled(False)
            self.btn_settings.setEnabled(False)
        else:
            self.btn_power.setText("ВКЛЮЧИТЬ")
            self.btn_power.setStyleSheet("""
                QPushButton {
                    background-color: #00F267; color: white; border-radius: 75px;
                    font-size: 20px; font-weight: bold; border: 4px solid #27ae60;
                }
                QPushButton:hover { background-color: #27ae60; }
            """)
            self.setWindowTitle("Bobcat Proxy 2.5 pre1 — Naive Proxy отключен")
            self.key_selector.setEnabled(True)
            self.btn_add.setEnabled(True)
            self.key_input.setEnabled(True)
            self.chk_system_proxy.setEnabled(True)
            self.btn_settings.setEnabled(True)
            has = len(self.key_manager.keys) > 0
            self.btn_delete.setEnabled(has)
            self.btn_delete_all.setEnabled(has)

    def closeEvent(self, event):
        if self.naive_thread and self.naive_thread.isRunning():
            self.naive_thread.stop()
            self.naive_thread.wait()
        if self.system_proxy_enabled:
            set_system_proxy(False)
        event.accept()

# ==========================================
# ЗАПУСК
# ==========================================
if __name__ == "__main__":
    if platform.system() != 'Windows':
        os.environ.setdefault('QT_QPA_PLATFORM', 'wayland;xcb')
        os.environ.setdefault('QT_STYLE_OVERRIDE', 'fusion')
    app = QApplication([])
    app.setFont(QFont("Arial", 10))
    window = NaiveProxyClient()
    window.show()
    app.exec()
