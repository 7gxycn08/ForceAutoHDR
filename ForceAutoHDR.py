import os
import sys

from PySide6.QtCore import Qt, QSettings, QThread
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from display_status import query_display_status
from library_scan import (
    is_skipped_executable,
    resolve_shortcut,
    running_executables,
    scan_installed_games,
)
from registry_prefs import APP_VERSION, STRENGTH_PRESETS, GameEntry, profile_document
from registry_store import (
    add_games,
    import_profile,
    list_games,
    read_global_swap,
    remove_game,
    set_global_swap,
    set_strength_for_all,
    undo_available,
    undo_last_change,
    upsert_game,
)

GAME_BAR_HINT = (
    "Open Xbox Game Bar and move the HDR intensity slider. If brightness changes, Auto HDR is on."
)
APP_STYLE = """
QMainWindow, QDialog { background-color: #2b2b2b; }
QMainWindow QLabel, QDialog QLabel, QMainWindow QCheckBox, QDialog QCheckBox,
QMainWindow QRadioButton, QMainWindow QGroupBox {
    color: #e6e6e6;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #555555;
    margin-top: 12px;
    padding: 12px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #ffffff; }
QPushButton, QDialogButtonBox QPushButton {
    background-color: #1f538d;
    color: white;
    border-radius: 5px;
    padding: 8px 14px;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QPushButton:hover, QDialogButtonBox QPushButton:hover { background-color: #2563be; }
QPushButton:disabled, QDialogButtonBox QPushButton:disabled {
    background-color: #3a3a3a;
    color: #9a9a9a;
}
QLineEdit, QComboBox {
    background-color: #333333;
    color: white;
    border: 1px solid #555555;
    padding: 6px;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QTableWidget, QListWidget {
    background-color: #333333;
    color: white;
    border: 1px solid #555555;
    font-family: 'Segoe UI';
    font-size: 13px;
    gridline-color: #555555;
}
QTableWidget::item, QListWidget::item { color: white; padding: 4px; }
QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #1f538d;
    color: white;
}
QHeaderView::section {
    background-color: #2b2b2b;
    color: white;
    border: 1px solid #555555;
    padding: 4px;
}
QComboBox QAbstractItemView, QListWidget {
    background-color: #333333;
    color: white;
    selection-background-color: #1f538d;
    selection-color: white;
}
QSlider::groove:horizontal { height: 6px; background: #555555; border-radius: 3px; }
QSlider::handle:horizontal { background: #2563be; width: 14px; margin: -5px 0; border-radius: 7px; }
QStatusBar { color: #e6e6e6; background: #2b2b2b; }
"""


def _icon_path() -> str | None:
    roots = [
        getattr(sys, "_MEIPASS", None),
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
    ]
    for root in roots:
        if not root:
            continue
        candidate = os.path.join(root, "Resources", "hdr.ico")
        if os.path.isfile(candidate):
            return candidate
    return None


class TaskWorker(QThread):
    """Runs one registry or scan task off the UI thread."""

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.message = ""
        self.error = ""
        self.result = None
        self.show_hint = False
        self.remember_strength = None

    def run(self):
        try:
            self.result = self._fn()
            if isinstance(self.result, str):
                self.message = self.result
        except Exception as exc:
            self.error = str(exc)


class ChoiceDialog(QDialog):
    def __init__(self, title: str, rows: list[tuple[str, object]], multi: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection if multi else QListWidget.SelectionMode.SingleSelection
        )
        for label, payload in rows:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, payload)
            item.setToolTip(label)
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(self._accept_one)
        layout.addWidget(self.list, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._multi = multi

    def _filter(self, text: str):
        query = text.strip().lower()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(bool(query) and query not in item.text().lower())

    def _accept_one(self, item):
        if self._multi:
            self.list.clearSelection()
            item.setSelected(True)
        self.accept()

    def chosen(self) -> list:
        payloads = []
        for item in self.list.selectedItems():
            payloads.append(item.data(Qt.ItemDataRole.UserRole))
        return payloads


class ForceAutoHDR(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: TaskWorker | None = None
        self.settings = QSettings("ForceAutoHDR", "ForceAutoHDR")
        self._suspend = False
        self.setWindowTitle(f"ForceAutoHDR v{APP_VERSION}")
        self.setMinimumSize(980, 760)
        self.resize(1100, 820)
        self.setAcceptDrops(True)
        icon = _icon_path()
        if icon:
            self.setWindowIcon(QIcon(icon))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(10)

        status_row = QHBoxLayout()
        self.display_label = QLabel("Checking displays...")
        self.display_label.setWordWrap(True)
        refresh_status = QPushButton("Refresh status")
        refresh_status.clicked.connect(self._refresh_display_status)
        status_row.addWidget(self.display_label, stretch=1)
        status_row.addWidget(refresh_status)
        layout.addLayout(status_row)

        hint = QLabel(
            "Add the game executable Windows actually launches, not a launcher. "
            "Drop an .exe or a shortcut here. Strength is the Xbox Game Bar HDR intensity."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games")
        self.search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search, stretch=1)
        self.add_file_button = QPushButton("Add file")
        self.add_running_button = QPushButton("Add running")
        self.add_installed_button = QPushButton("Add installed")
        self.add_shortcut_button = QPushButton("Add shortcut")
        self.add_file_button.clicked.connect(self._add_files)
        self.add_running_button.clicked.connect(self._add_running)
        self.add_installed_button.clicked.connect(self._add_installed)
        self.add_shortcut_button.clicked.connect(self._add_shortcut)
        for button in (
            self.add_file_button,
            self.add_running_button,
            self.add_installed_button,
            self.add_shortcut_button,
        ):
            search_row.addWidget(button)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Game", "Strength", "10-bit", "GPU", "Flip model", "Path"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=1)

        self.details = QGroupBox("Selected game")
        detail_layout = QVBoxLayout(self.details)
        strength_row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(self._last_strength())
        self.strength_value = QLabel(f"{self.slider.value()}%")
        self.strength_value.setMinimumWidth(48)
        self.slider.valueChanged.connect(lambda value: self.strength_value.setText(f"{value}%"))
        self.slider.sliderReleased.connect(self._save_from_details)
        strength_row.addWidget(self.slider, stretch=1)
        strength_row.addWidget(self.strength_value)
        for name, value in STRENGTH_PRESETS:
            button = QPushButton(name)
            button.clicked.connect(lambda _checked=False, preset=value: self._apply_preset(preset))
            strength_row.addWidget(button)
        self.apply_all_button = QPushButton("Apply strength to all")
        self.apply_all_button.clicked.connect(self._apply_strength_to_all)
        strength_row.addWidget(self.apply_all_button)
        detail_layout.addLayout(strength_row)

        self.ten_bit = QCheckBox("10-bit buffer upgrade")
        self.ten_bit.toggled.connect(self._save_from_details)
        detail_layout.addWidget(self.ten_bit)
        ten_bit_hint = QLabel(
            "10-bit is stored by executable name, so every path with the same exe shares it. "
            "If an Unreal game blows out on Windows 11 24H2, turn this off or set "
            "r.DefaultBackBufferPixelFormat=1 in that game's Engine.ini under %LOCALAPPDATA%."
        )
        ten_bit_hint.setWordWrap(True)
        detail_layout.addWidget(ten_bit_hint)

        gpu_row = QHBoxLayout()
        gpu_row.addWidget(QLabel("GPU"))
        self.gpu_group = QButtonGroup(self)
        self.gpu_windows = QRadioButton("Windows decides")
        self.gpu_power = QRadioButton("Power saving")
        self.gpu_high = QRadioButton("High performance")
        self.gpu_group.addButton(self.gpu_windows, 0)
        self.gpu_group.addButton(self.gpu_power, 1)
        self.gpu_group.addButton(self.gpu_high, 2)
        self.gpu_windows.setChecked(True)
        for button in (self.gpu_windows, self.gpu_power, self.gpu_high):
            gpu_row.addWidget(button)
        gpu_row.addStretch(1)
        self.gpu_group.idClicked.connect(self._save_from_details)
        detail_layout.addLayout(gpu_row)

        flip_row = QHBoxLayout()
        flip_row.addWidget(QLabel("Flip model"))
        self.swap_box = QComboBox()
        self.swap_box.addItem("Follow Windows", None)
        self.swap_box.addItem("On for this game", 1)
        self.swap_box.addItem("Off for this game", 0)
        self.swap_box.currentIndexChanged.connect(self._save_from_details)
        flip_row.addWidget(self.swap_box)
        flip_row.addStretch(1)
        detail_layout.addLayout(flip_row)

        action_row = QHBoxLayout()
        self.relink_button = QPushButton("Relink")
        self.remove_button = QPushButton("Remove")
        self.open_button = QPushButton("Open folder")
        self.copy_button = QPushButton("Copy path")
        self.relink_button.clicked.connect(self._relink)
        self.remove_button.clicked.connect(self._remove)
        self.open_button.clicked.connect(self._open_folder)
        self.copy_button.clicked.connect(self._copy_path)
        for button in (self.relink_button, self.remove_button, self.open_button, self.copy_button):
            action_row.addWidget(button)
        action_row.addStretch(1)
        detail_layout.addLayout(action_row)
        layout.addWidget(self.details)

        bottom = QHBoxLayout()
        self.export_button = QPushButton("Export profile")
        self.import_button = QPushButton("Import profile")
        self.undo_button = QPushButton("Undo last change")
        self.global_swap = QCheckBox("Flip model for all windowed DirectX games")
        self.export_button.clicked.connect(self._export_profile)
        self.import_button.clicked.connect(self._import_profile)
        self.undo_button.clicked.connect(self._undo)
        self.global_swap.toggled.connect(self._on_global_swap)
        bottom.addWidget(self.export_button)
        bottom.addWidget(self.import_button)
        bottom.addWidget(self.undo_button)
        bottom.addWidget(self.global_swap, stretch=1)
        layout.addLayout(bottom)

        self._refresh_display_status()
        self.refresh_list()
        self.statusBar().showMessage("Drop a game executable or shortcut onto this window.")

    def _last_strength(self) -> int:
        try:
            value = int(self.settings.value("last_strength", 50))
        except (TypeError, ValueError):
            return 50
        return value if 0 <= value <= 100 else 50

    def _remember_strength(self, strength: int | None):
        if strength is None:
            return
        self.settings.setValue("last_strength", int(strength))

    def _refresh_display_status(self):
        try:
            status = query_display_status()
            self.display_label.setText(status.line())
        except OSError as exc:
            self.display_label.setText(f"Display status unavailable: {exc}")

    def refresh_list(self):
        previous = self._selected_entry()
        self._suspend = True
        try:
            games = list_games()
        except OSError as exc:
            self._suspend = False
            QMessageBox.critical(self, "Error", f"Could not read the registry:\n{exc}")
            self._update_buttons()
            return
        self.table.setRowCount(0)
        restore_row = 0 if games else None
        for entry in games:
            row = self.table.rowCount()
            self.table.insertRow(row)
            missing = " (file missing)" if entry.file_missing else ""
            values = [
                f"{entry.exe_name}{missing}",
                "—" if entry.strength is None else f"{entry.strength}%",
                "On" if entry.ten_bit else "Off",
                entry.gpu_label(),
                entry.swap_label(),
                entry.exe_path or "path not recorded",
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                item.setToolTip(entry.label())
                if entry.file_missing:
                    item.setForeground(QColor("#e6c07b"))
                self.table.setItem(row, column, item)
            if previous and self._same_entry(previous, entry):
                restore_row = row
        if restore_row is not None and self.table.rowCount():
            self.table.selectRow(restore_row)
        try:
            global_on = read_global_swap()
        except OSError:
            global_on = False
        self.global_swap.setChecked(global_on)
        self._suspend = False
        self._apply_filter()
        self._load_details(self._selected_entry())
        self._update_buttons()

    def _selected_entry(self) -> GameEntry | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        entry = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, GameEntry):
            return entry
        return None

    @staticmethod
    def _same_entry(left: GameEntry, right: GameEntry) -> bool:
        if left.exe_path and right.exe_path:
            return os.path.normcase(left.exe_path) == os.path.normcase(right.exe_path)
        return left.key_name == right.key_name and left.exe_name == right.exe_name

    def _apply_filter(self):
        query = self.search.text().strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            entry = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not isinstance(entry, GameEntry):
                self.table.setRowHidden(row, False)
                continue
            haystack = f"{entry.exe_name} {entry.exe_path or ''}".lower()
            self.table.setRowHidden(row, bool(query) and query not in haystack)

    def _busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _update_buttons(self, *_args):
        busy = self._busy()
        entry = self._selected_entry()
        has_selection = entry is not None
        has_path = bool(entry and entry.exe_path)
        for button in (
            self.add_file_button,
            self.add_running_button,
            self.add_installed_button,
            self.add_shortcut_button,
            self.export_button,
            self.import_button,
            self.apply_all_button,
        ):
            button.setEnabled(not busy)
        self.undo_button.setEnabled(not busy and undo_available())
        self.global_swap.setEnabled(not busy)
        self.details.setEnabled(not busy and has_selection)
        self.remove_button.setEnabled(not busy and has_selection)
        self.relink_button.setEnabled(not busy and has_selection)
        self.open_button.setEnabled(not busy and has_path)
        self.copy_button.setEnabled(not busy and has_path)
        editable = not busy and has_path and not entry.file_missing
        self.slider.setEnabled(editable)
        self.ten_bit.setEnabled(editable)
        self.swap_box.setEnabled(editable)
        for button in (self.gpu_windows, self.gpu_power, self.gpu_high):
            button.setEnabled(editable)

    def _on_selection_changed(self):
        if self._suspend:
            return
        self._load_details(self._selected_entry())
        self._update_buttons()

    def _load_details(self, entry: GameEntry | None):
        self._suspend = True
        try:
            if entry is None:
                self.details.setEnabled(False)
                return
            strength = entry.strength if entry.strength is not None else self._last_strength()
            self.slider.setValue(strength)
            self.strength_value.setText(f"{strength}%")
            self.ten_bit.setChecked(bool(entry.ten_bit))
            gpu_id = entry.gpu_preference if entry.gpu_preference in (1, 2) else 0
            button = self.gpu_group.button(gpu_id)
            if button is not None:
                button.setChecked(True)
            swap_index = {None: 0, 1: 1, 0: 2}.get(entry.swap_effect, 0)
            self.swap_box.setCurrentIndex(swap_index)
        finally:
            self._suspend = False
        self._update_buttons()

    def _gpu_value(self):
        checked = self.gpu_group.checkedId()
        if checked in (1, 2):
            return checked
        return None

    def _swap_value(self):
        return self.swap_box.currentData()

    def _start(self, fn, *, remember=None, hint=False):
        if self._busy():
            return
        self.worker = TaskWorker(fn, self)
        self.worker.show_hint = hint
        self.worker.remember_strength = remember
        self.worker.finished.connect(self._on_finished)
        self._update_buttons()
        self.statusBar().showMessage("Working...")
        self.worker.start()

    def _on_finished(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self.refresh_list()
        if worker is None:
            return
        if worker.error:
            QMessageBox.critical(self, "Error", worker.error)
            self.statusBar().showMessage(worker.error, 8000)
            return
        if worker.remember_strength is not None:
            self._remember_strength(worker.remember_strength)
        if worker.message:
            text = f"{worker.message} {GAME_BAR_HINT}" if worker.show_hint else worker.message
            self.statusBar().showMessage(text, 12000)

    def _save_from_details(self, *_args):
        if self._suspend or self._busy():
            return
        entry = self._selected_entry()
        if entry is None or not entry.exe_path or entry.file_missing:
            return
        path = entry.exe_path
        strength = self.slider.value()
        ten_bit = self.ten_bit.isChecked()
        gpu = self._gpu_value()
        swap = self._swap_value()

        def task():
            upsert_game(path, strength, ten_bit=ten_bit, gpu_preference=gpu, swap_effect=swap)
            return f"Saved {os.path.basename(path)}."

        self._start(task, remember=strength, hint=True)

    def _apply_preset(self, strength: int):
        self.slider.setValue(strength)
        self._save_from_details()

    def _paths_without_launchers(self, paths: list[str]) -> list[str]:
        flagged = [path for path in paths if is_skipped_executable(path)]
        if not flagged:
            return paths
        names = "\n".join(os.path.basename(path) for path in flagged)
        answer = QMessageBox.question(
            self,
            "Launcher or helper",
            "These look like launchers or helpers, not the game itself:\n\n"
            f"{names}\n\nAdd them anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            return paths
        return [path for path in paths if not is_skipped_executable(path)]

    def _add_paths(self, paths: list[str]):
        paths = [path for path in paths if path]
        paths = self._paths_without_launchers(paths)
        if not paths:
            self.statusBar().showMessage("Nothing was added.", 6000)
            return
        strength = self._last_strength()

        def task():
            return add_games(paths, strength)

        self._start(task, remember=strength, hint=True)

    def _add_files(self):
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            "Select the game executable (not the launcher)",
            "",
            "Executable files (*.exe)",
        )
        if paths:
            self._add_paths(paths)

    def _add_running(self):
        try:
            processes = running_executables()
        except OSError as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        if not processes:
            QMessageBox.information(self, "Running games", "No user executables are running.")
            return
        dialog = ChoiceDialog(
            "Add a running executable",
            [(f"{name} — {path}", path) for name, path in processes],
            multi=True,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._add_paths(dialog.chosen())

    def _add_installed(self):
        if self._busy():
            return
        self.statusBar().showMessage("Scanning Steam, Epic, GOG, and Xbox folders...")
        self.worker = TaskWorker(scan_installed_games, self)
        self.worker.finished.connect(self._on_scan_finished)
        self._update_buttons()
        self.worker.start()

    def _on_scan_finished(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self._update_buttons()
        if worker is None:
            return
        if worker.error:
            QMessageBox.critical(self, "Error", worker.error)
            return
        games, warnings = worker.result
        if warnings:
            self.statusBar().showMessage(" ".join(warnings), 10000)
        if not games:
            QMessageBox.information(
                self,
                "Installed games",
                "No installed games were found in Steam, Epic, GOG, or Xbox folders.",
            )
            return
        dialog = ChoiceDialog("Add installed games", [(game.label(), game.exe_path) for game in games], True, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._add_paths(dialog.chosen())

    def _add_shortcut(self):
        path, _selected = QFileDialog.getOpenFileName(self, "Select a shortcut", "", "Shortcuts (*.lnk)")
        if not path:
            return
        try:
            target = resolve_shortcut(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Shortcut", str(exc))
            return
        self._add_paths([target])

    def _apply_strength_to_all(self):
        strength = self.slider.value()
        answer = QMessageBox.question(
            self,
            "Apply strength",
            f"Set HDR strength to {strength}% for every saved game that still has its executable?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start(lambda: set_strength_for_all(strength), remember=strength, hint=True)

    def _relink(self):
        entry = self._selected_entry()
        if entry is None:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Select the executable Windows launches",
            entry.exe_path or "",
            "Executable files (*.exe)",
        )
        if not path:
            return
        strength = self.slider.value() if entry.strength is None else entry.strength
        ten_bit = self.ten_bit.isChecked()
        gpu = self._gpu_value()
        swap = self._swap_value()
        previous = entry.exe_path

        def task():
            name = upsert_game(
                path,
                strength,
                ten_bit=ten_bit,
                gpu_preference=gpu,
                swap_effect=swap,
                previous_path=previous,
            )
            return f"Relinked {name}."

        self._start(task, remember=strength, hint=True)

    def _remove(self):
        entry = self._selected_entry()
        if entry is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove game",
            f"Remove Auto HDR for this game?\n\n{entry.label()}\n\n"
            "GPU preference and the per-game flip setting stay in place.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start(lambda: f"Removed Auto HDR for {remove_game(entry)}.")

    def _open_folder(self):
        entry = self._selected_entry()
        if entry is None or not entry.exe_path:
            return
        import subprocess

        path = os.path.normpath(entry.exe_path)
        if os.path.isfile(path):
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            folder = os.path.dirname(path)
            if os.path.isdir(folder):
                subprocess.Popen(["explorer", folder])
            else:
                self.statusBar().showMessage("That folder is not on this PC.", 6000)

    def _copy_path(self):
        entry = self._selected_entry()
        if entry is None or not entry.exe_path:
            return
        QApplication.clipboard().setText(entry.exe_path)
        self.statusBar().showMessage("Path copied.", 4000)

    def _export_profile(self):
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export profile",
            "ForceAutoHDR-profile.json",
            "JSON profiles (*.json)",
        )
        if not path:
            return
        try:
            document = profile_document(list_games(), read_global_swap())
        except OSError as exc:
            QMessageBox.critical(self, "Export", str(exc))
            return
        import json

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
        self.statusBar().showMessage(f"Exported {len(document['games'])} games.", 8000)

    def _import_profile(self):
        path, _selected = QFileDialog.getOpenFileName(self, "Import profile", "", "JSON profiles (*.json)")
        if not path:
            return
        import json

        from registry_prefs import parse_profile

        try:
            with open(path, encoding="utf-8") as handle:
                document = json.loads(handle.read())
            games, global_swap = parse_profile(document)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            QMessageBox.critical(self, "Import", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "Import profile",
            "Also remove saved games that are not in this profile?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        remove_missing = answer == QMessageBox.StandardButton.Yes

        def task():
            return import_profile(games, remove_missing=remove_missing, global_swap=global_swap)

        self._start(task, hint=True)

    def _undo(self):
        answer = QMessageBox.question(
            self,
            "Undo",
            "Restore Auto HDR registry settings to the way they were before the last change?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start(lambda: undo_last_change() or "Restored the previous registry settings.")

    def _on_global_swap(self, checked: bool):
        if self._suspend or self._busy():
            return

        def task():
            set_global_swap(checked)
            if checked:
                return "Windowed flip model enabled for DirectX games."
            return "Windowed flip model turned off."

        self._start(task)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = []
        errors = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            ext = os.path.splitext(local)[1].lower()
            if ext == ".lnk":
                try:
                    paths.append(resolve_shortcut(local))
                except (OSError, ValueError) as exc:
                    errors.append(str(exc))
            elif ext == ".exe":
                paths.append(local)
        if errors:
            QMessageBox.warning(self, "Some files were skipped", "\n".join(errors))
        if paths:
            self._add_paths(paths)
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(5000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    window = ForceAutoHDR()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
