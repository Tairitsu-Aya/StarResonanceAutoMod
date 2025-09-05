import os
import re
import sys
import subprocess
import json
import hashlib
from typing import List

from PyQt5.QtCore import (
    Qt,
    QThread,
    pyqtSignal,
    QSize,
    QPoint,
)
from PyQt5.QtGui import (
    QPixmap,
    QMovie,
    QIcon,
    QPalette,
    QColor,
    QStandardItemModel,
    QStandardItem,
)
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QSizePolicy,
    QFrame,
    QSplitter,
    QScrollArea,
    QGridLayout,
)


SCRIPT_NAME = os.path.join(os.path.dirname(__file__), "star_railway_monitor.py")

BACKGROUND_IMAGE = os.path.join(os.path.dirname(__file__), "assets", "gui_bg_80pct.jpg")

ATTRIBUTES = [
    "力量加持", "敏捷加持", "智力加持", "特攻伤害", "精英打击", "特攻治疗加持", "专精治疗加持",
    "施法专注", "攻速专注", "暴击专注", "幸运专注", "抵御魔法", "抵御物理",
    "极-绝境守护", "极-伤害叠加", "极-灵活身法", "极-生命凝聚", "极-急救措施",
    "极-生命波动", "极-生命汲取", "极-全队幸暴",
]

CATEGORIES = {
    "全部": "全部",
    "攻击": "攻击",
    "守护": "守护",
    "辅助": "辅助",
}

MATCH_COUNTS = [1, 2, 3]


def parse_log_file(path: str) -> List[dict]:
    """Parse a solver log file and extract combination information."""
    combos: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            lines: List[str] = []
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("=" * 50) or stripped.startswith("模组搭配优化 -"):
                    continue
                if stripped.startswith("统计信息"):
                    break
                if stripped:
                    lines.append(stripped)
        text = "\n".join(lines)
        pattern = r"=== 第(\d+)名搭配 ==="
        parts = re.split(pattern, text)
        for i in range(1, len(parts), 2):
            rank = int(parts[i])
            block = parts[i + 1]
            combo = _parse_block(block)
            combo["rank"] = rank
            combos.append(combo)
    except Exception:
        return []
    return combos


def _parse_block(block: str) -> dict:
    """Parse a single combination block."""
    total = ""
    power = ""
    modules: List[str] = []
    attrs: List[str] = []
    lines = [l for l in block.splitlines() if l.strip()]
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("总属性值"):
            total = line
        elif line.startswith("战斗力"):
            power = line
        elif line.startswith("模组列表"):
            i += 1
            while i < len(lines) and not lines[i].startswith("属性分布"):
                modules.append(lines[i].strip())
                i += 1
            continue
        elif line.startswith("属性分布"):
            i += 1
            while i < len(lines):
                attrs.append(lines[i].strip())
                i += 1
            break
        i += 1
    return {"total": total, "power": power, "modules": modules, "attrs": attrs}


class CheckableComboBox(QComboBox):
    """A QComboBox that allows multiple selection via checkboxes.

    Each item in the combobox is checkable.  Use :meth:`checked_items`
    to retrieve the list of selected entries.  When an item is
    clicked its check state toggles instead of selecting the item
    exclusively.  The combobox display shows a comma separated list
    of checked items.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))        
        self.view().pressed.connect(self.handle_item_pressed)        
        self.setEditable(True)
        if self.lineEdit() is not None:
            self.lineEdit().setReadOnly(True)        
        self._placeholder_text = "请选择"
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)

    def add_check_item(self, text: str):
        """Add a new checkable item to the combobox."""
        item = QStandardItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        item.setData(Qt.Unchecked, Qt.CheckStateRole)
        self.model().appendRow(item)
        self.update_display_text()

    def handle_item_pressed(self, index):
        """Toggle the check state of the clicked item."""
        item = self.model().itemFromIndex(index)
        if item.checkState() == Qt.Checked:
            item.setCheckState(Qt.Unchecked)
        else:
            item.setCheckState(Qt.Checked)
        self.update_display_text()

    def update_display_text(self):
        """Update the combobox text based on checked items."""
        checked = self.checked_items()
        if checked:
            self.setEditText(", ".join(checked))
        else:
            self.setEditText(self._placeholder_text)

    def checked_items(self) -> List[str]:
        """Return a list of all currently checked item texts."""
        checked = []
        for i in range(self.model().rowCount()):
            item = self.model().item(i)
            if item.checkState() == Qt.Checked:
                checked.append(item.text())
        return checked

    def clear_checked(self):
        """Clear all checkboxes."""
        for i in range(self.model().rowCount()):
            item = self.model().item(i)
            item.setCheckState(Qt.Unchecked)
        self.update_display_text()


class SolverWorker(QThread):
    """运行求解器脚本并输出其结果的工作线程。
    接收命令行参数列表，并以此参数启动子进程运行``python star_railway_monitor.py``。
    通过:attr:`output_signal`输出。
    进程完成时触发:attr:`finished_signal`。
    """

    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, args: List[str], parent=None):
        super().__init__(parent)
        self.args = args

    def run(self):
        # Compose the full command: python <script> <args>
        cmd = [sys.executable, SCRIPT_NAME] + self.args
        print("RUN:", " ".join(cmd))
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            
            if process.stdout:
                for line in process.stdout:
                    self.output_signal.emit(line)
            process.wait()
        except Exception as e:
            self.output_signal.emit(f"Error running solver: {e}\n")
        finally:
            self.finished_signal.emit()


class CustomTitleBar(QWidget):
    """
    实现最小化和关闭按钮的自定义标题栏。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._mouse_press_pos: QPoint | None = None
        self._mouse_move_pos: QPoint | None = None
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        self.title_label = QLabel("Star Resonance Auto Mod    原作者：fudiyangjin    GUI作者：Tairitsu-Aya  bilibili@Murasame绫         移动窗口请拖拽本行")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 18px;")
        self.title_label.setAlignment(Qt.AlignCenter)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.minimise_button = QPushButton("–")
        self.minimise_button.setFixedSize(28, 28)
        self.minimise_button.setStyleSheet(
            "QPushButton {background-color: transparent; color: white; border: none; font-size: 20px;}"
            "QPushButton:hover {background-color: rgba(255, 255, 255, 0.2);}"
        )
        self.minimise_button.clicked.connect(self.on_minimise)

        # Close button
        self.close_button = QPushButton("✕")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setStyleSheet(
            "QPushButton {background-color: transparent; color: white; border: none; font-size: 20px;}"
            "QPushButton:hover {background-color: rgba(255, 0, 0, 0.5);}"
        )
        self.close_button.clicked.connect(self.on_close)

        layout.addWidget(self.title_label)
        layout.addWidget(spacer)
        layout.addWidget(self.minimise_button)
        layout.addWidget(self.close_button)
        self.setLayout(layout)
        self.setFixedHeight(35)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.4); color: white;")

    def on_minimise(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def on_close(self):
        if self.parent_window:
            self.parent_window.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._mouse_press_pos = event.globalPos()
            self._mouse_move_pos = self.parent_window.pos() if self.parent_window else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._mouse_press_pos and self._mouse_move_pos and event.buttons() == Qt.LeftButton:
            global_pos = event.globalPos()
            diff = global_pos - self._mouse_press_pos
            new_pos = self._mouse_move_pos + diff
            self.parent_window.move(new_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._mouse_press_pos = None
        self._mouse_move_pos = None
        super().mouseReleaseEvent(event)


class StarRailwayGUI(QMainWindow):
    """Main application window for the Star Resonance Auto Mod GUI."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        if os.path.exists(BACKGROUND_IMAGE):
            pix = QPixmap(BACKGROUND_IMAGE)
            self._bg_pixmap = pix
            self.resize(pix.width(), pix.height())
        else:
            # Fallback size if image missing
            self.resize(1200, 800)
            self._bg_pixmap = None
        self.last_result_combos: List[dict] | None = None
        # Build UI components
        self.init_ui()

        # Worker thread placeholder
        self.solver_worker: SolverWorker | None = None

    def paintEvent(self, event):
        super().paintEvent(event)

    def init_ui(self):
        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        central.setLayout(layout)
        # 半透明遮罩，降低背景图存在感
        self.bg_dimmer = QWidget(central)
        self.bg_dimmer.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.bg_dimmer.setStyleSheet("background-color: rgba(0,0,0,0.5);")
        self.bg_dimmer.setGeometry(central.rect())
        self.bg_dimmer.lower()  # 放到其他控件下面（但在背景图之上）
        if os.path.exists(BACKGROUND_IMAGE):
            img_path = BACKGROUND_IMAGE.replace("\\", "/")
            central.setStyleSheet(
                f"#central {{"
                f"background-image: url({img_path});"
                f"background-repeat: no-repeat;"
                f"background-position: center;"
                f"}}"
            )
        
        self.title_bar = CustomTitleBar(self)
        layout.addWidget(self.title_bar)
        
        self.vertical_splitter = QSplitter(Qt.Vertical)
        self.vertical_splitter.setHandleWidth(1)
        layout.addWidget(self.vertical_splitter)
        layout.setStretchFactor(self.vertical_splitter, 1)
        
        self.top_splitter = QSplitter(Qt.Horizontal)
        self.top_splitter.setHandleWidth(1)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_panel.setLayout(left_layout)

        self.init_module_panel(left_layout)
        self.init_solver_panel(left_layout)
        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(spacer)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_panel.setLayout(right_layout)
        self.init_log_panel(right_layout)
        
        self.top_splitter.addWidget(left_panel)
        self.top_splitter.addWidget(right_panel)
        # 70/30 horizontal split
        self.top_splitter.setStretchFactor(0, 7)
        self.top_splitter.setStretchFactor(1, 3)
        
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.5);"
            "color: white;"
            "border: 1px solid rgba(255, 255, 255, 0.2);"
            "padding: 5px;"
        )
        self.output_edit.setPlaceholderText("输出内容将在此显示...")
        
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(5)
        bottom_container.setLayout(bottom_layout)
        
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(10)
        
        self.expand_output_button = QPushButton("放大显示")
        self.expand_output_button.setFixedHeight(24)
        self.expand_output_button.setStyleSheet(
            "QPushButton { background-color: rgba(0, 120, 215, 0.8); color: white; border: none; padding: 4px 8px; }"
            "QPushButton:hover { background-color: rgba(0, 120, 215, 1.0); }"
        )
        self.expand_output_button.clicked.connect(self.show_output_window)
        button_row.addWidget(self.expand_output_button)
        
        self.view_collect_button = QPushButton("查看收藏")
        self.view_collect_button.setFixedHeight(24)
        self.view_collect_button.setStyleSheet(
            "QPushButton { background-color: rgba(0, 120, 215, 0.8); color: white; border: none; padding: 4px 8px; }"
            "QPushButton:hover { background-color: rgba(0, 120, 215, 1.0); }"
        )
        self.view_collect_button.clicked.connect(self.show_collect_window)
        button_row.addWidget(self.view_collect_button)
        
        self.view_result_button = QPushButton("组合查看")
        self.view_result_button.setFixedHeight(24)
        self.view_result_button.setStyleSheet(
            "QPushButton { background-color: rgba(0, 120, 215, 0.8); color: white; border: none; padding: 4px 8px; }"
            "QPushButton:hover { background-color: rgba(0, 120, 215, 1.0); }"
        )
        self.view_result_button.clicked.connect(self.show_last_result_window)
        button_row.addWidget(self.view_result_button)
        button_row.addStretch(1)
        bottom_layout.addLayout(button_row)
        
        bottom_layout.addWidget(self.output_edit)
        bottom_layout.setStretchFactor(self.output_edit, 1)
        
        self.vertical_splitter.addWidget(self.top_splitter)
        self.vertical_splitter.addWidget(bottom_container)
        # 60/40 vertical split
        self.vertical_splitter.setStretchFactor(0, 3)
        self.vertical_splitter.setStretchFactor(1, 5)
        # Loading animation overlay
        self.loading_label = QLabel(central)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("background-color: rgba(0, 0, 0, 0.6);")
        self.loading_movie = QMovie()
        spinner_path = os.path.join(os.path.dirname(__file__), "assets", "spinner.gif")
        if os.path.exists(spinner_path):
            self.loading_movie.setFileName(spinner_path)
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.hide()
        # Set the central widget
        self.setCentralWidget(central)

        # Set global stylesheet for consistent look
        self.setStyleSheet(
            "* { color: white; font-family: 'Segoe UI', sans-serif; }"
            "QComboBox, QSpinBox, QTableWidget, QListWidget, QTextEdit {"
            " background-color: rgba(0,0,0,0.5);"
            " border: 1px solid rgba(255,255,255,0.2);"
            " }"
            "QPushButton {"
            " background-color: rgba(255,255,255,0.1);"
            " border: 1px solid rgba(255,255,255,0.2);"
            " padding: 4px 8px;"
            " }"
            "QPushButton:hover {"
            " background-color: rgba(255,255,255,0.2);"
            " }"
        )

    def resizeEvent(self, event):
        """Update the loading overlay geometry on resize."""
        super().resizeEvent(event)
        central = self.centralWidget()
        if central and self.loading_label:
            self.loading_label.setGeometry(central.rect())
        if hasattr(self, "bg_dimmer") and self.bg_dimmer:
            self.bg_dimmer.setGeometry(central.rect())

    def init_module_panel(self, parent_layout: QVBoxLayout):
        """Initialise the module selection panel."""
        
        cat_label = QLabel("选择类型 (category):")
        self.category_combo = QComboBox()
        for key in CATEGORIES.keys():
            self.category_combo.addItem(key)
        self.category_combo.setCurrentText("全部")
        attr_label = QLabel("选择词条 (attributes):")
        self.attributes_combo = CheckableComboBox()
        for attr in ATTRIBUTES:
            self.attributes_combo.add_check_item(attr)
        
        excl_label = QLabel("排除词条 (exclude attributes):")
        self.exclude_combo = CheckableComboBox()
        for attr in ATTRIBUTES:
            self.exclude_combo.add_check_item(attr)
        
        match_label = QLabel("匹配数量 (match count):")
        self.match_combo = QComboBox()
        for n in MATCH_COUNTS:
            self.match_combo.addItem(str(n))
        self.match_combo.setCurrentIndex(0)
        parent_layout.addWidget(cat_label)
        parent_layout.addWidget(self.category_combo)
        parent_layout.addWidget(attr_label)
        parent_layout.addWidget(self.attributes_combo)
        parent_layout.addWidget(excl_label)
        parent_layout.addWidget(self.exclude_combo)
        parent_layout.addWidget(match_label)
        parent_layout.addWidget(self.match_combo)

    def init_solver_panel(self, parent_layout: QVBoxLayout):
        """Initialise the solver parameter panel."""
        # Enumeration mode
        self.enum_checkbox = QCheckBox("启用枚举模式 (enumeration mode)")
        # Debug mode
        self.debug_checkbox = QCheckBox("启用调试模式 (debug mode)")
        # Min attr sum table
        mas_label = QLabel("最小词条数量 (min‑attr‑sum):")
        self.mas_table = QTableWidget(0, 2)
        self.mas_table.setHorizontalHeaderLabels(["词条", "数量"])
        self.mas_table.horizontalHeader().setStretchLastSection(True)
        self.mas_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.mas_table.verticalHeader().setVisible(False)
        self.mas_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.mas_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Button to add new row
        self.add_mas_button = QPushButton("添加一行 (Add)")
        self.add_mas_button.clicked.connect(self.add_mas_row)
        # Start solve button
        self.solve_button = QPushButton("开始求解")
        self.solve_button.setStyleSheet(
            "QPushButton {background-color: rgba(0, 120, 215, 0.8); color: white; font-weight: bold;}"
            "QPushButton:hover {background-color: rgba(0, 120, 215, 1.0);}"
        )
        self.solve_button.clicked.connect(self.on_solve)
        # Lay out
        parent_layout.addWidget(self.enum_checkbox)
        parent_layout.addWidget(self.debug_checkbox)
        parent_layout.addWidget(mas_label)
        parent_layout.addWidget(self.mas_table)
        button_row = QHBoxLayout()
        button_row.addWidget(self.add_mas_button)
        button_row.addWidget(self.solve_button)
        parent_layout.addLayout(button_row)

    def add_mas_row(self):
        """Append a new row to the min‑attr‑sum table with editable widgets."""
        row = self.mas_table.rowCount()
        self.mas_table.insertRow(row)
        # Attribute selector combobox for this row
        combo = QComboBox()
        for attr in ATTRIBUTES:
            combo.addItem(attr)
        self.mas_table.setCellWidget(row, 0, combo)
        # Quantity spinbox for this row
        spin = QSpinBox()
        spin.setMinimum(1)
        spin.setMaximum(999)
        spin.setValue(1)
        self.mas_table.setCellWidget(row, 1, spin)

    def init_log_panel(self, parent_layout: QVBoxLayout):
        """Initialise the log file panel."""
        log_label = QLabel("日志文件 (logs):")
        self.log_list = QListWidget()
        self.log_list.itemClicked.connect(self.on_log_clicked)
        # Populate log list
        self.refresh_log_list()
        parent_layout.addWidget(log_label)
        parent_layout.addWidget(self.log_list)

    def refresh_log_list(self):
        """Scan the ``logs`` directory and populate the list widget."""
        self.log_list.clear()
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        if os.path.isdir(logs_dir):
            files = [f for f in os.listdir(logs_dir) if f.endswith(".log")]
            for fname in sorted(files):
                item = QListWidgetItem(fname)
                self.log_list.addItem(item)

    def on_log_clicked(self, item: QListWidgetItem):
        """Load and display the selected log file in the output area."""
        log_name = item.text()
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        path = os.path.join(logs_dir, log_name)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            self.output_edit.setPlainText(content)
        except Exception as e:
            self.output_edit.setPlainText(f"无法读取日志 {log_name}: {e}\n")

    def build_args(self) -> List[str]:
        """Construct command line arguments from current UI state."""
        args: List[str] = []
        # Category
        cat_text = self.category_combo.currentText()
        cat_value = CATEGORIES.get(cat_text, None)
        args.extend(["-a"])
        if cat_value and cat_value != "all":
            args.extend(["--category", cat_value])
        # Attributes
        attrs = self.attributes_combo.checked_items()
        if attrs:
            args.extend(["--attributes", *attrs])
        # Exclude attributes
        excl_attrs = self.exclude_combo.checked_items()
        if excl_attrs:
            args.extend(["--exclude-attributes", *excl_attrs])
        # Match count
        match_value = self.match_combo.currentText()
        if match_value:
            args.extend(["--match-count", match_value])
        # Enumeration mode
        if self.enum_checkbox.isChecked():
            args.append("--enumeration-mode")
        # Debug mode
        if self.debug_checkbox.isChecked():
            args.append("--debug")
        # Min attr sum rows
        for row in range(self.mas_table.rowCount()):
            attr_widget = self.mas_table.cellWidget(row, 0)
            count_widget = self.mas_table.cellWidget(row, 1)
            if isinstance(attr_widget, QComboBox) and isinstance(count_widget, QSpinBox):
                attr_name = attr_widget.currentText().strip()
                count = count_widget.value()
                if attr_name:
                    args.extend(["-mas", f"{attr_name}", f"{count}"])
        print(args)
        return args

    def on_solve(self):
        """Callback when the solve button is clicked."""
        
        self.output_edit.clear()
        
        args = self.build_args()
        
        central = self.centralWidget()
        if central:
            self.loading_label.setGeometry(central.rect())
        if self.loading_movie.fileName():
            self.loading_movie.start()
        self.loading_label.show()
        
        self.solve_button.setEnabled(False)
        
        self.solver_worker = SolverWorker(args)
        self.solver_worker.output_signal.connect(self.append_output)
        self.solver_worker.finished_signal.connect(self.on_solver_finished)
        self.solver_worker.start()

    def append_output(self, text: str):
        """Append a line of output to the output area."""
        self.output_edit.moveCursor(self.output_edit.textCursor().End)
        self.output_edit.insertPlainText(text)
        self.output_edit.ensureCursorVisible()

    def on_solver_finished(self):
        """Clean up after the solver finishes and display results."""
        self.loading_label.hide()
        self.loading_movie.stop()
        self.solve_button.setEnabled(True)
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        try:
            files = [
                os.path.join(logs_dir, f)
                for f in os.listdir(logs_dir)
                if f.endswith(".log")
            ]
            if files:
                latest = max(files, key=os.path.getmtime)
                combos = parse_log_file(latest)
                if combos:
                    self.last_result_combos = combos
                    self.result_window = ResultWindow(combos, self)
                    self.result_window.show()
        except Exception as e:
            self.append_output(f"解析日志失败: {e}\n")
        self.refresh_log_list()

    def show_output_window(self):
        """Open a new resizable window to display the full output text."""
        text = self.output_edit.toPlainText()
        window = OutputWindow(text, self)
        window.show()

    def show_collect_window(self):
        """Open a window displaying all collected combos."""
        collect_dir = os.path.join(os.path.dirname(__file__), "collect")
        combos: List[dict] = []
        if os.path.isdir(collect_dir):
            for name in os.listdir(collect_dir):
                if name.endswith(".json"):
                    path = os.path.join(collect_dir, name)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            combos.append(json.load(f))
                    except Exception:
                        pass
        if combos:
            self.collect_window = ResultWindow(combos, self, title="收藏夹")
            self.collect_window.show()

    def show_last_result_window(self) -> None:
        """Reopen the last solver result window if results are available."""
        if self.last_result_combos:
            self.result_window = ResultWindow(self.last_result_combos, self)
            self.result_window.show()
        else:
            self.append_output("暂无结果，请先运行求解。\n")


class ResultWindow(QMainWindow):
    """Display parsed solver results in a scrollable grid layout."""

    def __init__(
        self,
        combos: List[dict],
        parent: QWidget | None = None,
        *,
        title: str = "搭配结果",
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1637, 1088)
        central = QWidget()
        central.setObjectName("resultWindowCentral")
        outer = QVBoxLayout()
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(5)
        central.setLayout(outer)
        central.setStyleSheet(
            "#resultWindowCentral { background-color: rgba(0, 0, 0, 0.8); border-radius: 8px; }"
        )
        self.title_bar = CustomTitleBar(self)
        self.title_bar.title_label.setText(title)
        outer.addWidget(self.title_bar)
        self.collect_dir = os.path.join(os.path.dirname(__file__), "collect")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        container = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(10)
        container.setLayout(grid)
        for i, combo in enumerate(combos):
            frame = QFrame()
            frame.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0.7); color: white; border-radius: 5px;"
            )
            vbox = QVBoxLayout()
            vbox.setContentsMargins(10, 10, 10, 10)
            vbox.setSpacing(8)
            frame.setLayout(vbox)
            rank = combo.get("rank", i + 1)
            top_row = QHBoxLayout()
            rank_label = QLabel(f"第{rank}名")
            rank_label.setStyleSheet("font-weight: bold; font-size: 24px;")
            top_row.addWidget(rank_label)
            top_row.addStretch(1)
            combo_hash = hashlib.md5(
                json.dumps(combo, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            collect_path = os.path.join(self.collect_dir, f"{combo_hash}.json")
            star_button = QPushButton("☆")
            star_button.setFixedSize(48, 48)
            star_button.setStyleSheet(
                "QPushButton { border: none; background: transparent; color: white; font-size: 28px; }"
            )
            if os.path.exists(collect_path):
                star_button.setText("★")
                star_button.setStyleSheet(
                    "QPushButton { border: none; background: transparent; color: yellow; font-size: 28px; }"
                )
            star_button.clicked.connect(
                lambda _, path=collect_path, combo=combo, btn=star_button: self.toggle_collect(path, combo, btn)
            )
            top_row.addWidget(star_button)
            vbox.addLayout(top_row)
            lines: List[str] = []
            if combo.get("total"):
                lines.append(combo["total"])
            if combo.get("power"):
                lines.append(combo["power"])
            if combo.get("modules"):
                lines.append("模组列表:")
                lines.extend(combo["modules"])
            if combo.get("attrs"):
                lines.append("属性分布:")
                lines.extend(combo["attrs"])
            label = QLabel("\n".join(lines))
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet("font-size: 22px;")
            vbox.addWidget(label)
            grid.addWidget(frame, i // 2, i % 2)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        outer.setStretchFactor(scroll, 1)
        self.setCentralWidget(central)
        #self.setStyleSheet("* { font-size: 22px; }")

    def toggle_collect(self, path: str, combo: dict, button: QPushButton) -> None:
        """Toggle collection state for a combo and update button appearance."""
        if os.path.exists(path):
            os.remove(path)
            button.setText("☆")
            button.setStyleSheet(
                "QPushButton { border: none; background: transparent; color: white; font-size: 28px;}"
            )
        else:
            os.makedirs(self.collect_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(combo, f, ensure_ascii=False, indent=2)
            button.setText("★")
            button.setStyleSheet(
                "QPushButton { border: none; background: transparent; color: yellow; font-size: 28px;}"
            )



class OutputWindow(QMainWindow):

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Set fixed size as requested
        self.resize(1637, 1088)
        # Central widget with dark translucent background
        central = QWidget()
        central.setObjectName("outputWindowCentral")
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        central.setLayout(layout)
        central.setStyleSheet(
            "#outputWindowCentral { background-color: rgba(0, 0, 0, 0.8); border-radius: 8px; }"
        )
        # Title bar
        self.title_bar = CustomTitleBar(self)
        # Override the title text
        self.title_bar.title_label.setText("输出查看")
        layout.addWidget(self.title_bar)
        # Text area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.7);"
            "color: white;"
            "border: none;"
            "padding: 5px;"
        )
        self.text_edit.setPlainText(text)
        layout.addWidget(self.text_edit)
        layout.setStretchFactor(self.text_edit, 1)
        self.setCentralWidget(central)


def main():
    app = QApplication(sys.argv)
    # Use a dark palette to better contrast against the background image
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(0, 0, 0, 0))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(0, 0, 0, 150))
    palette.setColor(QPalette.AlternateBase, QColor(0, 0, 0, 100))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(0, 0, 0, 150))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.Highlight, QColor(0, 120, 215, 180))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)
    window = StarRailwayGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()