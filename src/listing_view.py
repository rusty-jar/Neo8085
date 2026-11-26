# Neo8085 - 8085 Microprocessor Simulator
# Copyright (C) 2026 Shahibur Rahaman
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

"""Opcode listing window and printing of plain-text documents."""

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import (
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPageLayout,
    QTextBlockFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from listing import SOURCE_COLUMN

BUTTON_STYLE = (
    "QPushButton { background-color: #5C2D91; color: white; border: none;"
    " padding: 5px 12px; font: 9pt 'Segoe UI'; }"
    " QPushButton:hover { background-color: #7A4BAF; }"
    " QPushButton:disabled { background-color: #BBBBBB; }"
)


def _monospace(point_size):
    font = QFont("Consolas", point_size)
    if not QFontDatabase.hasFamily("Consolas"):
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(point_size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def text_document(text, title, hanging_columns=0, device=None):
    """
    A printable document of monospaced 8 pt text. Lines too long for the page
    wrap with a hanging indent of `hanging_columns` characters, so wrapped
    listing lines stay in the SOURCE STATEMENT column.
    """
    document = QTextDocument()
    font = _monospace(8)
    document.setDefaultFont(font)
    document.setPlainText(text)
    document.setMetaInformation(QTextDocument.MetaInformation.DocumentTitle, title)
    if hanging_columns:
        # Measured on the printer: the document is laid out at its resolution
        metrics = QFontMetricsF(font, device) if device is not None else QFontMetricsF(font)
        indent = metrics.horizontalAdvance("0" * hanging_columns)
        block_format = QTextBlockFormat()
        block_format.setLeftMargin(indent)
        block_format.setTextIndent(-indent)
        cursor = QTextCursor(document)
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeBlockFormat(block_format)
    return document


def _printer(title):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(title)
    printer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    return printer


def print_text(parent, text, title, hanging_columns=0):
    """Shows the print dialog and prints the text. Returns True if it was printed."""
    printer = _printer(title)
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(f"Print {title}")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    text_document(text, title, hanging_columns, printer).print_(printer)
    return True


def print_preview(parent, text, title, hanging_columns=0):
    """Shows a print preview (with its own Print button)."""
    printer = _printer(title)
    document = text_document(text, title, hanging_columns, printer)
    preview = QPrintPreviewDialog(printer, parent)
    preview.setWindowTitle(f"Print Preview - {title}")
    preview.paintRequested.connect(document.print_)
    preview.resize(900, 1000)
    preview.exec()


class ListingWindow(QWidget):
    """
    Shows the opcode listing of the program. The simulator supplies the
    actions (refresh, save, export, print) so they use its file handling.
    """

    def __init__(self, simulator, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.simulator = simulator
        self.title = ""
        self.setWindowTitle("Opcode Listing")
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        self.caption = QLabel("")
        self.caption.setFont(QFont("Segoe UI", 10))
        layout.addWidget(self.caption)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(_monospace(10))
        self.text.setStyleSheet("QPlainTextEdit { background: white; border: 1px solid #DDDDDD; }")
        layout.addWidget(self.text, 1)

        buttons = QHBoxLayout()
        actions = (
            ("Refresh", "Assemble the editor contents again and update the listing", simulator.show_listing),
            ("Copy", "Copy the whole listing to the clipboard", self.copy),
            ("Save Listing...", "Save the listing as a text (.lst) file", simulator.save_listing),
            ("Export Intel HEX...", "Save the object code as an Intel HEX file", simulator.export_intel_hex),
            ("Print Preview...", "Preview the printed listing", self.preview),
            ("Print...", "Print the listing (Ctrl+P)", self.print),
        )
        self.buttons = {}
        for label, tip, handler in actions:
            button = QPushButton(label)
            button.setToolTip(tip)
            button.setStyleSheet(BUTTON_STYLE)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, h=handler: h())
            buttons.addWidget(button)
            self.buttons[label] = button
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_listing(self, text, title, caption):
        self.title = title
        self.setWindowTitle(f"Opcode Listing - {title}")
        self.caption.setText(caption)
        scroll = self.text.verticalScrollBar().value()
        self.text.setPlainText(text)
        self.text.verticalScrollBar().setValue(scroll)

    def listing_text(self):
        return self.text.toPlainText()

    def copy(self):
        QApplication.clipboard().setText(self.listing_text())
        self.simulator.add_to_log("Listing copied to the clipboard", "SYSTEM")

    def preview(self):
        print_preview(self, self.listing_text(), f"Listing of {self.title}", SOURCE_COLUMN)

    def print(self):
        if print_text(self, self.listing_text(), f"Listing of {self.title}", SOURCE_COLUMN):
            self.simulator.add_to_log(f"Listing of {self.title} sent to the printer", "SYSTEM")
