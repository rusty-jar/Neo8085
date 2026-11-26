"""
End-to-end audit of the GUI: every menu action, every example in every run
mode, every button and toggle in every side tab, zoom, layout, listing/HEX/print.
Records every exception, including those raised inside Qt slots (which Qt only
prints), and fails if there is any.

Run it from the repository root (it needs PySide6):

    python tests/gui_audit.py

It runs headless (Qt's offscreen platform) and uses a temporary settings file,
so it never touches the user's saved layout.
"""
import os, sys, time, tempfile, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["NEO8085_SETTINGS_FILE"] = os.path.join(TMP, "settings.ini")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC); os.chdir(ROOT)

errors = []
def hook(kind, value, tb):
    errors.append("".join(traceback.format_exception(kind, value, tb)))
sys.excepthook = hook

from PySide6.QtCore import QEventLoop

from PySide6.QtWidgets import (QApplication, QMessageBox, QFileDialog, QAbstractButton, QComboBox, QDialog)
from PySide6.QtPrintSupport import QPrintDialog, QPrintPreviewDialog
app = QApplication(sys.argv)

messages = []
QMessageBox.critical = lambda *a, **k: messages.append(("critical", a[1:3]))
QMessageBox.warning = lambda *a, **k: messages.append(("warning", a[1:3]))
QMessageBox.information = lambda *a, **k: messages.append(("information", a[1:3]))
QMessageBox.about = lambda *a, **k: messages.append(("about", a[1:2]))
QMessageBox.question = lambda *a, **k: QMessageBox.Discard
QFileDialog.getSaveFileName = lambda *a, **k: (os.path.join(TMP, "out" + ("." + a[3].split("*.")[1].split(")")[0].split()[0] if len(a) > 3 and "*." in a[3] else ".txt")), "")
saved_hex = []
QFileDialog.getOpenFileName = lambda *a, **k: (saved_hex[-1] if saved_hex else "", "")
QPrintDialog.exec = lambda self: QDialog.DialogCode.Rejected
QPrintPreviewDialog.exec = lambda self: 0

import main
from examples import EXAMPLES

def pump(seconds=0.05):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 2)

sim = main.Simulator(); sim.resize(1500, 1000); sim.show(); pump(0.4)
checked = {"actions": 0, "examples": 0, "buttons": 0, "combos": 0}

def all_actions(menu_bar):
    for top in menu_bar.actions():
        menu = top.menu()
        if menu is None:
            continue
        for action in menu.actions():
            if action.isSeparator() or not action.isEnabled():
                continue
            yield top.text(), action

# 1. Every menu action (except Exit, done at the end)
sim.load_example(EXAMPLES[0]); pump()
for menu_name, action in list(all_actions(sim.menu_bar)):
    text = action.text().strip()
    if text in ("Exit",):
        continue
    action.trigger(); pump(0.15)
    if sim.running:
        pump(0.2); sim.stop_execution()
    checked["actions"] += 1
    if text.startswith("Export Intel HEX"):
        hex_files = [f for f in os.listdir(TMP) if f.endswith(".hex")]
        if hex_files:
            saved_hex.append(os.path.join(TMP, hex_files[0]))
# zoom in/out repeatedly
for _ in range(3): sim.zoom_in(); pump()
for _ in range(5): sim.zoom_out(); pump()
sim.reset_zoom(); pump()
# the pane toggles left everything consistent? restore the layout
sim.reset_layout(); pump()

# 2. Every example in every run mode, with each side tab shown
for index, example in enumerate(EXAMPLES):
    sim.load_example(example); pump()
    sim.side_tabs.setCurrentIndex(index % sim.side_tabs.count())
    for _ in range(15):
        sim.execute_single_step()
    pump()
    for start in (sim.start_continuous_execution, sim.start_fast_execution, sim.start_realtime_execution):
        start(); pump(0.25)
        if sim.running:
            sim.stop_execution()
    sim.soft_reset(); pump()
    checked["examples"] += 1

# 3. Every button, toggle and combo box in every side tab, while a program runs
sim.load_example(next(e for e in EXAMPLES if "Real-Time Clock" in e.title)); pump()
sim.start_realtime_execution(); pump(0.2)
for tab in range(sim.side_tabs.count()):
    sim.side_tabs.setCurrentIndex(tab); pump(0.1)
    page = sim.side_tabs.widget(tab)
    for button in page.findChildren(QAbstractButton):
        if not button.isEnabled() or not button.isVisibleTo(page):
            continue
        button.click(); pump(0.02)
        if button.isCheckable():
            button.click(); pump(0.02)  # back to how it was
        checked["buttons"] += 1
    for box in page.findChildren(QComboBox):
        if not box.isEnabled():
            continue
        original = box.currentIndex()
        for i in range(box.count()):
            box.setCurrentIndex(i); pump(0.01)
        box.setCurrentIndex(original); pump(0.01)
        checked["combos"] += 1
sim.stop_execution(); pump()

# 4. Clock presets, then real time at each of a few clocks
for i in range(sim.clock_selector.count()):
    sim.clock_selector.setCurrentIndex(i)
    sim.apply_clock_selection()
sim.clock_selector.set_text("3.072 MHz (trainer kit)"); sim.apply_clock_selection()

# 5. Resets, then close the window (saves the layout)
sim.reset_simulation(); pump()
sim.close(); pump(0.2)

print("checked:", checked, "| message boxes:", len(messages))
for kind, args in messages:
    if kind in ("critical", "warning"):
        print("  ", kind, args)
if errors:
    print(f"{len(errors)} EXCEPTIONS:")
    for e in errors[:5]:
        print(e)
    sys.exit(1)
print("FULL GUI AUDIT PASSED: no exceptions anywhere")
