"""
Graphical user interface for the Star Rail module optimisation tool.

This GUI wraps the existing ``star_railway_monitor.py`` script and provides
interactive widgets for selecting optimisation parameters.  The layout is
split into four distinct panels:

* **Module filter panel** – allows the user to choose the equipment
  category, required attribute list, attributes to exclude and the
  number of matching modules to return.  Multi‑select drop‑downs are
  implemented via a custom checkable combobox.
* **Solver panel** – exposes solver options such as enumeration mode
  and debug logging.  A table lets the user add one or more
  ``--min‑attr‑sum`` constraints via a combination of attribute and
  minimum count.  Clicking the “开始求解” button spawns the solver in
  a separate thread and streams its console output to the output
  viewer.  A simple loading animation is displayed while the solver
  runs.
* **Output panel** – shows the combined stdout/stderr of the solver
  process.  Selecting a log file from the log list will also display
  its contents here.
* **Log panel** – lists all ``*.log`` files in the ``logs`` folder
  relative to this script.  Clicking a file name loads its contents.

The top of the window contains a custom title bar with its own close
and minimise buttons.  The entire interface sits on top of a
semi‑transparent window whose background image is loaded from
``gui_bg.jpg``.  Colours and fonts are tuned for a dark background.

To run this GUI you will need PyQt5 (or PySide2) installed.  On
Windows the script may need to be started with ``pythonw`` to avoid a
separate console window.  When the “开始求解” button is pressed the
GUI invokes ``python star_railway_monitor.py`` with the selected
options.  If the solver script is located in a different folder you
can adjust ``SCRIPT_NAME`` below.
"""

import os
import re
import sys
import subprocess
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

# Path to the solver script.  You can modify this constant if your
# ``star_railway_monitor.py`` resides somewhere else.
SCRIPT_NAME = os.path.join(os.path.dirname(__file__), "star_railway_monitor.py")

# Path to the background image bundled alongside this file.  If you
# wish to use a different background simply replace ``gui_bg.jpg`` or
# adjust this constant accordingly.
# Background image for the window.  The default image shipped with this
# application resides under the ``assets`` directory.  If you wish to
# change the background simply replace the file at this path or point
# the constant elsewhere.
BACKGROUND_IMAGE = os.path.join(os.path.dirname(__file__), "assets", "gui_bg_80pct.jpg")

# List of attribute names used for the drop‑downs.  These names should
# match exactly those expected by ``star_railway_monitor.py``.  If
# additional attributes become available you can extend this list.
ATTRIBUTES = [
    "力量加持", "敏捷加持", "智力加持", "特攻伤害", "精英打击", "特攻治疗加持", "专精治疗加持",
    "施法专注", "攻速专注", "暴击专注", "幸运专注", "抵御魔法", "抵御物理",
    "极-绝境守护", "极-伤害叠加", "极-灵活身法", "极-生命凝聚", "极-急救措施",
    "极-生命波动", "极-生命汲取", "极-全队幸暴",
]

# Human‑readable category names mapped to the actual command line
# values.  Feel free to edit the keys or values to reflect your
# translation or script behaviour.  The default category is ``全部``.
CATEGORIES = {
    "全部": "全部",
    "攻击": "攻击",
    "守护": "守护",
    "辅助": "辅助",
}

# Default list of match counts available in the UI.  These values
# correspond to the ``--match-count`` parameter.  You can adjust the
# range or individual options here.
MATCH_COUNTS = [1, 2, 3, 4, 5]


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
            block = parts[i + 1]
            combos.append(_parse_block(block))
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
        # Use a standard item model so we can attach check states
        self.setModel(QStandardItemModel(self))
        # Connect the pressed signal to our handler to toggle check state
        self.view().pressed.connect(self.handle_item_pressed)
        # Enable editing of the display text so we can show selected items
        # directly in the combobox.  We mark the line edit as read only to
        # prevent manual typing by the user.
        self.setEditable(True)
        if self.lineEdit() is not None:
            self.lineEdit().setReadOnly(True)
        # Display placeholder when nothing is selected
        self._placeholder_text = "请选择"
        # Set minimal width to avoid collapsing to tiny size
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
    """Worker thread that runs the solver script and emits its output.

    The worker takes a list of command line arguments and spawns a
    subprocess running ``python star_railway_monitor.py`` with those
    arguments.  Both stdout and stderr are captured and emitted via
    :attr:`output_signal`.  When the process finishes the
    :attr:`finished_signal` is emitted so the GUI can hide the loader.
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
            # Start the subprocess and capture combined stdout/stderr
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            # Stream output line by line
            if process.stdout:
                for line in process.stdout:
                    self.output_signal.emit(line)
            process.wait()
        except Exception as e:
            # Emit any exception information to the output area
            self.output_signal.emit(f"Error running solver: {e}\n")
        finally:
            self.finished_signal.emit()


class CustomTitleBar(QWidget):
    """A custom title bar implementing minimise and close buttons.

    This widget replaces the default window frame.  Dragging the title
    bar moves the window and clicking the buttons triggers minimise or
    close actions on the parent window.
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

        # Spacer between title and buttons
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Minimise button (larger for better visibility)
        self.minimise_button = QPushButton("–")
        self.minimise_button.setFixedSize(28, 28)
        self.minimise_button.setStyleSheet(
            "QPushButton {background-color: transparent; color: white; border: none; font-size: 20px;}"
            "QPushButton:hover {background-color: rgba(255, 255, 255, 0.2);}"
        )
        self.minimise_button.clicked.connect(self.on_minimise)

        # Close button (larger for better visibility)
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
        # Increase the height to make dragging easier
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
            # Calculate offset and move window
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
        # Load background image and set window size accordingly
        if os.path.exists(BACKGROUND_IMAGE):
            pix = QPixmap(BACKGROUND_IMAGE)
            self._bg_pixmap = pix
            self.resize(pix.width(), pix.height())
        else:
            # Fallback size if image missing
            self.resize(1200, 800)
            self._bg_pixmap = None
        # Build UI components
        self.init_ui()

        # Worker thread placeholder
        self.solver_worker: SolverWorker | None = None

    def paintEvent(self, event):
        """Override paintEvent for transparency when frameless."""
        # We don't explicitly paint the background here because the
        # background image is applied via stylesheet on the central widget.
        # Simply delegate to the parent implementation.
        super().paintEvent(event)

    def init_ui(self):
        # Central widget with background applied via stylesheet.  The
        # ``central`` widget will fill the entire window and its
        # stylesheet draws the background image.  We keep margins
        # around the content to give elements breathing room.
        central = QWidget()
        central.setObjectName("central")
        # Build a layout for central; contents margins define padding
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        central.setLayout(layout)
        # 半透明遮罩，降低背景图“存在感”
        self.bg_dimmer = QWidget(central)
        self.bg_dimmer.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.bg_dimmer.setStyleSheet("background-color: rgba(0,0,0,0.5);")
        self.bg_dimmer.setGeometry(central.rect())
        self.bg_dimmer.lower()  # 放到其他控件下面（但在背景图之上）

        # Apply the background image via stylesheet on the central
        # widget.  ``background-position`` ensures the image stays
        # centered when the window is resized.
        if os.path.exists(BACKGROUND_IMAGE):
            img_path = BACKGROUND_IMAGE.replace("\\", "/")
            central.setStyleSheet(
                f"#central {{"
                f"background-image: url({img_path});"
                f"background-repeat: no-repeat;"
                f"background-position: center;"
                f"}}"
            )
        # Title bar
        self.title_bar = CustomTitleBar(self)
        layout.addWidget(self.title_bar)
        # Splitter to separate top (controls) and bottom (output)
        self.vertical_splitter = QSplitter(Qt.Vertical)
        self.vertical_splitter.setHandleWidth(1)
        layout.addWidget(self.vertical_splitter)
        layout.setStretchFactor(self.vertical_splitter, 1)
        # Top horizontal splitter for left and right panels
        self.top_splitter = QSplitter(Qt.Horizontal)
        self.top_splitter.setHandleWidth(1)
        # Left panel: module and solver controls
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        # Reduce spacing between controls to make the panel more compact
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_panel.setLayout(left_layout)
        # Module filter group
        self.init_module_panel(left_layout)
        # Solver panel
        self.init_solver_panel(left_layout)
        # Flexible spacer to push content to the top
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(spacer)
        # Right panel: log viewer
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_panel.setLayout(right_layout)
        self.init_log_panel(right_layout)
        # Add panels to top splitter
        self.top_splitter.addWidget(left_panel)
        self.top_splitter.addWidget(right_panel)
        # 70/30 horizontal split
        self.top_splitter.setStretchFactor(0, 7)
        self.top_splitter.setStretchFactor(1, 3)
        # Output panel for bottom half
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.5);"
            "color: white;"
            "border: 1px solid rgba(255, 255, 255, 0.2);"
            "padding: 5px;"
        )
        self.output_edit.setPlaceholderText("输出内容将在此显示...")
        # Construct a container for the output area: it holds a
        # button to expand the output and the text edit itself.
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(5)
        bottom_container.setLayout(bottom_layout)
        # Row with expand button aligned to the left
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(0)
        # Expand output button
        self.expand_output_button = QPushButton("放大显示")
        self.expand_output_button.setFixedHeight(24)
        self.expand_output_button.setStyleSheet(
            "QPushButton { background-color: rgba(0, 120, 215, 0.8); color: white; border: none; padding: 4px 8px; }"
            "QPushButton:hover { background-color: rgba(0, 120, 215, 1.0); }"
        )
        self.expand_output_button.clicked.connect(self.show_output_window)
        button_row.addWidget(self.expand_output_button)
        button_row.addStretch(1)
        bottom_layout.addLayout(button_row)
        # Add the output text edit underneath
        bottom_layout.addWidget(self.output_edit)
        bottom_layout.setStretchFactor(self.output_edit, 1)
        # Insert top and bottom containers into vertical splitter
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
        # Resize the loading overlay to cover the entire central widget
        central = self.centralWidget()
        if central and self.loading_label:
            self.loading_label.setGeometry(central.rect())
        if hasattr(self, "bg_dimmer") and self.bg_dimmer:
            self.bg_dimmer.setGeometry(central.rect())

    def init_module_panel(self, parent_layout: QVBoxLayout):
        """Initialise the module selection panel."""
        # Category selection
        cat_label = QLabel("选择类型 (category):")
        self.category_combo = QComboBox()
        for key in CATEGORIES.keys():
            self.category_combo.addItem(key)
        self.category_combo.setCurrentText("全部")
        # Attributes selection (multi)
        attr_label = QLabel("选择词条 (attributes):")
        self.attributes_combo = CheckableComboBox()
        for attr in ATTRIBUTES:
            self.attributes_combo.add_check_item(attr)
        # Exclude attributes (multi)
        excl_label = QLabel("排除词条 (exclude attributes):")
        self.exclude_combo = CheckableComboBox()
        for attr in ATTRIBUTES:
            self.exclude_combo.add_check_item(attr)
        # Match count selection
        match_label = QLabel("匹配数量 (match count):")
        self.match_combo = QComboBox()
        for n in MATCH_COUNTS:
            self.match_combo.addItem(str(n))
        self.match_combo.setCurrentIndex(0)
        # Lay out
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
        # Clear previous output
        self.output_edit.clear()
        # Build command line arguments
        args = self.build_args()
        # Start loading animation – cover the entire central widget
        central = self.centralWidget()
        if central:
            self.loading_label.setGeometry(central.rect())
        if self.loading_movie.fileName():
            self.loading_movie.start()
        self.loading_label.show()
        # Disable solve button to prevent reentry
        self.solve_button.setEnabled(False)
        # Spawn worker thread
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


class ResultWindow(QMainWindow):
    """Display parsed solver results in a scrollable grid layout."""

    def __init__(self, combos: List[dict], parent: QWidget | None = None):
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
        self.title_bar.title_label.setText("搭配结果")
        outer.addWidget(self.title_bar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        container = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(5, 5, 5, 5)
        grid.setSpacing(5)
        container.setLayout(grid)
        for i, combo in enumerate(combos):
            frame = QFrame()
            frame.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0.7); color: white; border-radius: 5px;"
            )
            vbox = QVBoxLayout()
            vbox.setContentsMargins(5, 5, 5, 5)
            frame.setLayout(vbox)
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
            vbox.addWidget(label)
            grid.addWidget(frame, i // 2, i % 2)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        outer.setStretchFactor(scroll, 1)
        self.setCentralWidget(central)


class OutputWindow(QMainWindow):
    """A separate window for viewing output text at full size.

    This window replicates the custom title bar with minimise and
    close buttons and can be dragged around the screen.  It displays
    the provided text in a read‑only QTextEdit that fills most of
    the window.  The window size is fixed to 1637×1088 by default.
    """

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