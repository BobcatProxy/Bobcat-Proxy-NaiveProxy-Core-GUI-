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
import zipfile
import tarfile
from pathlib import Path
from typing import Dict, Optional, List, Tuple

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTextEdit, QLineEdit,
                             QComboBox, QLabel, QMessageBox, QSplitter,
                             QGroupBox, QCheckBox, QMenu, QProgressBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QFont, QPalette

# ==========================================
# КОНСТАНТЫ И ПУТИ
# ==========================================
GITHUB_API_URL = "https://api.github.com/repos/klzgrad/naiveproxy/releases"
GITHUB_RELEASES_URL = "https://github.com/klzgrad/naiveproxy/releases"

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
NAIVE_BINARY_NAME_WIN = "naive.exe"
KEYS_DB_PATH = os.path.join(DATA_DIR, "configs.json")
VERSION_FILE = os.path.join(DATA_DIR, "naive_version.txt")
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")

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

def get_current_version() -> Optional[str]:
    """Получает текущую установленную версию."""
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, 'r') as f:
            return f.read().strip()
    return None

def save_current_version(version: str):
    """Сохраняет текущую версию."""
    with open(VERSION_FILE, 'w') as f:
        f.write(version)

def find_naive_binary() -> Optional[str]:
    """Находит бинарный файл naiveproxy."""
    # Проверяем в PATH
    binary_name = NAIVE_BINARY_NAME_WIN if platform.system() == 'Windows' else NAIVE_BINARY_NAME
    naive_path = shutil.which(binary_name)
    
    if naive_path:
        return naive_path
    
    # Проверяем в DATA_DIR
    candidate = os.path.join(DATA_DIR, binary_name)
    if os.path.exists(candidate):
        return candidate
    
    # Проверяем в BASE_DIR
    candidate = os.path.join(BASE_DIR, binary_name)
    if os.path.exists(candidate):
        return candidate
    
    return None

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
# ОБНОВЛЕНИЕ NAIVEPROXY
# ==========================================
class UpdateChecker(QThread):
    """Поток для проверки обновлений."""
    update_available = pyqtSignal(str, str, str)  # version, tag, download_url
    no_update = pyqtSignal(str)  # current version
    error = pyqtSignal(str)
    
    def run(self):
        try:
            # Получаем информацию о последнем релизе
            api_url = f"{GITHUB_API_URL}/latest"
            req = urllib.request.Request(api_url)
            req.add_header('Accept', 'application/vnd.github.v3+json')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            latest_version = data.get('tag_name', '').lstrip('v')
            if not latest_version:
                self.error.emit("Не удалось определить версию релиза")
                return
            
            # Ищем подходящий ассет для нашей платформы
            assets = data.get('assets', [])
            download_url = self.find_asset_for_platform(assets)
            
            if not download_url:
                self.error.emit(f"Не найден подходящий билд для {platform.system()} {platform.machine()}")
                return
            
            # Проверяем текущую версию
            current_version = get_current_version()
            
            if current_version == latest_version:
                self.no_update.emit(latest_version)
            else:
                self.update_available.emit(latest_version, data.get('tag_name', ''), download_url)
                
        except Exception as e:
            self.error.emit(f"Ошибка проверки обновлений: {str(e)}")
    
    def find_asset_for_platform(self, assets: List[Dict]) -> Optional[str]:
        """Находит подходящий ассет для текущей платформы."""
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        # Определяем ключевые слова для поиска
        if system == 'windows':
            platform_keywords = ['win', 'windows']
        elif system == 'linux':
            platform_keywords = ['linux']
        elif system == 'darwin':
            platform_keywords = ['mac', 'macos', 'darwin', 'osx']
        else:
            return None
        
        # Ключевые слова для архитектуры
        if machine in ['x86_64', 'amd64', 'x64']:
            arch_keywords = ['x64', 'x86_64', 'amd64', 'x86-64']
        elif machine in ['aarch64', 'arm64']:
            arch_keywords = ['arm64', 'aarch64']
        elif machine in ['x86', 'i386', 'i686']:
            arch_keywords = ['x86', 'i386', '386']
        else:
            arch_keywords = [machine]
        
        # Ищем подходящий ассет
        for asset in assets:
            name = asset.get('name', '').lower()
            download_url = asset.get('browser_download_url', '')
            
            if not download_url:
                continue
            
            # Проверяем платформу и архитектуру
            platform_match = any(keyword in name for keyword in platform_keywords)
            arch_match = any(keyword in name for keyword in arch_keywords)
            
            # Исключаем отладочные и символьные файлы
            is_excluded = any(x in name for x in ['debug', 'symbol', 'pdb', 'sha256', 'asc'])
            
            if platform_match and arch_match and not is_excluded:
                return download_url
        
        return None

class DownloadWorker(QThread):
    """Поток для скачивания и установки обновлений."""
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, download_url: str, version: str):
        super().__init__()
        self.download_url = download_url
        self.version = version
        
    def run(self):
        try:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            
            # Определяем имя файла
            filename = self.download_url.split('/')[-1]
            download_path = os.path.join(DOWNLOAD_DIR, filename)
            
            self.status.emit(f"Скачивание {filename}...")
            
            # Скачиваем файл с отслеживанием прогресса
            def progress_hook(count, block_size, total_size):
                if total_size > 0:
                    percent = int(count * block_size * 100 / total_size)
                    self.progress.emit(min(percent, 100))
            
            urllib.request.urlretrieve(self.download_url, download_path, progress_hook)
            
            self.status.emit("Распаковка архива...")
            
            # Распаковываем архив
            extract_dir = os.path.join(DOWNLOAD_DIR, f"naiveproxy_{self.version}")
            os.makedirs(extract_dir, exist_ok=True)
            
            if filename.endswith('.zip'):
                with zipfile.ZipFile(download_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            elif filename.endswith(('.tar.gz', '.tgz')):
                with tarfile.open(download_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_dir)
            elif filename.endswith(('.tar.xz', '.txz')):
                with tarfile.open(download_path, 'r:xz') as tar_ref:
                    tar_ref.extractall(extract_dir)
            else:
                # Если не архив, возможно это просто бинарник
                extract_dir = download_path
            
            self.status.emit("Установка бинарных файлов...")
            
            # Копируем бинарные файлы в DATA_DIR
            binary_name = NAIVE_BINARY_NAME_WIN if platform.system() == 'Windows' else NAIVE_BINARY_NAME
            installed = self.install_binary(extract_dir, binary_name)
            
            if installed:
                # Сохраняем версию
                save_current_version(self.version)
                
                # Удаляем архив после установки
                if os.path.exists(download_path) and download_path != extract_dir:
                    os.remove(download_path)
                
                self.finished.emit(True, f"✅ Успешно установлена версия {self.version}")
            else:
                self.finished.emit(False, f"❌ Не удалось найти {binary_name} в скачанных файлах")
                
        except Exception as e:
            self.finished.emit(False, f"❌ Ошибка при скачивании: {str(e)}")
    
    def install_binary(self, source_dir: str, binary_name: str) -> bool:
        """Устанавливает бинарные файлы из распакованной директории."""
        if os.path.isfile(source_dir):
            # Если source_dir это файл, просто копируем его
            return self.copy_binary(source_dir, os.path.join(DATA_DIR, binary_name))
        
        # Ищем бинарный файл в директории и поддиректориях
        for root, dirs, files in os.walk(source_dir):
            if binary_name in files:
                source_path = os.path.join(root, binary_name)
                target_path = os.path.join(DATA_DIR, binary_name)
                return self.copy_binary(source_path, target_path)
            
            # Также ищем naive без расширения
            if platform.system() != 'Windows' and NAIVE_BINARY_NAME in files:
                source_path = os.path.join(root, NAIVE_BINARY_NAME)
                target_path = os.path.join(DATA_DIR, NAIVE_BINARY_NAME)
                return self.copy_binary(source_path, target_path)
        
        return False
    
    def copy_binary(self, source: str, target: str) -> bool:
        """Копирует бинарный файл и устанавливает права на выполнение."""
        try:
            # Создаем резервную копию старого файла
            if os.path.exists(target):
                backup = target + '.backup'
                shutil.move(target, backup)
            
            # Копируем новый файл
            shutil.copy2(source, target)
            
            # Устанавливаем права на выполнение для Unix систем
            if platform.system() != 'Windows':
                os.chmod(target, 0o755)
            
            # Удаляем резервную копию
            if os.path.exists(target + '.backup'):
                os.remove(target + '.backup')
            
            return True
        except Exception as e:
            return False

# ==========================================
# NAIVEPROXY WORKER
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
        naive_path = find_naive_binary()
        
        if not naive_path:
            self.log_signal.emit("❌ naiveproxy не найден")
            self.log_signal.emit(f"Нажмите 'Проверить обновления' для автоматической установки")
            self.log_signal.emit(f"Или скачайте вручную с {GITHUB_RELEASES_URL}")
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
# МЕНЕДЖЕР КЛЮЧЕЙ
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
        self.update_checker = None
        self.download_worker = None
        self.system_proxy_enabled = False
        self.current_key_index = -1
        self.auto_update_enabled = False

        self.log_styles = {
            "dark": "background-color: #1e1e1e; color: #c0c0c0;",
            "light": "background-color: #ffffff; color: #000000;",
        }
        self.current_theme = get_system_theme()

        self.init_ui()
        self.refresh_keys_list()
        self.update_status(False)
        
        # Автоматическая проверка обновлений при запуске
        QTimer.singleShot(1000, self.auto_check_updates)

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
        self.btn_check_updates = QPushButton("🔄 Проверить обновления")
        self.btn_check_updates.clicked.connect(self.check_for_updates)
        self.chk_system_proxy = QCheckBox("Системный прокси")
        self.chk_system_proxy.setChecked(False)
        top_bar_layout.addWidget(self.btn_settings)
        top_bar_layout.addWidget(self.btn_check_updates)
        top_bar_layout.addWidget(self.chk_system_proxy)
        top_bar_layout.addStretch()
        left_layout.addLayout(top_bar_layout)

        # Прогресс-бар для обновлений
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximum(100)
        left_layout.addWidget(self.progress_bar)

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

        # Информация о версии
        current_ver = get_current_version()
        if current_ver:
            version_label = QLabel(f"NaiveProxy v{current_ver}")
            version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            version_label.setStyleSheet("color: #666; font-size: 8pt;")
            right_layout.addWidget(version_label)

        right_layout.addStretch()

        # Сплиттер
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    def auto_check_updates(self):
        """Автоматическая проверка обновлений при запуске."""
        self.append_log("🔄 Автоматическая проверка обновлений...")
        self.check_for_updates(silent=True)

    def check_for_updates(self, silent=False):
        """Проверяет наличие обновлений."""
        self.btn_check_updates.setEnabled(False)
        
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(
            lambda version, tag, url: self.on_update_available(version, tag, url, silent)
        )
        self.update_checker.no_update.connect(
            lambda version: self.on_no_update(version, silent)
        )
        self.update_checker.error.connect(
            lambda error: self.on_update_error(error, silent)
        )
        self.update_checker.finished.connect(
            lambda: self.btn_check_updates.setEnabled(True)
        )
        self.update_checker.start()

    def on_update_available(self, version: str, tag: str, url: str, silent: bool):
        """Обрабатывает доступное обновление."""
        current = get_current_version() or "не установлена"
        msg = f"Доступна новая версия: {version}\nТекущая: {current}"
        self.append_log(f"📦 {msg}")
        
        if not silent:
            reply = QMessageBox.question(
                self, "Доступно обновление",
                f"{msg}\n\nСкачать и установить автоматически?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.download_update(url, version)
        else:
            # В тихом режиме спрашиваем один раз при запуске
            if not hasattr(self, '_auto_update_asked'):
                self._auto_update_asked = True
                reply = QMessageBox.question(
                    self, "Доступно обновление",
                    f"{msg}\n\nУстановить сейчас?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    self.download_update(url, version)

    def on_no_update(self, version: str, silent: bool):
        """Обрабатывает отсутствие обновлений."""
        if not silent:
            self.append_log(f"✅ Установлена последняя версия: {version}")
            QMessageBox.information(self, "Обновления", "Установлена последняя версия")

    def on_update_error(self, error: str, silent: bool):
        """Обрабатывает ошибку проверки обновлений."""
        self.append_log(f"❌ {error}")
        if not silent:
            QMessageBox.warning(self, "Ошибка", error)

    def download_update(self, url: str, version: str):
        """Скачивает и устанавливает обновление."""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.append_log(f"📥 Начинаю скачивание версии {version}...")
        
        self.download_worker = DownloadWorker(url, version)
        self.download_worker.progress.connect(self.progress_bar.setValue)
        self.download_worker.status.connect(self.append_log)
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.start()

    def on_download_finished(self, success: bool, message: str):
        """Обрабатывает завершение скачивания."""
        self.progress_bar.setVisible(False)
        self.append_log(message)
        
        if success:
            QMessageBox.information(self, "Обновление", message)
        else:
            QMessageBox.warning(self, "Ошибка обновления", message)

    def show_settings_menu(self):
        menu = QMenu(self)
        menu.setFont(QFont("Arial", 10))
        
        check_action = QAction("🔄 Проверить обновления", self)
        check_action.triggered.connect(lambda: self.check_for_updates())
        menu.addAction(check_action)
        
        menu.addSeparator()
        
        about_action = QAction("ℹ️ О программе", self)
        about_action.triggered.connect(self.show_about)
        menu.addAction(about_action)
        
        menu.exec(self.btn_settings.mapToGlobal(self.btn_settings.rect().bottomLeft()))

    def show_about(self):
        QMessageBox.information(
            self, "О программе",
            "Bobcat Proxy Naive GUI\n\n"
            "Клиент для NaiveProxy\n"
            "SOCKS5 + HTTP прокси\n\n"
            "Автоматическое обновление с GitHub\n"
            f"Репозиторий: {GITHUB_RELEASES_URL}"
        )

    def append_log(self, text: str):
        if "❌" in text or "ERROR" in text.upper() or "CRITICAL" in text:
            txt = f"<span style='color:#ff6b6b;font-weight:bold'>{text}</span>"
        elif "✅" in text:
            txt = f"<span style='color:#51cf66'>{text}</span>"
        elif "⚠️" in text or "WARN" in text.upper():
            txt = f"<span style='color:#ffa94d'>{text}</span>"
        elif "📍" in text or "🔄" in text or "🚀" in text or "⏹️" in text or "📥" in text or "📦" in text:
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

        # Проверяем наличие бинарника
        if not find_naive_binary():
            reply = QMessageBox.question(
                self, "NaiveProxy не найден",
                "Бинарный файл naiveproxy не найден.\n\n"
                "Хотите проверить и скачать обновление сейчас?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.check_for_updates()
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
            self.setWindowTitle("Bobcat Proxy — Naive Proxy ВКЛЮЧЕН")
            self.key_selector.setEnabled(False)
            self.btn_add.setEnabled(False)
            self.key_input.setEnabled(False)
            self.chk_system_proxy.setEnabled(False)
            self.btn_delete.setEnabled(False)
            self.btn_delete_all.setEnabled(False)
            self.btn_settings.setEnabled(False)
            self.btn_check_updates.setEnabled(False)
        else:
            self.btn_power.setText("ВКЛЮЧИТЬ")
            self.btn_power.setStyleSheet("""
                QPushButton {
                    background-color: #00F267; color: white; border-radius: 75px;
                    font-size: 20px; font-weight: bold; border: 4px solid #27ae60;
                }
                QPushButton:hover { background-color: #27ae60; }
            """)
            self.setWindowTitle("Bobcat Proxy — Naive Proxy отключен")
            self.key_selector.setEnabled(True)
            self.btn_add.setEnabled(True)
            self.key_input.setEnabled(True)
            self.chk_system_proxy.setEnabled(True)
            self.btn_settings.setEnabled(True)
            self.btn_check_updates.setEnabled(True)
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
