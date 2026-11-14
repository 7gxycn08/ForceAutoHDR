import sys
import os
import winreg
import ctypes
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QComboBox, QFileDialog, QInputDialog,
    QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon

# --- DPI Awareness ---
# noinspection SpellCheckingInspection
sh_core = ctypes.WinDLL("shcore")
user32 = ctypes.WinDLL("user32")
shell32 = ctypes.WinDLL("shell32")
try:
    sh_core.SetProcessDpiAwareness(2)
except AttributeError:
    user32.SetProcessDPIAware(True)


class RegistryWorker(QThread):
    """Worker thread to handle registry operations without freezing the UI"""
    finished = Signal()
    error = Signal(str)
    success = Signal(str)

    def __init__(self, action, data=None):
        super().__init__()
        self.action = action
        self.data = data

    def run(self):
        try:
            if self.action == "add":
                self.add_exe_to_reg(self.data['path'], self.data['strength'])
                self.success.emit("EXE and HDR Strength Added to Registry.")
            elif self.action == "delete":
                self.delete_registry_key(self.data)
                self.success.emit(f"Registry key '{self.data}' deleted successfully.")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    # noinspection PyMethodMayBeStatic
    def add_exe_to_reg(self, exe_path, hdr_strength):
        exe_name = os.path.basename(exe_path)

        # Direct3D Logic
        base_path = r"Software\Microsoft\Direct3D"
        key_name = exe_name.replace(".exe", "")
        registry_path = fr"{base_path}\{key_name}"

        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "Name", 0, winreg.REG_SZ, f"{key_name}.exe")
        winreg.SetValueEx(key, "D3DBehaviors", 0, winreg.REG_SZ,
                          "BufferUpgradeOverride=1;BufferUpgradeEnable10Bit=1")
        winreg.CloseKey(key)

        # UserGpuPreferences Logic
        gpu_pref_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
        try:
            formated_exe_path = exe_path.replace('/', '\\')
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, gpu_pref_path, 0, winreg.KEY_SET_VALUE) as gpu_key:
                reg_value = f"AutoHDRStrength={hdr_strength};AppStatus=1;AutoHDREnable=2097;"
                winreg.SetValueEx(gpu_key, formated_exe_path, 0, winreg.REG_SZ, reg_value)
        except FileNotFoundError:
            formated_exe_path = exe_path.replace('/', '\\')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, gpu_pref_path) as gpu_key:
                reg_value = f"AutoHDRStrength={hdr_strength};AppStatus=1;AutoHDREnable=2097;"
                winreg.SetValueEx(gpu_key, formated_exe_path, 0, winreg.REG_SZ, reg_value)

    # noinspection PyMethodMayBeStatic
    def delete_registry_key(self, key_name):
        path = r"Software\Microsoft\Direct3D"
        if not shell32.IsUserAnAdmin():
            raise PermissionError("Run the script with administrator privileges to modify the registry.")

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteKey(key, key_name)


class ForceAutoHDR(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.setWindowTitle("ForceAutoHDR v1.0.0.5")
        self.setFixedSize(400, 240)

        # Set Icon (Handles case where file might be missing)
        if os.path.exists(r"Resources\hdr.ico"):
            self.setWindowIcon(QIcon(r"Resources\hdr.ico"))

        # Main Widget and Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(50, 40, 50, 40)
        layout.setSpacing(20)

        # Dropdown (ComboBox)
        self.keys_drop = QComboBox()
        self.refresh_list()
        layout.addWidget(self.keys_drop, alignment=Qt.AlignmentFlag.AlignCenter)

        # Buttons
        self.add_button = QPushButton("Add Game EXE")
        self.add_button.clicked.connect(self.handle_add_exe)
        layout.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.delete_button = QPushButton("Delete Game EXE")
        self.delete_button.clicked.connect(self.handle_delete_exe)
        layout.addWidget(self.delete_button, alignment=Qt.AlignmentFlag.AlignCenter)

    def show_keys(self):
        path = r"Software\Microsoft\Direct3D"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                keys = []
                index = 0
                while True:
                    try:
                        keys.append(winreg.EnumKey(key, index))
                        index += 1
                    except OSError:
                        break
                return keys
        except FileNotFoundError:
            # Create path if missing
            # noinspection PyBroadException
            try:
                winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Microsoft\Direct3D")
            except:
                pass
            return []
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Error accessing registry: {e}")
            return []

    def refresh_list(self):
        self.keys_drop.clear()
        keys = self.show_keys()
        if keys:
            self.keys_drop.addItems(keys)
        else:
            self.keys_drop.addItem("No Games Found")

    def handle_add_exe(self):
        # 1. Select File
        file_path, _ = QFileDialog.getOpenFileName(self, "Select EXE", "", "Executable files (*.exe)")
        if not file_path:
            return

        # 2. Input HDR Strength
        strength, ok = QInputDialog.getInt(self, "HDR Strength", "Enter HDR strength (0-100):",
                                           50, 0, 100)
        if not ok:
            QMessageBox.warning(self, "Cancelled", "HDR strength is required to proceed.")
            return

        # 3. Run in Thread
        self.worker = RegistryWorker("add", {"path": file_path, "strength": strength})
        self.worker.success.connect(lambda msg: QMessageBox.information(self, "Done", msg))
        self.worker.error.connect(lambda err: QMessageBox.critical(self, "Error",
                                                                   f"Error updating registry: {err}"))
        self.worker.finished.connect(self.refresh_list)
        self.worker.start()

    def handle_delete_exe(self):
        key_name = self.keys_drop.currentText()
        if key_name == "No Games Found":
            return

        confirm = QMessageBox.question(self, "Warning",
                                       f"Are you sure you want to delete key: {key_name}?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if confirm == QMessageBox.StandardButton.Yes:
            self.worker = RegistryWorker("delete", key_name)
            self.worker.success.connect(lambda msg: QMessageBox.information(self, "Done", msg))
            self.worker.error.connect(lambda err: QMessageBox.critical(self, "Error", err))
            self.worker.finished.connect(self.refresh_list)
            self.worker.start()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Basic styling to mimic the "Dark Blue" theme
    # noinspection SpellCheckingInspection
    app.setStyleSheet("""
        QMainWindow { background-color: #2b2b2b; }
        QPushButton { 
            background-color: #1f538d; 
            color: white; 
            border-radius: 5px; 
            padding: 8px; 
            font-family: 'Segoe UI'; 
            font-size: 13px;
        }
        QPushButton:hover { background-color: #2563be; }
        QComboBox { 
            background-color: #333333; 
            color: white; 
            border: 1px solid #555; 
            padding: 5px; 
            min-width: 200px;
        }
    """)

    window = ForceAutoHDR()
    window.show()
    sys.exit(app.exec())