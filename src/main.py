# Neo8085 - 8085 Microprocessor Simulator
# Copyright (C) 2025 Shahibur Rahaman
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# Main module for Neo8085 - an 8085 microprocessor simulator
# with integrated editor, assembler, and debugging capabilities

# Standard library imports
import os
import sys

# Third-party imports
from PySide6.QtCore import (
    QDateTime,
    QElapsedTimer,
    QRect,
    QRegularExpression,
    QSize,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplashScreen,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from assembler import Assembler8085
from processor import Processor8085
from version import version_string, display_version

class ZoomMixin:
    def __init__(self, *args, **kwargs):
        font_point_size = kwargs["font_point_size"]
        del kwargs["font_point_size"]
        super(ZoomMixin, self).__init__(*args, **kwargs)
        self.font_point_size = font_point_size

    def zoom_in(self):
        """Zoom in"""
        current_size = self.font().pointSize()
        self.setFont(QFont(self.font().family(), current_size + 1))
        self.set_fixed_height()

    def zoom_out(self):
        """Zoom out"""
        current_size = self.font().pointSize()
        if current_size > (4 if self.font_point_size == 12 else (2 if self.font_point_size == 10 else 1)):
            self.setFont(QFont(self.font().family(), current_size - 1))
        self.set_fixed_height()

    def reset_zoom(self):
        """Reset zoom"""
        self.setFont(QFont(self.font().family(), self.font_point_size))
        self.set_fixed_height()

    def set_fixed_height(self):
        if type(self) == Header:
            fm = QFontMetrics(self.font())
            self.setFixedHeight(fm.height() * 1.43)


class Label(ZoomMixin, QLabel):
    """Label - QLabel wrapper"""

    def __init__(self, text: str, font_family="Consolas", font_point_size=12):
        super().__init__(text, font_point_size=font_point_size)
        self.setFont(QFont(font_family, font_point_size))


class Header(Label):
    """Header for different sections"""

    def __init__(self, header: str):
        super().__init__(header, font_family="Segoe UI", font_point_size=12)
        self.setFixedHeight(30)
        self.setStyleSheet(
            "background-color: #5C2D91; color: white; border: none;"
        )
        self.setAlignment(Qt.AlignCenter)


class LineEdit(ZoomMixin, QLineEdit):
    """LineEdit - QLineEdit wrapper"""

    def __init__(self, place_holder_text: str):
        super().__init__(font_point_size=10)
        self.setFont(QFont("Consolas", 10))
        self.setPlaceholderText(place_holder_text)


class TextEdit(ZoomMixin, QTextEdit):
    """TextEdit - QTextEdit wrapper"""

    def __init__(self):
        super().__init__(font_point_size=10)
        self.setFont(QFont("Consolas", 10))


class PushButton(ZoomMixin, QPushButton):
    """Label - QPushButton wrapper"""

    def __init__(self, text: str):
        super().__init__(text, font_point_size=10)
        self.setFont(QFont("Segoe UI", 10))


class TableWidgetItem(ZoomMixin, QTableWidgetItem):
    """TableWidgetItem - QTableWidgetItem wrapper"""

    def __init__(self, text: str):
        super().__init__(text, font_point_size=10)
        self.setFont(QFont("Segoe UI", 10))


# ZoomMixin did not work with QMenuBar, hence this is kind of a hack!
class MenuBar(QMenuBar):
    """MenuBar - QMenuBar wrapper"""
    def __init__(self, parent = None):
        super().__init__(parent)
        self.font_point_size = 10
        self.__style_sheet = """
            QMenuBar {{
                font: {size}pt "Segoe UI";
                background-color: white;
                color: #1E1E1E;
                border-bottom: 1px solid #DDDDDD;
                padding: 0px;
                margin: 0px;
            }}
            QMenuBar::item {{
                background: transparent;
                padding: 4px 10px;
            }}
            QMenuBar::item:selected {{
                background-color: #CBE3F8;
            }}
            QMenu {{
                font: {size}pt "Segoe UI";
                background-color: white;
                border: 1px solid #CCCCCC;
            }}
            QMenu::item:selected {{
                background-color: #CBE3F8;
            }}
        """
        self.setStyleSheet(self.__style_sheet.format(size=self.font_point_size))

    def zoom_in(self):
        """Zoom in"""
        current_size = self.font().pointSize()
        self.setStyleSheet(self.__style_sheet.format(size=current_size + 1))

    def zoom_out(self):
        """Zoom out"""
        current_size = self.font().pointSize()
        if current_size > 2:
            self.setStyleSheet(self.__style_sheet.format(size=current_size - 1))

    def reset_zoom(self):
        """Reset zoom"""
        self.setStyleSheet(self.__style_sheet.format(size=self.font_point_size))


class LineNumberArea(ZoomMixin, QWidget):
    """Widget for displaying line numbers and breakpoints in code editor"""

    def __init__(self, editor):
        super().__init__(editor, font_point_size=12)
        self.setFont(QFont("Consolas", 12))
        self.editor = editor
        self.simulator = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

    def set_simulator(self, simulator):
        """Store reference to simulator for logging capabilities"""
        self.simulator: Simulator = simulator

    def mousePressEvent(self, event):
        """Handle mouse clicks to toggle breakpoints on valid code lines"""
        # Calculate which line was clicked
        y_position = event.position().y()
        block = self.editor.firstVisibleBlock()
        top = (
            self.editor.blockBoundingGeometry(block)
            .translated(self.editor.contentOffset())
            .top()
        )

        # Find the text block (line) that was clicked
        while block.isValid():
            block_height = self.editor.blockBoundingRect(block).height()
            bottom = top + block_height

            if top <= y_position <= bottom:
                line_number = block.blockNumber()
                # Validate line has actual code (not empty or comment-only)
                block_text = (
                    self.editor.document().findBlockByNumber(line_number).text().strip()
                )
                if block_text and not block_text.startswith(";"):
                    self.editor.toggleBreakpoint(line_number)
                else:
                    if self.simulator:
                        self.simulator.add_to_log(
                            "Cannot add breakpoint on empty line or comment-only line",
                            "ERROR",
                        )
                break

            block = block.next()
            top = bottom


class AssemblyHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for 8085 assembly language with customized color scheme"""

    def __init__(self, document):
        super().__init__(document)

        self.highlighting_rules = []

        # Format definitions with appropriate colors for code elements
        instruction_format = QTextCharFormat()
        instruction_format.setForeground(QColor("#8A2BE2"))  # Purple
        instruction_format.setFontWeight(QFont.Weight.Bold)

        register_format = QTextCharFormat()
        register_format.setForeground(QColor("#2E8B57"))  # Sea Green

        decimal_format = QTextCharFormat()
        decimal_format.setForeground(QColor("#0000FF"))  # Blue

        hex_format = QTextCharFormat()
        hex_format.setForeground(QColor("#1E90FF"))  # Light Blue

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#808080"))  # Gray
        comment_format.setFontItalic(True)

        label_format = QTextCharFormat()
        label_format.setForeground(QColor("#800020"))  # Burgundy

        directive_format = QTextCharFormat()
        directive_format.setForeground(QColor("#FF6600"))  # Orange
        directive_format.setFontWeight(QFont.Weight.Bold)

        # 8085 instruction set
        instructions = [
            "MVI",
            "MOV",
            "LXI",
            "LDA",
            "STA",
            "ADD",
            "ADI",
            "SUB",
            "INR",
            "DCR",
            "JMP",
            "JZ",
            "JNZ",
            "JC",
            "JNC",
            "JP",
            "JM",
            "JPE",
            "JPO",
            "HLT",
            "INX",
            "PUSH",
            "POP",
            "CALL",
            "RET",
            "CPI",
            "DAD",
            "XCHG",
            "LDAX",
            "STAX",
            "LHLD",
            "SHLD",
            "PCHL",
            "SPHL",
            "XTHL",
            "ANA",
            "ANI",
            "ORA",
            "ORI",
            "XRA",
            "XRI",
            "CMA",
            "CMC",
            "STC",
            "RLC",
            "RRC",
            "RAL",
            "RAR",
            "ADC",
            "ACI",
            "SBB",
            "SBI",
            "DAA",
            "DCX",
            "CC",
            "CNC",
            "CZ",
            "CNZ",
            "CP",
            "CM",
            "CPE",
            "CPO",
            "RC",
            "RNC",
            "RZ",
            "RNZ",
            "RP",
            "RM",
            "RPE",
            "RPO",
            "RST",
            "CMP",
            "NOP",
        ]

        # Assembler directives
        directives = ["DS", "ORG", "END", "EQU"]

        # Create highlighting rules for instructions
        for instruction in instructions:
            pattern = QRegularExpression(
                f"\\b{instruction}\\b", QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            self.highlighting_rules.append((pattern, instruction_format))

        # Create highlighting rules for directives
        for directive in directives:
            pattern = QRegularExpression(
                f"\\b{directive}\\b", QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            self.highlighting_rules.append((pattern, directive_format))

        # Create highlighting rules for registers
        registers = ["A", "B", "C", "D", "E", "H", "L", "M", "SP", "PSW"]

        for reg in registers:
            pattern = QRegularExpression(
                f"\\b{reg}\\b", QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            self.highlighting_rules.append((pattern, register_format))

        # Highlighting rules for number formats
        hex_pattern = QRegularExpression("\\b[0-9A-Fa-f]+[Hh]\\b")
        self.highlighting_rules.append((hex_pattern, hex_format))

        decimal_pattern = QRegularExpression("\\b[0-9]+\\b(?![Hh])")
        self.highlighting_rules.append((decimal_pattern, decimal_format))

        # Highlighting rules for comments and labels
        comment_pattern = QRegularExpression(";.*")
        self.highlighting_rules.append((comment_pattern, comment_format))

        label_pattern = QRegularExpression("\\b[A-Za-z_][A-Za-z0-9_]*:")
        self.highlighting_rules.append((label_pattern, label_format))

    def highlightBlock(self, text):
        """Apply defined highlighting rules to each text block"""
        for pattern, format in self.highlighting_rules:
            match = pattern.globalMatch(text)
            while match.hasNext():
                match_result = match.next()
                self.setFormat(
                    match_result.capturedStart(), match_result.capturedLength(), format
                )


class LineNumberedEditor(ZoomMixin, QPlainTextEdit):
    """Code editor with line numbers, syntax highlighting, and breakpoint support"""

    def __init__(self):
        super().__init__(font_point_size=12)
        self.setPlaceholderText("Enter 8085 Assembly Code Here...")
        self.setFont(QFont("Consolas", 12))

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)

        # Initialize syntax highlighter
        self.highlighter = AssemblyHighlighter(self.document())

        # Light theme styling
        self.setStyleSheet(
            """
        QPlainTextEdit {
            background-color: white;
            color: #1E1E1E;
            padding: 0px;
            selection-background-color: #0B91FF;
            selection-color: white;
        }
        QScrollBar:vertical {
            border: none;
            background: #F0F0F0;
            width: 10px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #AAAAAA;
            min-height: 30px;
        }
        QScrollBar::handle:vertical:hover {
            background: #888888;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
            background: none;
            border: none;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
        """
        )

        # Status bar for cursor position display
        self.status_bar = Label("Ln 1, Col 1", font_family="Segoe UI", font_point_size=9)
        self.status_bar.setStyleSheet(
            "background-color: white; padding: 2px 5px; border: none; solid #DDDDDD;"
        )
        self.status_bar.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.lineNumberArea = LineNumberArea(self)
        self.breakpoints = set()

        # Connect signals for UI updates
        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.updateCursorPosition)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()
        self.updateCursorPosition()

    def updateCursorPosition(self):
        """Update status bar with current cursor position information"""
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        chars = len(self.toPlainText())

        self.status_bar.setText(f"Ln {line}, Col {col}, Chars: {chars}")

    def lineNumberAreaWidth(self):
        """Calculate required width for line number display area"""
        digits = len(str(self.blockCount())) + (2 if self.lineNumberArea.simulator is None
                                                 or len(self.lineNumberArea.simulator.processor.line_to_address_map) == 0
                                                   else 8)
        return 15 + self.fontMetrics().horizontalAdvance("9") * digits

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        """Update line number area on scroll or text changes"""
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(
                0, rect.y(), self.lineNumberArea.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        """Handle resize events to adjust line number area dimensions"""
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.lineNumberArea.setGeometry(
            QRect(rect.left(), rect.top(), self.lineNumberAreaWidth(), rect.height())
        )

    def lineNumberAreaPaintEvent(self, event):
        """Render line numbers and breakpoint indicators in the line number area"""
        painter = QPainter(self.lineNumberArea)
        painter.fillRect(event.rect(), QColor("#F0F0F0"))

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_to_address_map = self.lineNumberArea.simulator.processor.line_to_address_map
                line_number = blockNumber + 1
                number = (str(line_number) if len(line_to_address_map) == 0
                          else
                            (f"{line_number}      ") if line_number not in line_to_address_map
                                else f"{line_number} {line_to_address_map[line_number]:04X}H")
                painter.setPen(QColor("#6D6D6D"))

                # Draw breakpoint marker
                if blockNumber in self.breakpoints:
                    painter.setPen(QColor("#DA0000"))
                    painter.setBrush(QColor("#DA0000"))
                    painter.drawEllipse(3, int(top) + 4, 8, 8)
                    painter.setPen(QColor("#6D6D6D"))

                painter.drawText(
                    0,
                    int(top),
                    self.lineNumberArea.width() - 5,
                    int(self.fontMetrics().height()),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            blockNumber += 1

    def highlightCurrentLine(self):
        """Highlight the line containing the cursor"""
        extraSelections = []
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#E6F2FF"))
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        extraSelections.append(selection)
        self.setExtraSelections(extraSelections)

    def highlightExecutedLine(self, line):
        """Highlight the currently executing line during simulation"""
        cursor = QTextCursor(self.document().findBlockByLineNumber(line))

        # Temporarily disconnect to prevent interference
        self.cursorPositionChanged.disconnect(self.highlightCurrentLine)

        # Create execution highlight with light purple background
        extraSelections = []
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#E6D9EC"))
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = cursor
        selection.cursor.clearSelection()
        extraSelections.append(selection)

        # Apply the highlight
        self.setExtraSelections(extraSelections)

        # Ensure line is visible in the viewport
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

        # Force update to make the highlight visible immediately
        QApplication.processEvents()

        # Reconnect signal
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

    def toggleBreakpoint(self, line):
        """Toggle breakpoint state for the specified line"""
        if line in self.breakpoints:
            self.breakpoints.remove(line)
        else:
            self.breakpoints.add(line)

        # Refresh line number area display
        self.lineNumberArea.update()

    def zoom_in(self):
        """Zoom in"""
        super().zoom_in()
        self.lineNumberArea.zoom_in()

    def zoom_out(self):
        """Zoom out"""
        super().zoom_out()
        self.lineNumberArea.zoom_out()

    def reset_zoom(self):
        """Reset zoom"""
        super().reset_zoom()
        self.lineNumberArea.reset_zoom()

class Simulator(QWidget):
    """Main simulator application for the 8085 microprocessor"""

    def __init__(self):
        super().__init__()
        self.processor = Processor8085()
        self.execution_log = []
        self.execution_count = 0
        self.current_file = None
        self.user_memory_addr = 0x0000
        self.follow_pc = False
        self.use_highlighting = True
        self.document_modified = False

        # Performance tracking
        self.elapsed_timer = QElapsedTimer()
        self.elapsed_time_ms = 0
        self.timer_running = False

        self.init_ui()

    def start_elapsed_timer(self):
        """Start or resume execution timing"""
        if not self.timer_running:
            self.elapsed_timer.start()
            self.timer_running = True

    def stop_elapsed_timer(self):
        """Stop execution timer and update elapsed time"""
        if self.timer_running:
            self.elapsed_time_ms += self.elapsed_timer.elapsed()
            self.timer_running = False
            self.update_elapsed_time_display()

    def reset_elapsed_timer(self):
        """Reset execution timer statistics"""
        self.elapsed_time_ms = 0
        self.timer_running = False
        self.update_elapsed_time_display()

    def update_elapsed_time_display(self):
        """Format and display elapsed execution time with appropriate units"""
        total_ms = self.elapsed_time_ms

        if self.timer_running:
            total_ms += self.elapsed_timer.elapsed()

        # Select appropriate time unit based on duration
        if total_ms < 1000:  # Less than 1 second
            time_str = f"{total_ms} ms"
        elif total_ms < 60000:  # Less than 1 minute
            time_str = f"{total_ms / 1000:.2f} s"
        else:  # Minutes and seconds
            minutes = int(total_ms / 60000)
            seconds = (total_ms % 60000) / 1000
            time_str = f"{minutes}:{seconds:06.3f}"

        self.exec_time_label.setText(f"Elapsed Time: {time_str}")

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle(
            f"Neo8085 v{display_version} - 8085 Microprocessor Simulator"
        )
        self.setGeometry(100, 50, 1280, 800)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create menu bar
        self.menu_bar = MenuBar(self)

        # File Menu
        file_menu = self.menu_bar.addMenu("File")

        new_action = QAction("New File", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_file)
        file_menu.addAction(new_action)

        load_action = QAction("Open Program", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.load_program)
        file_menu.addAction(load_action)

        file_menu.addSeparator()

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_program)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_program_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Run Menu
        run_menu = self.menu_bar.addMenu("Simulator")

        compile_action = QAction("Assemble", self)
        compile_action.setShortcut(QKeySequence("Ctrl+B"))
        compile_action.triggered.connect(self.compile_program)

        step_action = QAction("Step", self)
        step_action.setShortcut(QKeySequence("F10"))
        step_action.triggered.connect(self.execute_single_step)

        run_action = QAction("Run", self)
        run_action.setShortcut(QKeySequence("F5"))
        run_action.triggered.connect(self.start_continuous_execution)

        run_fast_action = QAction("Run without Highlighting", self)
        run_fast_action.setShortcut(QKeySequence("Ctrl+Shift+F5"))
        run_fast_action.triggered.connect(self.start_fast_execution)

        stop_action = QAction("Stop", self)
        stop_action.setShortcut(QKeySequence("F8"))
        stop_action.triggered.connect(self.stop_execution)

        reset_action = QAction("Reset", self)
        reset_action.setShortcut(QKeySequence("Ctrl+R"))
        reset_action.triggered.connect(self.reset_simulation)

        run_menu.addAction(compile_action)
        run_menu.addAction(step_action)
        run_menu.addAction(run_action)
        run_menu.addAction(run_fast_action)
        run_menu.addAction(stop_action)
        run_menu.addAction(reset_action)

        # Debug Menu
        debug_menu = self.menu_bar.addMenu("Debug")
        add_bp_action = QAction("Add Breakpoint", self)
        add_bp_action.setShortcut("F9")
        add_bp_action.triggered.connect(self.add_breakpoint)
        remove_bp_action = QAction("Remove Breakpoint", self)
        remove_bp_action.triggered.connect(self.remove_breakpoint)
        remove_all_bp_action = QAction("Remove All Breakpoints", self)
        remove_all_bp_action.triggered.connect(self.remove_all_breakpoints)
        debug_menu.addAction(add_bp_action)
        debug_menu.addAction(remove_bp_action)
        debug_menu.addAction(remove_all_bp_action)

        # Zoom Menu
        zoom_menu = self.menu_bar.addMenu("Zoom")
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut("Ctrl+=")
        zoom_in_action.triggered.connect(self.zoom_in)
        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(self.zoom_out)
        reset_zoom_action = QAction("Reset Zoom", self)
        reset_zoom_action.setShortcut("Ctrl+0")
        reset_zoom_action.triggered.connect(self.reset_zoom)
        zoom_menu.addAction(zoom_in_action)
        zoom_menu.addAction(zoom_out_action)
        zoom_menu.addAction(reset_zoom_action)

        # Help Menu
        help_menu = self.menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        main_layout.addWidget(self.menu_bar)

        # Content Splitter
        content_splitter = QSplitter()
        content_splitter.setContentsMargins(0, 0, 5, 5)
        # Content Layout, this should be QVBoxLayout with just splitter
        content_layout = QVBoxLayout()

        # Left Part
        left_part = QWidget()
        # Left Panel - Code Editor and Execution Log
        left_panel = QVBoxLayout(left_part)

        # Global styling
        self.setStyleSheet(
            """
            QWidget {
                background-color: #EDEDED;
                color: #1E1E1E;
            }
            QScrollBar:vertical {
                border: none;
                background: #F0F0F0;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #AAAAAA;
                min-height: 30px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #888888;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                border: none;
                background: #F0F0F0;
                height: 10px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #AAAAAA;
                min-width: 30px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #888888;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """
        )

        self.code_editor = LineNumberedEditor()

        # Connect line number area to simulator for error logging
        self.code_editor.lineNumberArea.set_simulator(self)

        # Code editor layout with status bar
        editor_layout = QVBoxLayout()
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        editor_layout.addWidget(self.code_editor)
        editor_layout.addWidget(self.code_editor.status_bar)

        left_panel.addLayout(editor_layout, 4)

        # Context menu for breakpoints
        self.code_editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.code_editor.customContextMenuRequested.connect(
            self.show_editor_context_menu
        )

        # Execution log and converter section
        log_converter_layout = QHBoxLayout()

        # Execution Log
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)

        log_header_layout = QHBoxLayout()
        log_header_layout.setContentsMargins(0, 0, 0, 0)
        log_header_layout.setSpacing(0)

        log_header = Header("EXECUTION LOG")
        log_header_layout.addWidget(log_header, 9)

        self.clear_log_button = PushButton("Clear")
        self.clear_log_button.setStyleSheet(
            """
            QPushButton {
                background-color: #8D56CA;
                color: white;
                border: 2px solid #D3BEEB;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #5C2D91;
                border: 2px solid #8D56CA;
            }
        """
        )
        log_header_layout.addWidget(self.clear_log_button, 1)
        self.clear_log_button.clicked.connect(self.clear_execution_log)

        log_layout.addLayout(log_header_layout)
        
        # Execution log widget
        self.execution_log_widget = TextEdit()
        self.execution_log_widget.setReadOnly(True)
        self.execution_log_widget.clear()

        self.execution_log_widget.setStyleSheet(
            """
            QTextEdit {
                background-color: white; 
                color: #1E1E1E; 
                padding: 5px;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #F0F0F0;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #AAAAAA;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #888888;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """
        )

        log_layout.addWidget(self.execution_log_widget, 1)
        log_converter_layout.addLayout(log_layout, 2)

        # Right side layout for converter and memory editor
        right_side_layout = QVBoxLayout()

        # Number converter widget
        converter_widget = self.create_converter()
        right_side_layout.addWidget(converter_widget)

        # Memory editor widget
        memory_editor_widget = self.create_memory_editor()
        right_side_layout.addWidget(memory_editor_widget)

        log_converter_layout.addLayout(right_side_layout, 1)
        left_panel.addLayout(log_converter_layout, 2)

        # Right Part
        right_part = QWidget()
        # Right Panel - Registers, Flags, and Memory
        right_panel = QVBoxLayout(right_part)

        # Simulator header
        simulator_header = Header("SIMULATOR OPERATIONS")
        right_panel.addWidget(simulator_header)

        # Control buttons
        control_layout = QHBoxLayout()

        self.compile_button = PushButton("Assemble")
        self.compile_button.setStyleSheet(
            """
            QPushButton {
                background-color: #458ADB; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #3A75C4;
            }
        """
        )
        self.compile_button.clicked.connect(self.compile_program)

        self.step_button = PushButton("Step")
        self.step_button.setStyleSheet(
            """
            QPushButton {
                background-color: #B8A404; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #9E8C03;
            }
        """
        )
        self.step_button.clicked.connect(self.execute_single_step)

        self.run_button = PushButton("Run")
        self.run_button.setStyleSheet(
            """
            QPushButton {
                background-color: #0DB000; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #0A9000;
            }
        """
        )
        self.run_button.clicked.connect(self.start_continuous_execution)

        self.stop_button = PushButton("Stop")
        self.stop_button.setStyleSheet(
            """
            QPushButton {
                background-color: #C42B1C; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #A82318;
            }
        """
        )
        self.stop_button.clicked.connect(self.stop_execution)
        self.stop_button.setEnabled(False)

        self.reset_button = PushButton("Reset")
        self.reset_button.setStyleSheet(
            """
            QPushButton {
                background-color: white; 
                color: #1E1E1E; 
                border: 2px solid #DDDDDD; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #F0F0F0;
                border: 2px solid #BBBBBB;
            }
        """
        )
        self.reset_button.clicked.connect(self.reset_simulation)

        control_layout.addWidget(self.compile_button)
        control_layout.addWidget(self.step_button)
        control_layout.addWidget(self.run_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.reset_button)

        right_panel.addLayout(control_layout)

        # Status display
        self.status_label = Label("Ready", font_family="Segoe UI", font_point_size=10)
        self.status_label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        self.set_status("Ready", "normal")
        right_panel.addWidget(self.status_label)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #555;")
        right_panel.addWidget(separator)

        # Registers and Stack display
        registers_stack_layout = QHBoxLayout()

        self.register_labels = {}

        self.registers_grid = QGridLayout()

        # Registers header
        register_header = Header("REGISTERS")
        self.registers_grid.addWidget(register_header, 0, 0, 1, 2)

        # A Register & Flags
        self.add_register("A", 1, 0)
        self.flags_group = Flags(self)
        self.registers_grid.addWidget(self.flags_group, 1, 1)

        # PSW Register - Full Width
        self.add_register("PSW", 2, 0, 1, 2)

        # B, C, D, E, H, L Registers - Two Columns
        self.add_register("B", 3, 0)
        self.add_register("C", 3, 1)
        self.add_register("D", 4, 0)
        self.add_register("E", 4, 1)
        self.add_register("H", 5, 0)
        self.add_register("L", 5, 1)

        # SP and PC Registers - Full Width
        self.add_register("SP", 6, 0, 1, 2)
        self.add_register("PC", 7, 0, 1, 2)

        self.stack = Stack(self)

        registers_stack_layout.addLayout(self.registers_grid, 1)
        registers_stack_layout.addLayout(self.stack, 1)
        
        right_panel.addLayout(registers_stack_layout)
        self.update_registers_display()

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #555;")
        right_panel.addWidget(separator)

        # Memory View
        memory_header = Header("MEMORY")
        right_panel.addWidget(memory_header)

        # Memory Search Bar
        memory_search_layout = QHBoxLayout()

        self.memory_search = LineEdit("Enter memory address (e.g., 8000, 2000H)")
        self.memory_search.setStyleSheet(
            "background-color: white; color: #1E1E1E; border: 1px solid #DDDDDD; padding: 5px;"
        )
        self.memory_search.returnPressed.connect(self.load_memory_address)
        self.memory_search.textChanged.connect(self.validate_memory_address)
        self.memory_search.setValidator(None)
        memory_search_layout.addWidget(self.memory_search, 4)

        # Add Enter button
        self.memory_enter_button = PushButton("Enter")
        self.memory_enter_button.setStyleSheet(
            """
            QPushButton {
                background-color: white;
                color: #1E1E1E;
                border: 1px solid #DDDDDD;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #E6F2FF;
                border: 1px solid #BBBBBB;
            }
        """
        )
        self.memory_enter_button.clicked.connect(self.load_memory_address)
        memory_search_layout.addWidget(self.memory_enter_button, 1)

        self.follow_pc_button = PushButton("Follow PC")
        self.follow_pc_button.setCheckable(True)
        self.follow_pc_button.setChecked(False)
        self.follow_pc_button.setStyleSheet(
            """
            QPushButton {
                background-color: white;
                color: #1E1E1E;
                border: 1px solid #DDDDDD;
                padding: 5px;
            }
            QPushButton:checked {
                background-color: #007ACC;
                color: white;
            }
            QPushButton:hover:!checked {
                background-color: #E6F2FF;
                border: 1px solid #BBBBBB;
            }
        """
        )
        self.follow_pc_button.clicked.connect(self.toggle_follow_pc)
        memory_search_layout.addWidget(self.follow_pc_button, 1)

        right_panel.addLayout(memory_search_layout)

        # Memory Table of 16 rows, 18 columns (decimal+hex address + 16 bytes)
        self.memory_table = MemoryTableWidget(16, 18, self)
        right_panel.addWidget(self.memory_table)

        # Execution Statistics
        stats_layout = QHBoxLayout()

        self.instr_count_label = Label("Instructions: 0", font_family="Segoe UI", font_point_size=10)
        self.instr_count_label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )

        self.exec_time_label = Label("Elapsed Time: 0 ms", font_family="Segoe UI", font_point_size=10)
        self.exec_time_label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )

        stats_layout.addWidget(self.instr_count_label)
        stats_layout.addWidget(self.exec_time_label)

        right_panel.addLayout(stats_layout)

        # Add left part to main content
        content_splitter.addWidget(left_part)
        # Add right part to main content
        content_splitter.addWidget(right_part)
        content_splitter.setStretchFactor(0, 55) # Left panel gets more horizontal space
        content_splitter.setStretchFactor(1, 45) # Right panel gets less horizontal space

        # content splitter needs to occupy whole of the vertical space otherwise
        # menubar has some white spaces, this can be kind of a hack!
        content_layout.addWidget(content_splitter, 1)
        main_layout.addLayout(content_layout)

        # Set up the main layout
        self.setLayout(main_layout)

        # Set up execution timer
        self.execution_timer = QTimer()
        self.execution_timer.timeout.connect(self.execute_single_step)

        # Initialize memory view
        self.load_memory_display(0x0000)

        # Set code editor with sample program
        self.code_editor.setPlainText(
            rf"""; +===================================================================+
;     _   __           ____  ____  ____  ______
;    / | / /__  ____  ( __ )/ __ \( __ )/ ____/
;   /  |/ / _ \/ __ \/ __  / / / / __  /___ \  
;  / /|  /  __/ /_/ / /_/ / /_/ / /_/ /___/ /  
; /_/ |_/\___/\____/\____/\____/\____/_____/  
;
; Version: {display_version}
;
; Copyright 2025 (c) Shahibur Rahaman
; Licensed under GNU GPL v3.0
;
; +==================================================================+
; |       Welcome to Neo8085 - 8085 Microprocessor Simulator         |
; +==================================================================+
;
; SIMULATOR USAGE INSTRUCTIONS:
; ----------------------------
; 1. EDITING & SAVING:
;    - Type your assembly code in this editor
;    - Save/Open files using File menu or Ctrl+S / Ctrl+O
;    - Modified files show an asterisk (*) in the title bar
;
; 2. ASSEMBLING & EXECUTION:
;    - Click "Assemble
;    - "Step" (F10) to execute one instruction at a time
;    - "Run" (F5) to execute continuously with highlighting
;    - "Fast mode" (Ctrl+Shift+F5) to execute at higher speed without highlighting
;    - "Stop" (F8) to pause continuous execution
;    - "Reset" to clear processor state and memory
;
; 3. DEBUGGING FEATURES:
;    - Add breakpoints by clicking in the line number margin
;    - Or use F9 to add a breakpoint at the current line
;    - Use the Memory Editor to modify memory
;    - Use Memory table view to inspect and analyze the memory during execution
;    - Follow PC button (toggle) tracks the Program Counter in memory
;
; 4. DIRECTIVE USAGE:
;    - ORG: Set starting address - e.g., "ORG 2000H"
;    - EQU: Define constants (supports arithmetic operations too) - e.g., "COUNT: EQU 5 * 5"
;    - DS: Reserve memory space - e.g., "BUFFER: DS 10" 
;    - END: A Placeholder representing the logical end of the progam
;    - NOTE! Use JUMP instructions before "DS" directives to prevent no instruction found error. 
;
; EXAMPLE PROGRAM BELOW DEMONSTRATES:
; - EQU nested directives with arithmetic
; - Memory operations
; - Register manipulation
; - Program logic and looping
; +===================================================================+
;
; ===================================================================
;              FIBONACCI SERIES CALCULATION AND STORAGE
; ===================================================================

; - After assembling the code use the memory table view's search field
;   to locate the loaded program (e.g., 2000H for our example program).
; - Use "Follow PC" (toggle) to easily locate the current row of memory
;   that is being executed (16 bytes per row). 

ORG 2000H		; Due to presence of 'H' suffix this is treated as HEX value

JMP START

FIRST_ELEMENT:	EQU 0	; Treated as DECIMAL value due to lack of 'H' suffix
SECOND_ELEMENT:	EQU 1	; Treated as DECIMAL value due to lack of 'H' suffix
ELEMENTS_COUNT: 	EQU 0AH  ; 10 ELEMENTS (Treated as HEX value due to presence of 'H' suffix)
LOOP_COUNTER:	EQU ELEMENTS_COUNT - 1 ; FIRST ONE ELEMENT IS NOT NEEDED FOR LOOPING

; RESERVING MEMORY SPACE FOR STORING FIBONACCI SERIES
DATA_AREA: DS ELEMENTS_COUNT

START:	JMP FIBONACCI_SERIES_SETUP	; Jump to the respective label

FIBONACCI_SERIES_SETUP:
	MVI A, FIRST_ELEMENT
	MVI B, SECOND_ELEMENT
	MVI D, LOOP_COUNTER
	LXI H, DATA_AREA
	MOV M, A		; STORING THE FIRST ELEMENT IN MEMORY
	INX H		; INCREASING MEMORY ADDRESS REGISTER VALUE (H-L REGISTER PAIR)
	JMP FIBONACCI_CALC_LOOP

FIBONACCI_CALC_LOOP:
	MOV C, A
	ADD B
	MOV B, C
	DCR D		; DECREASE THE VALUE OF THE LOOP COUNTER REGISTER
	MOV M, A
	INX H
	JNZ FIBONACCI_CALC_LOOP
	JMP END_OF_PROGRAM

END_OF_PROGRAM:
	HLT

END

"""
        )

        # Connect to the textChanged signal of the code editor
        self.code_editor.textChanged.connect(self.document_was_modified)

    def add_register(self, name, row, col, rowspan=1, colspan=1):
        """Add a register display to the UI"""
        value = "00H" if name not in ["SP", "PC", "PSW"] else "0000H"
        label = Label(f"{name}: {value}")
        label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )
        label.setAlignment(Qt.AlignCenter)
        self.registers_grid.addWidget(label, row, col, rowspan, colspan)
        self.register_labels[name] = label

    def update_registers_display(self):
        """Update register display from processor state"""
        for reg, value in self.processor.registers.items():
            if reg in self.register_labels:
                # Format the value based on register type
                if reg in ["SP", "PC"]:
                    hex_value = f"{value:04X}H"
                else:
                    hex_value = f"{value:02X}H"
                self.register_labels[reg].setText(f"{reg}: {hex_value}")

        # Update flags display from processor state
        self.flags_group.update_display()
        self.stack.update_display()

        # Update PSW display - combining A register and flags
        if "PSW" in self.register_labels:
            psw_value = self.processor.get_psw()
            self.register_labels["PSW"].setText(f"PSW: {psw_value:04X}H")

    def start_fast_execution(self):
        """Start continuous execution mode without code highlighting for better performance"""
        # Set the highlighting flag to False for faster execution
        self.use_highlighting = False

        # Assemble if not already done
        if (
                not hasattr(self.processor, "parsed_program")
                or not self.processor.parsed_program
        ):
            if not self.compile_program():
                return

        # Check if processor is already halted
        if self.processor.halted:
            self.add_to_log(
                "Cannot run - program has halted. Reset or assemble again.", "SYSTEM"
            )
            self.set_status("Program halted - Reset to run again", "warning")
            return

        # Start elapsed timer
        self.start_elapsed_timer()

        # Continue with normal execution if not halted
        self.running = True
        self.execution_timer.start(10)  # Execute faster - every 10ms instead of 50ms

        # Update UI state
        self.compile_button.setEnabled(False)
        self.step_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.set_status("Running (fast mode)...", "success")

        self.add_to_log("Fast execution started (no highlighting)", "SYSTEM")

    def parse_address(self, addr_text):
        """Parse address text using 8085 conventions.
        - With 'H' or 'h' suffix: hexadecimal
        - Otherwise: decimal
        Returns the parsed integer address.
        """
        addr_text = addr_text.strip()
        if addr_text.upper().endswith("H"):
            # Hex address
            try:
                return int(addr_text[:-1], 16)
            except ValueError:
                raise ValueError(f"Invalid hexadecimal address: {addr_text}")
        else:
            # Decimal address
            try:
                return int(addr_text, 10)
            except ValueError:
                raise ValueError(f"Invalid decimal address: {addr_text}")

    def load_memory_display(self, base_addr=0x0000):
        """Load memory view starting at base_addr"""
        # Address is aligned to 16-byte boundary
        base_addr = base_addr & 0xFFF0

        for row in range(16):
            row_addr = base_addr + (row * 16)
            # Set decimal address
            self.memory_table.setItem(row, 0, QTableWidgetItem(f"{row_addr}"))
            # Set hex address
            self.memory_table.setItem(row, 1, QTableWidgetItem(f"{row_addr:04X}H"))

            for col in range(16):
                addr = row_addr + col
                value = (
                    self.processor.memory[addr]
                    if hasattr(self.processor, "memory")
                    else 0
                )
                self.memory_table.setItem(
                    row, col + 2, QTableWidgetItem(f"{value:02X}")
                )

    def load_memory_address(self):
        """Jump to a specific memory address in the memory view"""
        addr_text = self.memory_search.text().strip()
        if not addr_text:
            return

        try:
            base_addr = self.parse_address(addr_text)

            # Ensure address is within valid memory range
            if base_addr < 0:
                base_addr = 0
                self.add_to_log("Address adjusted to minimum (0)", "SYSTEM")
            elif base_addr > 0xFFFF:
                base_addr = 0xFFFF
                self.add_to_log("Address adjusted to maximum (65535/FFFFH)", "SYSTEM")

            # If address is near the end of memory, adjust to show last complete page
            if base_addr > 0xFF00:  # 65280 decimal
                base_addr = 0xFF00  # Start the view from the last page
                self.add_to_log(
                    "Address adjusted to show last memory page (65280/FF00H)", "SYSTEM"
                )

            self.user_memory_addr = base_addr  # Store user's preference
            self.follow_pc = (
                False  # User has requested specific view, stop following PC
            )
            self.follow_pc_button.setChecked(False)
            self.load_memory_display(base_addr)

            # Show the format of the address that was interpreted
            if addr_text.upper().endswith("H"):
                self.add_to_log(f"Viewing memory at {base_addr:04X}H (hex)", "SYSTEM")
            else:
                self.add_to_log(f"Viewing memory at {base_addr} (decimal)", "SYSTEM")

        except ValueError as e:
            self.memory_search.setText("Invalid Address")
            self.memory_search.selectAll()
            self.add_to_log(f"Error: {str(e)}", "ERROR")

    def validate_memory_address(self, text):
        """Validate memory address input as user types"""
        if not text:
            return

        # Check if it's a decimal number or hex (with H/h suffix)
        if text.upper().endswith("H"):
            # Handle hex input
            hex_val = text[:-1]
            try:
                value = int(hex_val, 16)
                if value > 0xFFFF:
                    self.memory_search.setText(hex_val[:-1] + text[-1])
            except ValueError:
                # Invalid characters were entered - nothing to do as validator handles this
                pass
        else:
            # Handle decimal input
            try:
                value = int(text)
                if value > 65535:
                    self.memory_search.setText(text[:-1])
            except ValueError:
                # Invalid characters were entered - nothing to do as validator handles this
                pass

    def compile_program(self):
        """Compile the assembly code with syntax checking"""
        code = self.code_editor.toPlainText().splitlines()

        try:
            # Use the assembler to parse the code
            assembler = Assembler8085()
            assembly_output = assembler.assemble(code)

            # Load the assembled program into the processor
            self.processor = Processor8085()
            self.processor.load_program(assembly_output)

            # Update UI
            self.update_registers_display()
            self.code_editor.updateLineNumberAreaWidth(0)
            # By setting the text to ORG address we are allowing the user to
            # switch between Follow PC or ORG easily
            self.memory_search.setText(f"{assembly_output.starting_address:04X}H")
            self.memory_enter_button.click()

            self.add_to_log("Program assembled successfully", "SYSTEM")
            self.add_to_log("Machine code loaded into memory", "SYSTEM")
            self.set_status("Assembled - Ready to Execute", "success")

            # Reset execution statistics and timer
            self.execution_count = 0
            self.instr_count_label.setText("Instructions: 0")
            self.reset_elapsed_timer()

            self.highlight_current_instruction()

            return True

        except SyntaxError as e:
            # Handle syntax errors with detailed messages
            error_msg = str(e)
            self.add_to_log(f"Assembly error: {error_msg}", "ERROR")
            self.set_status(f"Assembly Failed: Syntax Error", "error")

            # Show error message box with details
            QMessageBox.critical(self, "Assembly Error", error_msg)
            return False

        except Exception as e:
            # Handle other unexpected errors
            self.add_to_log(f"Assembly error: {str(e)}", "ERROR")
            self.set_status("Assembly Failed: Unknown Error", "error")

            # Show error message box
            QMessageBox.critical(
                self, "Assembly Error", f"An unexpected error occurred:\n{str(e)}"
            )
            return False

    def execute_single_step(self):
        """Execute a single instruction"""
        # Make sure we have an assembled program
        if (
                not hasattr(self.processor, "parsed_program")
                or not self.processor.parsed_program
        ):
            self.compile_program()
            return

        # Start timing for this step
        self.start_elapsed_timer()

        # Return immediately if processor is already halted
        if self.processor.halted:
            # Make sure execution is fully stopped if we're in continuous mode
            if hasattr(self, "running") and self.running:
                self.stop_execution()
            return "HALT"

        # Get last PC and find corresponding line
        last_pc = self.processor.registers["PC"]
        last_line_num = self.processor.address_to_line_map.get(last_pc)

        # Check for breakpoints when running continuously
        if (
                hasattr(self, "running")
                and self.running
                and last_line_num is not None
                and (last_line_num - 1) in self.code_editor.breakpoints
        ):
            self.add_to_log(f"Breakpoint hit at line {last_line_num}", "SYSTEM")
            self.stop_execution()
            # Always highlight on breakpoint hit, even in fast mode
            self.code_editor.highlightExecutedLine(
                last_line_num - 1
            )  # Convert to 0-indexed for highlighting
            return

        # Execute one instruction
        result = self.processor.step()

        self.highlight_current_instruction()

        # Update execution count
        self.execution_count += 1
        self.instr_count_label.setText(f"Instructions: {self.execution_count}")

        # Update elapsed time display
        self.update_elapsed_time_display()

        # When running in single-step mode, stop the timer after each step
        if not hasattr(self, "running") or not self.running:
            self.stop_elapsed_timer()

        # Log the instruction that was executed - only in normal mode or for important events
        if self.processor.last_instruction and (
                self.use_highlighting or result != "OK"
        ):
            self.add_to_log(f"{last_pc:04X}: {self.processor.last_instruction}", result)

        # Update UI components
        self.update_registers_display()
        self.update_memory_view()

        # Check execution status
        if result == "HALT":
            self.set_status("Program halted", "warning")
            # Stop continuous execution when HLT is encountered
            self.stop_execution()
        elif result == "ERROR":
            self.set_status(f"Error: {self.processor.error}", "error")
            self.stop_execution()

        return result

    def highlight_current_instruction(self):
        """Highlight current instruction"""
        # Get current PC and find corresponding line
        cuurent_pc = self.processor.registers["PC"]
        line_num = self.processor.address_to_line_map.get(cuurent_pc)

        # Highlight the current line before executing (only if highlighting is enabled)
        if self.use_highlighting and line_num is not None:
            self.code_editor.highlightExecutedLine(
                line_num - 1
            )  # Convert to 0-indexed for highlighting

    def start_continuous_execution(self):
        """Start continuous execution mode"""
        # Assemble if not already done
        if (
                not hasattr(self.processor, "parsed_program")
                or not self.processor.parsed_program
        ):
            if not self.compile_program():
                return

        # Check if processor is already halted
        if self.processor.halted:
            self.add_to_log(
                "Cannot run - program has halted. Reset or assemble again.", "SYSTEM"
            )
            self.set_status("Program halted - Reset to run again", "warning")
            return

        # Set the highlighting flag to True for normal execution
        self.use_highlighting = True

        # Start elapsed timer
        self.start_elapsed_timer()

        # Continue with normal execution if not halted
        self.running = True
        self.execution_timer.start(50)  # Execute every 50ms

        # Update UI state
        self.compile_button.setEnabled(False)
        self.step_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.set_status("Running...", "success")

        self.add_to_log("Continuous execution started", "SYSTEM")

    def stop_execution(self):
        """Stop continuous execution"""
        self.running = False
        self.execution_timer.stop()

        # Stop elapsed timer
        self.stop_elapsed_timer()

        # Reset to default highlighting mode
        self.use_highlighting = True

        # Update UI state
        self.compile_button.setEnabled(True)
        self.step_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        if not self.processor.halted and not self.processor.error:
            self.set_status("Execution Paused", "warning")
            self.add_to_log("Execution paused", "SYSTEM")

    def update_memory_view(self):
        """Update memory view based on current state"""
        pc = self.processor.registers["PC"]

        # Only change memory view base address if we're in follow-PC mode
        if self.follow_pc:
            # Align to 16-byte boundary and show memory chunk containing PC
            base_addr = pc & 0xFFF0
            self.load_memory_display(base_addr)
        else:
            # Just update the values without changing the view location
            self.update_memory_values()

    def update_memory_values(self):
        """Update memory values without changing the current view"""
        try:
            # Get the base address from the hex address column (column 1)
            base_addr_text = self.memory_table.item(0, 1).text()

            # Parse the hex address (remove the 'H' suffix if present)
            if base_addr_text.upper().endswith("H"):
                base_addr = int(base_addr_text[:-1], 16)
            else:
                base_addr = int(base_addr_text, 16)

            # Update only the memory values (columns 2-17), not the address columns
            for row in range(16):
                row_addr = base_addr + (row * 16)

                for col in range(16):
                    addr = row_addr + col
                    value = self.processor.memory[addr]
                    # Update memory value column (col+2 since columns 0,1 are addresses)
                    self.memory_table.item(row, col + 2).setText(f"{value:02X}")
        except (ValueError, AttributeError) as e:
            # Handle case where table might not be fully initialized yet
            self.add_to_log(f"Memory view update error: {str(e)}", "ERROR")

    def add_breakpoint(self):
        """Add breakpoint at the current line if not empty"""
        cursor = self.code_editor.textCursor()
        line_num = cursor.blockNumber()

        # Check if line is not empty
        block_text = (
            self.code_editor.document().findBlockByNumber(line_num).text().strip()
        )
        if block_text and not block_text.startswith(";"):
            # Check if breakpoint already exists at this line
            if line_num in self.code_editor.breakpoints:
                # Inform that breakpoint already exists
                self.add_to_log(
                    f"Breakpoint already exists at line {line_num + 1}", "SYSTEM"
                )
            else:
                # Add breakpoint
                self.code_editor.toggleBreakpoint(line_num)
                self.add_to_log(f"Breakpoint added at line {line_num + 1}", "SYSTEM")
        else:
            self.add_to_log(
                "Cannot add breakpoint on empty line or comment-only line", "ERROR"
            )

    def remove_breakpoint(self):
        """Remove breakpoint from the current line if one exists"""
        cursor = self.code_editor.textCursor()
        line_num = cursor.blockNumber()

        if line_num in self.code_editor.breakpoints:
            self.code_editor.toggleBreakpoint(line_num)
            self.add_to_log(f"Breakpoint removed from line {line_num + 1}", "SYSTEM")
        else:
            self.add_to_log("No breakpoint on current line", "SYSTEM")

    def remove_all_breakpoints(self):
        """Remove all breakpoints"""
        if self.code_editor.breakpoints:
            self.code_editor.breakpoints.clear()
            self.code_editor.lineNumberArea.update()
            self.add_to_log("All breakpoints removed", "SYSTEM")
        else:
            self.add_to_log("No breakpoints to remove", "SYSTEM")

    def add_to_log(self, message, status="OK"):
        """Add a message to the execution log"""
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")

        # Set color based on status
        status_color = {
            "OK": "#00AA00",  # Green
            "HALT": "#AAAA00",  # Yellow
            "ERROR": "#AA0000",  # Red
            "SYSTEM": "#00AAAA",  # Cyan
        }.get(status, "white")

        # Format the log entry with HTML
        log_entry = f"<span style='color:{status_color}'>[{timestamp}] {message}</span>"

        # Add to the log and update display
        self.execution_log.append(log_entry)
        self.execution_log_widget.setHtml(
            "<br>".join(self.execution_log[-100:])
        )  # Show last 100 entries

        # Scroll to the bottom
        self.execution_log_widget.verticalScrollBar().setValue(
            self.execution_log_widget.verticalScrollBar().maximum()
        )

    def clear_execution_log(self):
        """Clear execution log"""
        self.execution_log.clear()
        self.execution_log_widget.clear()

    def show_editor_context_menu(self, pos):
        """Show context menu for the code editor"""
        cursor = self.code_editor.cursorForPosition(pos)
        line_num = cursor.blockNumber()

        menu = QMenu(self)

        if line_num in self.code_editor.breakpoints:
            action = menu.addAction("Remove Breakpoint")
        else:
            action = menu.addAction("Add Breakpoint")

        action.triggered.connect(lambda: self.toggle_breakpoint(line_num))
        menu.exec(self.code_editor.viewport().mapToGlobal(pos))

    def toggle_breakpoint(self, line_num):
        """Toggle breakpoint at the specified line"""
        # Check if line is not empty
        block_text = (
            self.code_editor.document().findBlockByNumber(line_num).text().strip()
        )
        if block_text and not block_text.startswith(";"):
            self.code_editor.toggleBreakpoint(line_num)
        else:
            self.add_to_log(
                "Cannot add breakpoint on empty line or comment-only line", "ERROR"
            )

    def save_program(self):
        """Save the current program to the current file or prompt for location"""
        if self.current_file:
            return self.save_to_file(self.current_file)
        else:
            return self.save_program_as()

    def save_program_as(self):
        """Save the program to a new file"""
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Assembly Program", "", "Assembly Files (*.asm);;All Files (*.*)"
        )

        if file_path:
            return self.save_to_file(file_path)
        return True  # User canceled

    def save_to_file(self, file_path):
        """Save content to the specified file"""
        try:
            with open(file_path, "w") as f:
                f.write(self.code_editor.toPlainText())

            self.current_file = file_path
            self.document_modified = False  # Reset modified flag after saving
            self.update_window_title()
            self.add_to_log(f"Program saved to {file_path}", "SYSTEM")
            return False  # No errors
        except Exception as e:
            self.add_to_log(f"Error saving program: {str(e)}", "ERROR")
            QMessageBox.critical(
                self, "Save Error", f"Could not save the file:\n{str(e)}"
            )
            return True  # Error occurred

    def load_program(self):
        """Load a program from a file"""
        # Check if we need to save current work
        if self.check_save_current():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Assembly Program", "", "Assembly Files (*.asm);;All Files (*.*)"
        )

        if file_path:
            try:
                with open(file_path, "r") as f:
                    content = f.read()

                self.code_editor.setPlainText(content)
                self.current_file = file_path
                self.document_modified = False  # Reset modified flag after loading
                self.update_window_title()
                self.add_to_log(f"Program loaded from {file_path}", "SYSTEM")

                # Reset simulation when loading a new file
                self.reset_simulation()

            except Exception as e:
                self.add_to_log(f"Error loading program: {str(e)}", "ERROR")
                QMessageBox.critical(
                    self, "Load Error", f"Could not load the file:\n{str(e)}"
                )

    def new_file(self):
        """Create a new file, checking if current work should be saved"""
        # Check if there's content that might need saving
        if self.check_save_current():
            return  # User canceled

        # Reset editor and simulation
        self.code_editor.setPlainText("")
        self.reset_simulation()
        self.current_file = None
        self.document_modified = False  # Reset modified flag for new file
        self.update_window_title()
        self.add_to_log("New file created", "SYSTEM")

    def check_save_current(self):
        """Check if current work should be saved before proceeding"""
        if self.code_editor.toPlainText().strip():
            reply = QMessageBox.question(
                self,
                "Save Changes?",
                "Do you want to save changes to the current program?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )

            if reply == QMessageBox.Save:
                return self.save_program()
            elif reply == QMessageBox.Cancel:
                return True  # User canceled operation

        return False  # No need to save or user discarded changes

    def zoom_in(self):
        """Zoom in"""
        self.menu_bar.zoom_in()
        self.code_editor.zoom_in()
        self.execution_log_widget.zoom_in()
        self.memory_table.zoom_in()
        for button in self.findChildren(PushButton):
            button.zoom_in()
        for label in self.findChildren(Label):
            label.zoom_in()
        for line_edit in self.findChildren(LineEdit):
            line_edit.zoom_in()

    def zoom_out(self):
        """Zoom out"""
        self.menu_bar.zoom_out()
        self.code_editor.zoom_out()
        self.execution_log_widget.zoom_out()
        self.memory_table.zoom_out()
        for button in self.findChildren(PushButton):
            button.zoom_out()
        for label in self.findChildren(Label):
            label.zoom_out()
        for line_edit in self.findChildren(LineEdit):
            line_edit.zoom_out()

    def reset_zoom(self):
        """Reset zoom"""
        self.menu_bar.reset_zoom()
        self.code_editor.reset_zoom()
        self.execution_log_widget.reset_zoom()
        self.memory_table.reset_zoom()
        for button in self.findChildren(PushButton):
            button.reset_zoom()
        for label in self.findChildren(Label):
            label.reset_zoom()
        for line_edit in self.findChildren(LineEdit):
            line_edit.reset_zoom()

    def show_about(self):
        """Show about dialog"""
        QMessageBox.information(
            self,
            "About Neo8085",
            f"Neo8085 - 8085 Microprocessor Simulator\n\n"
            f"Copyright (C) 2025 Shahibur Rahaman\n"
            f"Licensed under the GNU General Public License v3.0\n\n"
            f"A simulator for the 8085 microprocessor.\n"
            f"Version: {version_string}\n\n"
            f"This program is free software: you can redistribute it and/or modify "
            f"it under the terms of the GNU General Public License as published by "
            f"the Free Software Foundation, either version 3 of the License, or "
            f"(at your option) any later version.",
        )

    def reset_simulation(self):
        """Reset the processor and simulator state"""
        # Stop any running execution
        self.stop_execution()

        # Create new processor instance
        self.processor = Processor8085()

        # Reset UI elements
        self.update_registers_display()
        self.load_memory_display(0x0000)
        self.memory_search.setText("")

        # Reset execution statistics and timer
        self.execution_count = 0
        self.instr_count_label.setText("Instructions: 0")
        self.reset_elapsed_timer()

        # Update status
        self.set_status("Reset - Ready to Assemble", "normal")

        # Add log entry
        self.add_to_log("Simulator reset", "SYSTEM")

        # Reset code editor highlight
        self.code_editor.highlightCurrentLine()
        # Update line number area width
        self.code_editor.updateLineNumberAreaWidth(0)

    def set_status(self, text, status_type="normal"):
        """Set status text with consistent styling

        Parameters:
        text (str): The status message to display
        status_type (str): One of 'normal', 'success', 'warning', 'error'
        """
        # Set the text
        self.status_label.setText(text)

        # Common styling properties
        base_style = """
            background-color: {bg_color};
            color: #1E1E1E; 
            padding: 4px; 
            border: 1px solid #DDDDDD;
            border-radius: 3px;
        """

        # Choose background color based on status type
        bg_colors = {
            "normal": "white",  # White for normal/ready states
            "success": "#DFF6DD",  # Light green for success/compile/run states
            "warning": "#FFF4CE",  # Light yellow for warning/halt/pause states
            "error": "#FDE7E9",  # Light red for error states
        }

        bg_color = bg_colors.get(status_type, "white")

        # Apply the style
        self.status_label.setStyleSheet(base_style.format(bg_color=bg_color))

    def toggle_follow_pc(self):
        """Toggle whether memory view should follow PC"""
        self.follow_pc = self.follow_pc_button.isChecked()
        if self.follow_pc:
            # If enabling follow PC, update view to current PC
            pc = self.processor.registers["PC"]
            self.load_memory_display(pc)
        else:
            # If disabling, keep current view
            self.load_memory_display(self.user_memory_addr)

    def create_converter(self):
        """Create a number format converter widget"""
        converter_widget = QWidget()
        converter_layout = QVBoxLayout(converter_widget)
        converter_layout.setContentsMargins(0, 0, 0, 0)  # Remove all margins
        converter_layout.setSpacing(0)  # Remove spacing between elements

        # Set white background for the entire widget
        converter_widget.setStyleSheet("background-color: white;")

        # Title
        converter_header = Header("NUMBER CONVERTER")

        # Create form layout for input fields with minimal margins
        form_layout = QFormLayout()
        form_layout.setContentsMargins(10, 2, 10, 8)  # Minimal margins
        form_layout.setSpacing(4)  # Reduced spacing

        # Hex input
        self.hex_input = LineEdit("Enter hex value")
        self.hex_input.textChanged.connect(lambda: self.convert_number("hex"))

        # Binary input
        self.bin_input = LineEdit("Enter binary value")
        self.bin_input.textChanged.connect(lambda: self.convert_number("bin"))

        # Decimal input
        self.dec_input = LineEdit("Enter decimal value")
        self.dec_input.textChanged.connect(lambda: self.convert_number("dec"))

        # ASCII input (new)
        self.ascii_input = LineEdit("Enter ASCII character")
        self.ascii_input.setMaxLength(1)  # Only allow one character
        self.ascii_input.textChanged.connect(lambda: self.convert_number("ascii"))

        # Add fields to form
        form_layout.addRow(Label("Hex:"), self.hex_input)
        form_layout.addRow(Label("Binary:"), self.bin_input)
        form_layout.addRow(Label("Decimal:"), self.dec_input)
        form_layout.addRow(Label("ASCII:"), self.ascii_input)

        # Add fields to layout
        converter_layout.addWidget(converter_header)
        converter_layout.addLayout(form_layout)

        return converter_widget

    def convert_number(self, source):
        """Convert number between hex, binary, decimal and ASCII formats"""
        # Avoid recursive calls
        self.hex_input.blockSignals(True)
        self.bin_input.blockSignals(True)
        self.dec_input.blockSignals(True)
        self.ascii_input.blockSignals(True)

        try:
            if source == "hex":
                # Convert from hex
                hex_value = self.hex_input.text().strip()
                if hex_value:
                    value = int(hex_value, 16)
                    self.bin_input.setText(bin(value)[2:])  # Remove '0b' prefix
                    self.dec_input.setText(str(value))
                    # ASCII conversion (0-127 only)
                    if 0 <= value <= 127:
                        self.ascii_input.setText(chr(value))
                    else:
                        self.ascii_input.setText("X")
                else:
                    self.bin_input.setText("")
                    self.dec_input.setText("")
                    self.ascii_input.setText("")

            elif source == "bin":
                # Convert from binary
                bin_value = self.bin_input.text().strip()
                if bin_value:
                    value = int(bin_value, 2)
                    self.hex_input.setText(hex(value)[2:].upper())  # Remove '0x' prefix
                    self.dec_input.setText(str(value))
                    # ASCII conversion (0-127 only)
                    if 0 <= value <= 127:
                        self.ascii_input.setText(chr(value))
                    else:
                        self.ascii_input.setText("X")
                else:
                    self.hex_input.setText("")
                    self.dec_input.setText("")
                    self.ascii_input.setText("")

            elif source == "dec":
                # Convert from decimal
                dec_value = self.dec_input.text().strip()
                if dec_value:
                    value = int(dec_value)
                    self.hex_input.setText(hex(value)[2:].upper())  # Remove '0x' prefix
                    self.bin_input.setText(bin(value)[2:])  # Remove '0b' prefix
                    # ASCII conversion (0-127 only)
                    if 0 <= value <= 127:
                        self.ascii_input.setText(chr(value))
                    else:
                        self.ascii_input.setText("X")
                else:
                    self.hex_input.setText("")
                    self.bin_input.setText("")
                    self.ascii_input.setText("")

            elif source == "ascii":
                # Convert from ASCII
                ascii_value = self.ascii_input.text()
                if ascii_value and ascii_value != "X":
                    if len(ascii_value) > 0:
                        value = ord(ascii_value[0])
                        self.hex_input.setText(hex(value)[2:].upper())
                                               # Remove '0x' prefix
                        self.bin_input.setText(bin(value)[2:])  # Remove '0b' prefix
                        self.dec_input.setText(str(value))
                else:
                    if ascii_value != "X":  # Only clear if not showing "X"
                        self.hex_input.setText("")
                        self.bin_input.setText("")
                        self.dec_input.setText("")

        except ValueError:
            # Invalid input, do nothing
            pass

        # Re-enable signals
        self.hex_input.blockSignals(False)
        self.bin_input.blockSignals(False)
        self.dec_input.blockSignals(False)
        self.ascii_input.blockSignals(False)

    def create_memory_editor(self):
        """Create a memory editor widget"""
        memory_editor_widget = QWidget()
        editor_layout = QVBoxLayout(memory_editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)  # Remove all margins
        editor_layout.setSpacing(0)  # Remove spacing between elements

        # Set white background for the entire widget
        memory_editor_widget.setStyleSheet("background-color: white;")

        # Title
        editor_header = Header("MEMORY EDITOR")

        # Create form layout for input fields
        form_layout = QFormLayout()
        form_layout.setContentsMargins(10, 2, 10, 8)  # Minimal margins
        form_layout.setSpacing(4)  # Reduced spacing

        # Address input
        self.memory_addr_input = LineEdit("Memory address (0-65535)[H]")

        # Value input
        self.memory_value_input = LineEdit("Value (0-255)[H]")

        # Add fields to form
        form_layout.addRow(Label("Address:"), self.memory_addr_input)
        form_layout.addRow(Label("Value:"), self.memory_value_input)

        # Add write button
        self.write_memory_button = PushButton("Write to Memory")
        self.write_memory_button.setStyleSheet(
            """
            QPushButton {
                background-color: #0078D7;
                color: white;
                border: none;
                padding: 4px;
                margin-top: 4px;
            }
            QPushButton:hover {
                background-color: #0063B1;
            }
        """
        )
        self.write_memory_button.clicked.connect(self.write_memory_value)

        # Add to layout
        editor_layout.addWidget(editor_header)
        editor_layout.addLayout(form_layout)
        editor_layout.addWidget(self.write_memory_button)

        return memory_editor_widget

    def write_memory_value(self):
        """Write a value to a specific memory address"""
        try:
            # Parse address and value from inputs
            addr_text = self.memory_addr_input.text().strip()
            value_text = self.memory_value_input.text().strip()

            if not addr_text or not value_text:
                self.add_to_log("Please enter both address and value", "ERROR")
                return

            address = self.parse_address(addr_text)
            value = self.parse_address(value_text)

            if not (0 <= address < 65536):  # 64K memory space
                self.add_to_log(
                    f"Address must be in range 0-65535 (0000H-FFFFH)", "ERROR"
                )
                return

            if not (0 <= value <= 255):  # Byte value
                self.add_to_log(f"Value must be in range 0-255 (00H-FFH)", "ERROR")
                return

            # Check if address is in program memory range
            if hasattr(
                    self.processor, "is_program_memory"
            ) and self.processor.is_program_memory(address):
                self.add_to_log(
                    f"Cannot modify program memory at {address:04X}H (0-{self.processor.program_end_address - 1:04X}H)",
                    "ERROR",
                )
                self.memory_addr_input.selectAll()  # Select the address text for easy correction
                return

            # Write value to memory (only if not in program memory)
            self.processor.memory[address] = value

            # Update memory view if address is visible
            base_addr = 0
            if hasattr(self, "memory_table") and self.memory_table.rowCount() > 0:
                base_addr = int(
                    self.memory_table.item(0, 1).text()[:-1], 16
                )  # Get hex addr, remove 'H'

            if base_addr <= address < base_addr + 256:  # If address is in current view
                row = (address - base_addr) // 16
                col = (
                              address - base_addr
                      ) % 16 + 2  # +2 because we now have two address columns

                if (
                        row < self.memory_table.rowCount()
                        and col < self.memory_table.columnCount()
                ):
                    self.memory_table.item(row, col).setText(f"{value:02X}")

            # Log with appropriate format
            if addr_text.upper().endswith("H"):
                addr_display = f"{address:04X}H"
            else:
                addr_display = str(address)

            if value_text.upper().endswith("H"):
                value_display = f"{value:02X}H"
            else:
                value_display = str(value)

            self.add_to_log(
                f"Memory updated: [{addr_display}] = {value_display}", "SYSTEM"
            )

        except ValueError as e:
            self.add_to_log(f"Error: {str(e)}", "ERROR")
        except Exception as e:
            self.add_to_log(f"Error writing to memory: {str(e)}", "ERROR")

    def document_was_modified(self):
        """Mark the document as modified and update the window title"""
        if not self.document_modified:
            self.document_modified = True
            self.update_window_title()

    def update_window_title(self):
        """Update window title to show the modification state"""
        title = f"Neo8085 v{display_version} - "
        if self.current_file:
            filename = os.path.basename(self.current_file)
            if self.document_modified:
                title += f"{filename}* [Changes not saved]"  # Add asterisk to indicate unsaved changes
            else:
                title += filename
        else:
            title += "Untitled"
            if self.document_modified:
                title += (
                    "* [Changes not saved]"  # Add asterisk to indicate unsaved changes
                )

        self.setWindowTitle(title)


class Flags(QWidget):
    def __init__(self, simulator: Simulator):
        super().__init__()
        self.simulator = simulator
        vbox_layout = QVBoxLayout()
        vbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox_layout.setContentsMargins(0, 0, 0, 0)
        vbox_layout.setSpacing(0)
        self.setLayout(vbox_layout)
        self.header = Label(f"Flags")
        self.header.setFont(QFont("Consolas", 12))
        self.header.setStyleSheet(
            "background-color: white; color: #1E1E1E; border: 1px solid #DDDDDD;"
        )
        self.header.setAlignment(Qt.AlignCenter)
        vbox_layout.addWidget(self.header)
        hbox_layout = QHBoxLayout()
        hbox_layout.setContentsMargins(0, 0, 0, 0)
        hbox_layout.setSpacing(0)
        self.flags: dict[str, Label] = {"S": None, "Z": None, "X5": None, "AC": None, " ": None, "X3": None, "P": None, "X1": None, "C": None}
        for flag in self.flags:
            self.flags[flag] = Label(flag)
            if flag != " ":
                self.flags[flag].setStyleSheet(f"background-color: black; color: {"lightgreen" if flag == "X1" else "grey" }; border: 1px solid #DDDDDD;")
            hbox_layout.addWidget(self.flags[flag])
        vbox_layout.addLayout(hbox_layout)

    def update_display(self):
        """Update flags display from processor state"""
        if self.simulator is None:
            return
        flags_byte = self.simulator.processor.get_flags_byte()
        self.header.setText(f"Flags (bin): {(flags_byte >> 4) & 0xF:04b} {flags_byte & 0xF:04b}")
        for flag, value in self.simulator.processor.flags.items():
            if flag in self.flags:
                self.flags[flag].setStyleSheet(f"background-color: black; color: {"lightgreen" if value == 1 else "grey" }; border: 1px solid #DDDDDD;")
                self.flags[flag].update()

    def zoom_in(self):
        """Zoom in"""
        self.header.zoom_in()
        for flag in self.flags:
            self.flags[flag].zoom_in()

    def zoom_out(self):
        """Zoom out"""
        self.header.zoom_out()
        for flag in self.flags:
            self.flags[flag].zoom_out()

    def reset_zoom(self):
        """Reset zoom"""
        self.header.reset_zoom()
        for flag in self.flags:
            self.flags[flag].reset_zoom()


class Stack(QGridLayout):
    """Layout for stack"""
    def __init__(self, simulator: Simulator):
        super().__init__()
        self.simulator = simulator
        self.header = Header("STACK")
        self.addWidget(self.header, 0, 0, 1, 2)
        self.mem_locations: list[Label] = []
        for i in range(16):
            label = Label(f"Stack {i}")
            label.setStyleSheet(
                "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mem_locations.append(label)
            self.addWidget(self.mem_locations[i], (i / 2) + 1, i % 2)

    def update_display(self):
        """Update stack display from processor state"""
        if self.simulator is None:
            return
        sp = self.simulator.processor.registers["SP"]
        for i in range(8):
            addr = sp + i * 2
            addr_label = f"[{addr:04X}H]"
            if addr == 0xFFFF:
                value = "..00H"
            elif addr > 0xFFFF:
                addr_label = "[....H]"
                value = "....H"
            else:
                lsb = self.simulator.processor.memory[addr]
                msb = self.simulator.processor.memory[addr + 1]
                value = f"{msb:02X}{lsb:02X}H"
            self.mem_locations[i * 2].setText(addr_label)
            self.mem_locations[i * 2 + 1].setText(value)

    def zoom_in(self):
        """Zoom in"""
        for mem_location in self.mem_locations:
            mem_location.zoom_in()

    def zoom_out(self):
        """Zoom out"""
        for mem_location in self.mem_locations:
            mem_location.zoom_out()

    def reset_zoom(self):
        """Reset zoom"""
        for mem_location in self.mem_locations:
            mem_location.reset_zoom()


class MemoryTableWidget(ZoomMixin, QTableWidget):
    """Custom QTableWidget that clears selection when losing focus"""

    def __init__(self, rows, columns, simulator: Simulator, parent=None):
        super().__init__(rows, columns, parent, font_point_size=10)
        self.simulator = simulator
        self.setFont(QFont("Consolas", 10))
        self.setStyleSheet(
            """
            QTableWidget {
            background-color: white;
            border: 1px solid #DDDDDD;
            border-radius: 4px;
            color: #1E1E1E;
            }
            QHeaderView::section {
                background-color: #F0F0F0;
                color: #1E1E1E;
                padding: 5px;
                border: 1px solid #DDDDDD;
            }
            QTableWidget::item {
                border: 1px solid #F0F0F0;
                padding: 2px;
            }
            QTableWidget::item:selected {
                background-color: #0B91FF;
                color: white;
            }
        """
        )

        self.horizontalHeader().setDefaultSectionSize(45)
        # Set decimal address column to resize to contents
        self.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        # Set hex address column to be wider
        self.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        # Alternatively, set a fixed width that's wider:
        self.setColumnWidth(1, 80)  # Make hex address column 80px wide
        self.verticalHeader().setDefaultSectionSize(28)

        # Set up memory table headers
        self.setHorizontalHeaderItem(0, TableWidgetItem("Dec"))
        self.setHorizontalHeaderItem(1, TableWidgetItem("Hex"))
        for i in range(16):
            self.setHorizontalHeaderItem(
                i + 2, TableWidgetItem(f"+{i:X}")
            )

        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cellClicked.connect(self.display_value)

    def display_value(self, row, column):
        if column >= 2:
            lsb_addr = int(self.item(row, 0).text()) + column - 2
            lsb = f"{self.simulator.processor.memory[lsb_addr]:02X}H"
            msb = None if lsb_addr >= 0xFFFF else f"{self.simulator.processor.memory[lsb_addr + 1]:02X}"
            self.simulator.add_to_log(f"Byte value at {lsb_addr:04X}H is {lsb}")
            if msb is not None:
                self.simulator.add_to_log(f"Word value at {lsb_addr:04X}H is {msb}{lsb}")
        
    def focusOutEvent(self, event):
        self.clearSelection()
        super().focusOutEvent(event)

    def zoom_in(self):
        """Zoom in"""
        super().zoom_in()
        for i in range(self.columnCount()):
            self.horizontalHeaderItem(i).zoom_in()

    def zoom_out(self):
        """Zoom out"""
        super().zoom_out()
        for i in range(self.columnCount()):
            self.horizontalHeaderItem(i).zoom_out()

    def reset_zoom(self):
        """Reset zoom"""
        super().reset_zoom()
        for i in range(self.columnCount()):
            self.horizontalHeaderItem(i).reset_zoom()


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("8085-logo.ico"))

    # Show splash screen
    splash_pix = QPixmap("8085-splash-screen.png")
    if not splash_pix.isNull():
        splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
        splash.show()
        QTimer.singleShot(2000, splash.close)

    # Create and show main window
    window = Simulator()

    # Apply the pointing hand cursor to all buttons
    for button in window.findChildren(QPushButton):
        button.setCursor(Qt.CursorShape.PointingHandCursor)

    QTimer.singleShot(2000, window.show)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
