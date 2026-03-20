#!/usr/bin/env python3

import cicsim as cs
import tkinter
from tkinter import *
from tkinter import ttk
from tkinter import simpledialog, messagebox
import os
import re
import json
import sys
import fnmatch
import numpy as np

from .wavebrowser import *
from .wavegraph import *
from .theme import _get_theme, _set_active_theme


#- I try to follow a Model, View, Controller type of design pattern
#
# Controller: WaveBrowser
# View: WaveGraph
# Model: WaveFiles
#
# In principle, I want as little as possible to be known across the MVC boundaries
# The Model should not need to know how the data is presented, and the View should
# not need to know how the model reloads data.

_RECENT_FILES_PATH = os.path.expanduser("~/.cicsim_recent.json")
_MAX_RECENT = 10


def _load_recent_files():
    try:
        with open(_RECENT_FILES_PATH, 'r') as fh:
            data = json.load(fh)
            if isinstance(data, list):
                return data[:_MAX_RECENT]
    except Exception:
        pass
    return []


def _save_recent_files(files):
    try:
        with open(_RECENT_FILES_PATH, 'w') as fh:
            json.dump(files[:_MAX_RECENT], fh, indent=2)
    except Exception:
        pass


def _add_recent_file(filepath):
    recent = _load_recent_files()
    abspath = os.path.abspath(filepath)
    if abspath in recent:
        recent.remove(abspath)
    recent.insert(0, abspath)
    _save_recent_files(recent[:_MAX_RECENT])


class CmdWave(cs.Command):
    def __init__(self, xaxis):
        super().__init__()

        self.root = tkinter.Tk()
        self.root.wm_title("cIcWave: (no file)")
        self.root.option_add('*tearOff', FALSE)
        self.root.geometry("1200x700")

        self._current_file = None
        self._xaxis = xaxis

        # --- Menu bar ---
        menubar = Menu(self.root)
        self.root['menu'] = menubar

        menu_file = Menu(menubar)
        menu_edit = Menu(menubar)
        menu_view = Menu(menubar)
        menu_analysis = Menu(menubar)
        menu_signal = Menu(menubar)
        menubar.add_cascade(menu=menu_file, label="File")
        menubar.add_cascade(menu=menu_edit, label="Edit")
        menubar.add_cascade(menu=menu_view, label="View")
        menubar.add_cascade(menu=menu_analysis, label="Analysis")
        menubar.add_cascade(menu=menu_signal, label="Signal")

        self._line_width = 2
        self._font_size = 9

        menu_file.add_command(label="Open Raw          Ctrl+O",
                              command=self.openFileDialog)
        menu_file.add_command(label="Export PDF        Ctrl+P",
                              command=self._exportPdf)
        menu_file.add_separator()
        menu_file.add_command(label="Save Session      Ctrl+S",
                              command=self.saveSession)
        menu_file.add_command(label="Load Session      Ctrl+L",
                              command=self.loadSession)
        menu_file.add_separator()

        # Recent files submenu
        self._menu_recent = Menu(menu_file)
        menu_file.add_cascade(menu=self._menu_recent, label="Recent Files")
        self._refreshRecentMenu()

        menu_file.add_separator()
        menu_file.add_command(label="Quit              Ctrl+Q",
                              command=self.root.destroy)

        menu_edit.add_command(label="New Plot          Ctrl+N",
                              command=self.newPlot)
        menu_edit.add_command(label="Add Axis          Ctrl+A",
                              command=self._addAxis)
        menu_edit.add_separator()
        menu_edit.add_command(label="Reload All        R",
                              command=self.reloadPlots)
        menu_edit.add_command(label="Auto Scale        F",
                              command=self._autoSize)
        menu_edit.add_command(label="Zoom In           Shift+Z",
                              command=self._zoomIn)
        menu_edit.add_command(label="Zoom Out          Ctrl+Z",
                              command=self._zoomOut)
        menu_edit.add_command(label="Zoom In X         x",
                              command=self._zoomInX)
        menu_edit.add_command(label="Zoom Out X        Shift+X",
                              command=self._zoomOutX)
        menu_edit.add_command(label="Zoom In Y         y",
                              command=self._zoomInY)
        menu_edit.add_command(label="Zoom Out Y        Shift+Y",
                              command=self._zoomOutY)
        menu_edit.add_command(label="Zoom to Cursors   c",
                              command=self._zoomToCursors)
        menu_edit.add_command(label="Zoom Undo         u",
                              command=self._zoomUndo)
        menu_edit.add_separator()
        menu_edit.add_command(label="Pan Left          \u2190",
                              command=self._panLeft)
        menu_edit.add_command(label="Pan Right         \u2192",
                              command=self._panRight)
        menu_edit.add_command(label="Pan Up            \u2191",
                              command=self._panUp)
        menu_edit.add_command(label="Pan Down          \u2193",
                              command=self._panDown)
        menu_edit.add_separator()
        menu_edit.add_command(label="Remove Selected   Delete",
                              command=self._removeLine)
        menu_edit.add_command(label="Remove All",
                              command=self._removeAll)

        # --- View menu ---
        menu_view.add_command(label="Set Cursor A      A",
                              command=self._setCursorA)
        menu_view.add_command(label="Set Cursor B      B",
                              command=self._setCursorB)
        menu_view.add_command(label="Clear Cursors     Escape",
                              command=self._clearCursors)
        menu_view.add_separator()
        menu_view.add_command(label="Toggle Legend      L",
                              command=self._toggleLegend)
        menu_view.add_command(label="Toggle Crosshair   H",
                              command=self._toggleCrosshair)
        menu_view.add_command(label="Dark/Light Theme   T",
                              command=self._toggleTheme)
        menu_view.add_separator()
        menu_view.add_command(label="Overlay Compare... O",
                              command=self._overlayWave)
        menu_view.add_command(label="Waveform Compare...",
                              command=self._waveformCompare)
        menu_view.add_separator()
        menu_view.add_command(label="Increase Line Width   Ctrl+Up",
                              command=self._incLineWidth)
        menu_view.add_command(label="Decrease Line Width   Ctrl+Down",
                              command=self._decLineWidth)
        menu_view.add_separator()
        menu_view.add_command(label="Increase Font Size    Ctrl+=",
                              command=self._incFontSize)
        menu_view.add_command(label="Decrease Font Size    Ctrl+-",
                              command=self._decFontSize)

        # --- Analysis menu ---
        menu_analysis.add_command(label="FFT / Spectrum      Ctrl+F",
                                  command=self._plotFFT)
        menu_analysis.add_command(label="Eye Diagram          Ctrl+E",
                                  command=self._plotEye)
        menu_analysis.add_command(label="Expression...        Ctrl+M",
                                  command=self._addExpression)
        menu_analysis.add_separator()

        menu_measure = Menu(menu_analysis)
        menu_analysis.add_cascade(menu=menu_measure, label="Measurements")
        for mtype in ["Rise Time", "Fall Time", "Period",
                       "Pk-to-Pk", "RMS", "Average", "Min", "Max"]:
            menu_measure.add_command(
                label=mtype,
                command=lambda t=mtype: self._measure(t))

        # --- Signal menu ---
        menu_signal.add_command(label="Select All Signals",
                                command=self._selectAllSignals)
        menu_signal.add_command(label="Select hd[*]",
                                command=self._selectHdSignals)
        menu_signal.add_command(label="Select oh[*]",
                                command=self._selectOhSignals)
        menu_signal.add_command(label="Select Inputs",
                                command=self._selectInputSignals)
        menu_signal.add_separator()
        menu_signal.add_command(label="Save Signal List...",
                                command=self._saveSignalList)
        menu_signal.add_command(label="Load Signal List...",
                                command=self._loadSignalList)

        menu_help = Menu(menubar)
        menubar.add_cascade(menu=menu_help, label="Help")
        menu_help.add_command(label="Keyboard Shortcuts",
                              command=self._showHotkeyHelp)

        # --- Toolbar ---
        toolbar = ttk.Frame(self.root, relief="raised", borderwidth=1)
        toolbar.grid(column=0, row=0, sticky=(E, W))

        tb_buttons = [
            ("\U0001F4C2 Open",    self.openFileDialog),
            ("\U0001F4BE Save",    self.saveSession),
            ("\U0001F50D+ ZmIn",   self._zoomIn),
            ("\U0001F50D- ZmOut",  self._zoomOut),
            ("\u229E Fit",         self._autoSize),
            ("|A CsrA",           self._setCursorA),
            ("|B CsrB",           self._setCursorB),
            ("\u270B Pan",        self._panRight),
            ("\U0001F4CF Meas",   self._measureToolbar),
        ]
        for text, cmd in tb_buttons:
            b = ttk.Button(toolbar, text=text, command=cmd, width=8)
            b.pack(side=LEFT, padx=1, pady=1)

        # Quick signal add entry in toolbar
        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=4, pady=2)
        ttk.Label(toolbar, text="Signal:").pack(side=LEFT, padx=(4, 2))
        self._quick_signal_var = StringVar()
        self._quick_signal_entry = ttk.Entry(toolbar, textvariable=self._quick_signal_var, width=24)
        self._quick_signal_entry.pack(side=LEFT, padx=2, pady=2)
        self._quick_signal_entry.bind('<Return>', self._onQuickSignalAdd)
        self._quick_signal_entry.bind('<Tab>', self._onQuickSignalTab)

        # --- Main layout ---
        content = ttk.PanedWindow(self.root, orient=HORIZONTAL)
        height = 600
        self.graph = WaveGraph(content, height=height)
        self.browser = WaveBrowser(content, self.graph, xaxis, height=height)
        content.grid(column=0, row=1, sticky=(N, S, E, W))
        content.add(self.browser)
        content.add(self.graph)

        # --- Status bar ---
        self._statusbar = ttk.Frame(self.root, relief="sunken", borderwidth=1)
        self._statusbar.grid(column=0, row=2, sticky=(E, W))
        self._status_file = ttk.Label(self._statusbar, text="No file", width=30, anchor=W)
        self._status_file.pack(side=LEFT, padx=4)
        ttk.Separator(self._statusbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=2)
        self._status_signals = ttk.Label(self._statusbar, text="0 signals", width=14, anchor=W)
        self._status_signals.pack(side=LEFT, padx=4)
        ttk.Separator(self._statusbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=2)
        self._status_time = ttk.Label(self._statusbar, text="Time: --", width=30, anchor=W)
        self._status_time.pack(side=LEFT, padx=4)
        ttk.Separator(self._statusbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=2)
        self._status_cursors = ttk.Label(self._statusbar, text="Cursors: --", width=30, anchor=W)
        self._status_cursors.pack(side=LEFT, padx=4)
        ttk.Separator(self._statusbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=2)
        self._status_mem = ttk.Label(self._statusbar, text="", width=14, anchor=E)
        self._status_mem.pack(side=RIGHT, padx=4)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)

        # --- Tab context menu + rename support ---
        self.graph.nb.bind('<Double-1>', self._onTabDoubleClick)
        self.graph.nb.bind('<Button-3>', self._onTabRightClick)
        self.graph.nb.bind('<Button-2>', self._onTabRightClick)

        # --- Keyboard shortcuts ---
        self.root.bind('<Control-o>', lambda e: self.openFileDialog())
        self.root.bind('<Control-n>', lambda e: self.newPlot())
        self.root.bind('<Control-q>', lambda e: self.root.destroy())
        self.root.bind('<Control-a>', lambda e: self._addAxis())
        self.root.bind('<Control-p>', lambda e: self._exportPdf())
        self.root.bind('<Control-s>', lambda e: self.saveSession())
        self.root.bind('<Control-l>', lambda e: self.loadSession())
        self.root.bind('<Control-w>', lambda e: self._closeCurrentTab())
        self.root.bind('<Delete>', lambda e: self._removeLine())
        self.root.bind('<Escape>', lambda e: self._clearCursors())

        self.root.bind('<Control-z>', lambda e: self._zoomOut())
        self.root.bind('<Control-Up>', lambda e: self._incLineWidth())
        self.root.bind('<Control-Down>', lambda e: self._decLineWidth())
        self.root.bind('<Control-equal>', lambda e: self._incFontSize())
        self.root.bind('<Control-minus>', lambda e: self._decFontSize())

        self.root.bind('<Left>', lambda e: self._panLeft())
        self.root.bind('<Right>', lambda e: self._panRight())
        self.root.bind('<Up>', lambda e: self._panUp())
        self.root.bind('<Down>', lambda e: self._panDown())

        # New Ctrl+ shortcuts for Analysis
        self.root.bind('<Control-f>', lambda e: self._plotFFT())
        self.root.bind('<Control-e>', lambda e: self._plotEye())
        self.root.bind('<Control-m>', lambda e: self._addExpression())

        # Tab navigation: Ctrl+Tab, Ctrl+Shift+Tab, Ctrl+1..9
        self.root.bind('<Control-Tab>', lambda e: self._nextTab())
        self.root.bind('<Control-Shift-Tab>', lambda e: self._prevTab())
        self.root.bind('<Control-ISO_Left_Tab>', lambda e: self._prevTab())
        for i in range(1, 10):
            self.root.bind('<Control-Key-%d>' % i,
                           lambda e, idx=i-1: self._gotoTab(idx))

        # Single-key shortcuts -- skip when focus is in an Entry widget
        for key, func in [('r', self.reloadPlots),
                          ('f', self._autoSize),
                          ('a', self._setCursorA),
                          ('b', self._setCursorB),
                          ('l', self._toggleLegend),
                          ('Z', self._zoomIn),
                          ('x', self._zoomInX),
                          ('X', self._zoomOutX),
                          ('y', self._zoomInY),
                          ('Y', self._zoomOutY),
                          ('c', self._zoomToCursors),
                          ('u', self._zoomUndo),
                          ('h', self._toggleCrosshair),
                          ('t', self._toggleTheme),
                          ('o', self._overlayWave)]:
            self.root.bind(key, self._make_key_handler(func))

        # Periodic status bar update
        self._updateStatusBar()

    def _make_key_handler(self, func):
        def handler(event):
            if isinstance(event.widget, (ttk.Entry, Entry)):
                return
            func()
        return handler

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _updateStatusBar(self):
        # File name
        f = self.browser.files.getSelected()
        if f:
            self._status_file.config(text=os.path.basename(f.fname))
        else:
            self._status_file.config(text="No file")

        # Signal count
        p = self.graph.getCurrentPlot()
        sig_count = len(p.wave_data) if p else 0
        self._status_signals.config(text="%d signals" % sig_count)

        # Time range
        time_text = "Time: --"
        if p and p.wave_data:
            x_min = None
            x_max = None
            xunit = ""
            for wave, _ in p.wave_data.values():
                if wave.x is not None:
                    xr = np.real(wave.x)
                    lo, hi = float(xr[0]), float(xr[-1])
                    if x_min is None or lo < x_min:
                        x_min = lo
                    if x_max is None or hi > x_max:
                        x_max = hi
                    if wave.xunit:
                        xunit = wave.xunit
            if x_min is not None:
                from matplotlib.ticker import EngFormatter
                eng = EngFormatter(unit=xunit)
                time_text = "%s .. %s" % (eng(x_min), eng(x_max))
        self._status_time.config(text=time_text)

        # Cursor positions
        cursor_text = "Cursors: --"
        if p:
            parts = []
            xunit = ""
            for wave, _ in p.wave_data.values():
                if wave.xunit:
                    xunit = wave.xunit
                    break
            from matplotlib.ticker import EngFormatter
            eng = EngFormatter(unit=xunit)
            if p.cursor_a_x is not None:
                parts.append("A:%s" % eng(p.cursor_a_x))
            if p.cursor_b_x is not None:
                parts.append("B:%s" % eng(p.cursor_b_x))
            if p.cursor_a_x is not None and p.cursor_b_x is not None:
                parts.append("dX:%s" % eng(p.cursor_b_x - p.cursor_a_x))
            if parts:
                cursor_text = " ".join(parts)
        self._status_cursors.config(text=cursor_text)

        # Memory usage
        try:
            import resource
            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
            self._status_mem.config(text="%.0f MB" % mem_mb)
        except Exception:
            try:
                import psutil
                mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                self._status_mem.config(text="%.0f MB" % mem_mb)
            except Exception:
                self._status_mem.config(text="")

        # Schedule next update
        self.root.after(500, self._updateStatusBar)

    # ------------------------------------------------------------------
    # Window title
    # ------------------------------------------------------------------

    def _updateWindowTitle(self):
        f = self.browser.files.getSelected()
        p = self.graph.getCurrentPlot()

        parts = ["cIcWave:"]
        if f:
            parts.append(os.path.basename(f.fname))
        else:
            parts.append("(no file)")

        sig_count = len(p.wave_data) if p else 0
        parts.append("- %d signals" % sig_count)

        if p and p.wave_data:
            x_min = None
            x_max = None
            xunit = ""
            for wave, _ in p.wave_data.values():
                if wave.x is not None:
                    xr = np.real(wave.x)
                    lo, hi = float(xr[0]), float(xr[-1])
                    if x_min is None or lo < x_min:
                        x_min = lo
                    if x_max is None or hi > x_max:
                        x_max = hi
                    if wave.xunit:
                        xunit = wave.xunit
            if x_min is not None:
                from matplotlib.ticker import EngFormatter
                eng = EngFormatter(unit=xunit)
                parts.append("- %s..%s" % (eng(x_min), eng(x_max)))

        self.root.wm_title(" ".join(parts))

    # ------------------------------------------------------------------
    # Recent files
    # ------------------------------------------------------------------

    def _refreshRecentMenu(self):
        self._menu_recent.delete(0, END)
        recent = _load_recent_files()
        if not recent:
            self._menu_recent.add_command(label="(empty)", state=DISABLED)
            return
        for path in recent:
            label = os.path.basename(path)
            self._menu_recent.add_command(
                label=label,
                command=lambda p=path: self._openRecentFile(p))

    def _openRecentFile(self, filepath):
        if not os.path.exists(filepath):
            messagebox.showwarning("Recent Files",
                                   "File not found:\n%s" % filepath,
                                   parent=self.root)
            return
        self.browser.openFile(filepath)
        self._current_file = filepath
        _add_recent_file(filepath)
        self._refreshRecentMenu()
        self._updateWindowTitle()

    # ------------------------------------------------------------------
    # Toolbar: quick signal add
    # ------------------------------------------------------------------

    def _onQuickSignalAdd(self, event=None):
        pattern = self._quick_signal_var.get().strip()
        if not pattern:
            return
        f = self.browser.files.getSelected()
        if not f:
            return
        names = list(f.getWaveNames())
        matched = []
        for n in names:
            if fnmatch.fnmatch(n.lower(), '*' + pattern.lower() + '*'):
                matched.append(n)
        if not matched:
            try:
                rx = re.compile(pattern, re.IGNORECASE)
                matched = [n for n in names if rx.search(n)]
            except re.error:
                pass
        if matched:
            for name in matched:
                wave = f.getWave(name)
                self.graph.show(wave)
            self._quick_signal_var.set("")
            self._updateWindowTitle()
        else:
            messagebox.showinfo("Quick Signal",
                                "No signals matching '%s'" % pattern,
                                parent=self.root)

    def _onQuickSignalTab(self, event=None):
        pattern = self._quick_signal_var.get().strip()
        if not pattern:
            return 'break'
        f = self.browser.files.getSelected()
        if not f:
            return 'break'
        names = list(f.getWaveNames())
        matched = [n for n in names
                    if fnmatch.fnmatch(n.lower(), '*' + pattern.lower() + '*')]
        if not matched:
            try:
                rx = re.compile(pattern, re.IGNORECASE)
                matched = [n for n in names if rx.search(n)]
            except re.error:
                pass
        if len(matched) == 1:
            self._quick_signal_var.set(matched[0])
            self._quick_signal_entry.icursor(END)
        elif matched:
            # Find longest common prefix
            prefix = os.path.commonprefix(matched)
            if len(prefix) > len(pattern):
                self._quick_signal_var.set(prefix)
                self._quick_signal_entry.icursor(END)
        return 'break'

    def _measureToolbar(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        menu = Menu(self.root, tearoff=0)
        for mtype in ["Rise Time", "Fall Time", "Period",
                       "Pk-to-Pk", "RMS", "Average", "Min", "Max"]:
            menu.add_command(label=mtype,
                             command=lambda t=mtype: self._measure(t))
        try:
            menu.tk_popup(self.root.winfo_pointerx(),
                          self.root.winfo_pointery())
        finally:
            menu.grab_release()

    # ------------------------------------------------------------------
    # Tab navigation
    # ------------------------------------------------------------------

    def _nextTab(self):
        tabs = self.graph.nb.tabs()
        if len(tabs) <= 1:
            return
        cur = self.graph.nb.select()
        idx = list(tabs).index(cur)
        self.graph.nb.select(tabs[(idx + 1) % len(tabs)])

    def _prevTab(self):
        tabs = self.graph.nb.tabs()
        if len(tabs) <= 1:
            return
        cur = self.graph.nb.select()
        idx = list(tabs).index(cur)
        self.graph.nb.select(tabs[(idx - 1) % len(tabs)])

    def _gotoTab(self, idx):
        tabs = self.graph.nb.tabs()
        if idx < len(tabs):
            self.graph.nb.select(tabs[idx])

    def _closeCurrentTab(self):
        tabs = self.graph.nb.tabs()
        if len(tabs) <= 1:
            return
        cur = self.graph.nb.select()
        self.graph.nb.forget(cur)

    # ------------------------------------------------------------------
    # Tab rename and context menu
    # ------------------------------------------------------------------

    def _tabIndexFromEvent(self, event):
        try:
            return self.graph.nb.index("@%d,%d" % (event.x, event.y))
        except Exception:
            return None

    def _onTabDoubleClick(self, event):
        idx = self._tabIndexFromEvent(event)
        if idx is None:
            return
        tabs = self.graph.nb.tabs()
        old_text = self.graph.nb.tab(tabs[idx], 'text')
        new_name = simpledialog.askstring("Rename Tab",
                                          "New name:",
                                          initialvalue=old_text,
                                          parent=self.root)
        if new_name and new_name.strip():
            self.graph.nb.tab(tabs[idx], text=new_name.strip())

    def _onTabRightClick(self, event):
        idx = self._tabIndexFromEvent(event)
        if idx is None:
            return
        tabs = self.graph.nb.tabs()
        tab_id = tabs[idx]

        menu = Menu(self.root, tearoff=0)
        menu.add_command(label="Rename",
                         command=lambda: self._renameTab(idx))
        menu.add_command(label="Close",
                         command=lambda: self._closeTab(idx))
        menu.add_command(label="Duplicate",
                         command=lambda: self._duplicateTab(idx))
        menu.add_separator()
        if idx > 0:
            menu.add_command(label="Move Left",
                             command=lambda: self._moveTab(idx, idx - 1))
        if idx < len(tabs) - 1:
            menu.add_command(label="Move Right",
                             command=lambda: self._moveTab(idx, idx + 1))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _renameTab(self, idx):
        tabs = self.graph.nb.tabs()
        if idx >= len(tabs):
            return
        old_text = self.graph.nb.tab(tabs[idx], 'text')
        new_name = simpledialog.askstring("Rename Tab",
                                          "New name:",
                                          initialvalue=old_text,
                                          parent=self.root)
        if new_name and new_name.strip():
            self.graph.nb.tab(tabs[idx], text=new_name.strip())

    def _closeTab(self, idx):
        tabs = self.graph.nb.tabs()
        if len(tabs) <= 1:
            return
        self.graph.nb.forget(tabs[idx])

    def _duplicateTab(self, idx):
        tabs = self.graph.nb.tabs()
        if idx >= len(tabs):
            return
        src = self.graph.nb.nametowidget(tabs[idx])
        old_name = self.graph.nb.tab(tabs[idx], 'text')
        self.graph.addPlot()
        new_tabs = self.graph.nb.tabs()
        new_tab = self.graph.nb.nametowidget(new_tabs[-1])
        self.graph.nb.tab(new_tabs[-1], text=old_name + " (copy)")
        # Copy signal references
        for tag, (wave, ax_idx) in src.wave_data.items():
            new_tab.show(wave)

    def _moveTab(self, from_idx, to_idx):
        tabs = list(self.graph.nb.tabs())
        if from_idx < 0 or from_idx >= len(tabs):
            return
        if to_idx < 0 or to_idx >= len(tabs):
            return
        tab_id = tabs[from_idx]
        widget = self.graph.nb.nametowidget(tab_id)
        text = self.graph.nb.tab(tab_id, 'text')
        self.graph.nb.forget(tab_id)
        self.graph.nb.insert(to_idx, widget, text=text)
        self.graph.nb.select(to_idx)

    # ------------------------------------------------------------------
    # Session save/restore (YAML format)
    # ------------------------------------------------------------------

    def saveSession(self):
        try:
            import yaml
        except ImportError:
            messagebox.showerror("Save Session",
                                 "PyYAML not installed.\npip install pyyaml",
                                 parent=self.root)
            return

        filename = tkinter.filedialog.asksaveasfilename(
            defaultextension=".cicwave.yaml",
            filetypes=[("cIcWave Session", "*.cicwave.yaml"),
                       ("YAML files", "*.yaml"),
                       ("All files", "*.*")],
            initialdir=os.getcwd(),
            title="Save Session",
            parent=self.root)
        if not filename:
            return

        session = {
            'version': 1,
            'geometry': self.root.geometry(),
            'line_width': self._line_width,
            'font_size': self._font_size,
            'files': [],
            'tabs': [],
        }

        # Save loaded files
        for key, wf in self.browser.files.items():
            if not wf.fname.startswith("::virtual::"):
                session['files'].append({
                    'path': os.path.abspath(wf.fname),
                    'name': wf.name,
                })

        # Save tabs
        for tab_id in self.graph.nb.tabs():
            plot = self.graph.nb.nametowidget(tab_id)
            tab_name = self.graph.nb.tab(tab_id, 'text')
            tab_data = {
                'name': tab_name,
                'cursor_a': plot.cursor_a_x,
                'cursor_b': plot.cursor_b_x,
                'signals': [],
                'axes_limits': [],
            }
            for tag, (wave, ax_idx) in plot.wave_data.items():
                sig = {
                    'key': wave.key,
                    'axis': ax_idx,
                    'tag': tag,
                }
                if wave.line:
                    sig['color'] = wave.line.get_color()
                    sig['linestyle'] = wave.line.get_linestyle()
                    sig['linewidth'] = wave.line.get_linewidth()
                tab_data['signals'].append(sig)
            for ax in plot.axes:
                tab_data['axes_limits'].append({
                    'xlim': list(ax.get_xlim()),
                    'ylim': list(ax.get_ylim()),
                })
            session['tabs'].append(tab_data)

        try:
            with open(filename, 'w') as fh:
                yaml.dump(session, fh, default_flow_style=False, sort_keys=False)
        except Exception as exc:
            messagebox.showerror("Save Session",
                                 "Error saving session:\n%s" % str(exc),
                                 parent=self.root)

    def loadSession(self):
        try:
            import yaml
        except ImportError:
            messagebox.showerror("Load Session",
                                 "PyYAML not installed.\npip install pyyaml",
                                 parent=self.root)
            return

        filename = tkinter.filedialog.askopenfilename(
            defaultextension=".cicwave.yaml",
            filetypes=[("cIcWave Session", "*.cicwave.yaml"),
                       ("YAML files", "*.yaml"),
                       ("All files", "*.*")],
            initialdir=os.getcwd(),
            title="Load Session",
            parent=self.root)
        if not filename:
            return

        try:
            with open(filename, 'r') as fh:
                session = yaml.safe_load(fh)
        except Exception as exc:
            messagebox.showerror("Load Session",
                                 "Error reading session:\n%s" % str(exc),
                                 parent=self.root)
            return

        if not isinstance(session, dict) or session.get('version') != 1:
            messagebox.showerror("Load Session",
                                 "Unrecognized session format.",
                                 parent=self.root)
            return

        # Restore geometry
        if 'geometry' in session:
            self.root.geometry(session['geometry'])

        if 'line_width' in session:
            self._line_width = session['line_width']
        if 'font_size' in session:
            self._font_size = session['font_size']

        # Load files
        missing = []
        for finfo in session.get('files', []):
            path = finfo.get('path', '')
            if os.path.exists(path):
                try:
                    self.browser.openFile(path)
                    self._current_file = path
                    _add_recent_file(path)
                except Exception:
                    missing.append(path)
            else:
                missing.append(path)

        # Remove default tab if we will create tabs from session
        tab_configs = session.get('tabs', [])
        if tab_configs:
            default_tabs = self.graph.nb.tabs()
            for dt in default_tabs:
                self.graph.nb.forget(dt)

        # Restore tabs
        for tab_data in tab_configs:
            self.graph.addPlot()
            tabs = self.graph.nb.tabs()
            tab_id = tabs[-1]
            plot = self.graph.nb.nametowidget(tab_id)
            self.graph.nb.tab(tab_id, text=tab_data.get('name', 'Plot'))

            # Add signals
            f = self.browser.files.getSelected()
            if f:
                for sig in tab_data.get('signals', []):
                    key = sig.get('key', '')
                    ax_idx = sig.get('axis', 0)
                    while plot._num_axes <= ax_idx:
                        plot.addAxis()
                    plot.axis_index = ax_idx
                    try:
                        wave = f.getWave(key)
                        plot.show(wave)
                        if wave.line:
                            if 'color' in sig:
                                wave.line.set_color(sig['color'])
                            if 'linestyle' in sig:
                                wave.line.set_linestyle(sig['linestyle'])
                            if 'linewidth' in sig:
                                wave.line.set_linewidth(sig['linewidth'])
                    except Exception:
                        pass

            # Restore zoom state
            for i, lim in enumerate(tab_data.get('axes_limits', [])):
                if i < len(plot.axes):
                    if 'xlim' in lim:
                        plot.axes[i].set_xlim(lim['xlim'])
                    if 'ylim' in lim:
                        plot.axes[i].set_ylim(lim['ylim'])

            # Restore cursors
            if tab_data.get('cursor_a') is not None:
                plot._set_cursor('a', tab_data['cursor_a'])
            if tab_data.get('cursor_b') is not None:
                plot._set_cursor('b', tab_data['cursor_b'])

            plot.canvas.draw_idle()

        self._applyLineWidth()
        self._applyFontSize()
        self._refreshRecentMenu()
        self._updateWindowTitle()

        if missing:
            messagebox.showwarning("Load Session",
                                   "Files not found:\n" +
                                   '\n'.join(missing[:10]),
                                   parent=self.root)

    # ------------------------------------------------------------------
    # Waveform compare dialog
    # ------------------------------------------------------------------

    def _waveformCompare(self):
        file1 = tkinter.filedialog.askopenfilename(
            title="Select first waveform file",
            initialdir=os.getcwd(),
            parent=self.root)
        if not file1:
            return
        file2 = tkinter.filedialog.askopenfilename(
            title="Select second waveform file",
            initialdir=os.path.dirname(file1),
            parent=self.root)
        if not file2:
            return

        # Load both files
        from .wavefiles import WaveFile
        try:
            wf1 = WaveFile(file1, self._xaxis)
            wf2 = WaveFile(file2, self._xaxis)
        except Exception as exc:
            messagebox.showerror("Waveform Compare",
                                 "Error loading files:\n%s" % str(exc),
                                 parent=self.root)
            return

        names1 = list(wf1.getWaveNames())
        names2 = list(wf2.getWaveNames())

        # Dialog for signal selection
        dlg = Toplevel(self.root)
        dlg.title("Waveform Compare")
        dlg.geometry("700x500")
        dlg.transient(self.root)

        ttk.Label(dlg, text="File A: %s" % os.path.basename(file1)).pack(anchor=W, padx=8, pady=(8, 0))
        ttk.Label(dlg, text="File B: %s" % os.path.basename(file2)).pack(anchor=W, padx=8, pady=(0, 4))

        frame = ttk.Frame(dlg)
        frame.pack(fill=BOTH, expand=True, padx=8, pady=4)

        ttk.Label(frame, text="Signals in A:").grid(row=0, column=0, sticky=W)
        ttk.Label(frame, text="Signals in B:").grid(row=0, column=1, sticky=W)

        lb1 = Listbox(frame, selectmode=EXTENDED, exportselection=False)
        lb1.grid(row=1, column=0, sticky=(N, S, E, W), padx=(0, 4))
        lb2 = Listbox(frame, selectmode=EXTENDED, exportselection=False)
        lb2.grid(row=1, column=1, sticky=(N, S, E, W), padx=(4, 0))

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        for n in names1:
            lb1.insert(END, n)
        for n in names2:
            lb2.insert(END, n)

        chk_var = IntVar(value=1)
        ttk.Checkbutton(dlg, text="Show delta waveform (A - B)",
                        variable=chk_var).pack(anchor=W, padx=8, pady=4)

        def do_compare():
            sel1 = lb1.curselection()
            sel2 = lb2.curselection()
            if not sel1 or not sel2:
                messagebox.showwarning("Compare",
                                       "Select at least one signal from each file.",
                                       parent=dlg)
                return
            # Create new plot tab for comparison
            self.graph.addPlot()
            tabs = self.graph.nb.tabs()
            p = self.graph.nb.nametowidget(tabs[-1])
            self.graph.nb.tab(tabs[-1], text="Compare")

            pairs = min(len(sel1), len(sel2))
            for i in range(pairs):
                n1 = names1[sel1[i]]
                n2 = names2[sel2[i]]
                w1 = wf1.getWave(n1)
                w2 = wf2.getWave(n2)
                p.show(w1)
                p.show(w2)

                # Delta waveform
                if chk_var.get() and w1.x is not None and w2.x is not None:
                    x1 = np.real(w1.x)
                    y1 = np.real(w1.y)
                    x2 = np.real(w2.x)
                    y2 = np.real(w2.y)
                    # Interpolate to common x axis
                    x_common = x1
                    y2_interp = np.interp(x_common, x2, y2)
                    delta = y1 - y2_interp

                    p.addAxis()
                    ax = p.axes[p.axis_index]
                    label = "delta(%s - %s)" % (n1, n2)
                    line, = ax.plot(x_common, delta, label=label,
                                    linestyle='--', linewidth=1.0)
                    ax.set_title("Delta", fontsize=8)
                    ax.grid(True, alpha=0.3)

                    # Store as pseudo-wave
                    class _DeltaWave:
                        pass
                    dw = _DeltaWave()
                    dw.x = x_common
                    dw.y = delta
                    dw.key = label
                    dw.ylabel = label
                    dw.xlabel = w1.xlabel
                    dw.xunit = w1.xunit
                    dw.yunit = w1.yunit
                    dw.tag = "::delta::%s::%s" % (n1, n2)
                    dw.line = line
                    dw.logx = False
                    dw.logy = False
                    dw.reload = lambda: None

                    p.wave_data[dw.tag] = (dw, p.axis_index)
                    p.tree.insert('', 'end', dw.tag,
                                  text="A%d: %s" % (p.axis_index, label),
                                  tags=(dw.tag,))
                    p.tree.tag_configure(dw.tag, foreground=line.get_color())

            p.autoSize()
            p.canvas.draw_idle()
            dlg.destroy()
            self._updateWindowTitle()

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill=X, padx=8, pady=8)
        ttk.Button(btn_frame, text="Compare", command=do_compare).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=RIGHT, padx=4)

    # --- Dialog helpers ---

    def _askString(self, title, prompt):
        return simpledialog.askstring(title, prompt, parent=self.root)

    def _askFloat(self, title, prompt, default=0.0):
        return simpledialog.askfloat(title, prompt,
                                     initialvalue=default,
                                     parent=self.root)

    # --- Delegate to current plot tab ---

    def _addAxis(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.addAxis()

    def _autoSize(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.autoSize()

    def _zoomIn(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomIn()

    def _zoomOut(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomOut()

    def _zoomInX(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomInX()

    def _zoomOutX(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomOutX()

    def _zoomInY(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomInY()

    def _zoomOutY(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomOutY()

    def _zoomToCursors(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomToCursors()

    def _zoomUndo(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.zoomUndo()

    def _panLeft(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.panLeft()

    def _panRight(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.panRight()

    def _panUp(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.panUp()

    def _panDown(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.panDown()

    def _incLineWidth(self):
        self._line_width = min(self._line_width + 1, 10)
        self._applyLineWidth()

    def _decLineWidth(self):
        self._line_width = max(self._line_width - 1, 1)
        self._applyLineWidth()

    def _applyLineWidth(self):
        for t in self.graph.nb.tabs():
            self.graph.nb.nametowidget(t).setLineWidth(self._line_width)

    def _incFontSize(self):
        self._font_size = min(self._font_size + 1, 24)
        self._applyFontSize()

    def _decFontSize(self):
        self._font_size = max(self._font_size - 1, 6)
        self._applyFontSize()

    def _applyFontSize(self):
        for t in self.graph.nb.tabs():
            self.graph.nb.nametowidget(t).setFontSize(self._font_size)

    def _removeLine(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.removeLine()
            self._updateWindowTitle()

    def _removeAll(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.removeAll()
            self._updateWindowTitle()

    def _setCursorA(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.placeCursorA()

    def _setCursorB(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.placeCursorB()

    def _clearCursors(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.clearCursors()

    def _toggleLegend(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.toggleLegend()

    def _exportPdf(self):
        p = self.graph.getCurrentPlot()
        if p:
            p.exportPdf()

    # --- New View delegates ---

    def _toggleCrosshair(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        try:
            p.toggleCrosshair()
        except AttributeError:
            p._crosshair_enabled = not getattr(p, '_crosshair_enabled', False)

    def _toggleTheme(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        try:
            p.toggleTheme()
        except AttributeError:
            current = _get_theme()
            new_name = 'light' if current is not _get_theme() or current.get('pg_background') == 'k' else 'dark'
            _set_active_theme(new_name)

    def _overlayWave(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        offset = self._askFloat("Overlay Compare", "X offset:", default=0.0)
        if offset is None:
            return
        scale = self._askFloat("Overlay Compare", "Y scale factor:", default=1.0)
        if scale is None:
            return
        try:
            p.overlayWave(offset, scale)
        except AttributeError:
            messagebox.showinfo("Overlay Compare",
                                "overlayWave() not yet implemented in WavePlot.\n"
                                "Offset=%.4g, Scale=%.4g recorded." % (offset, scale),
                                parent=self.root)

    # --- Analysis delegates ---

    def _plotFFT(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        try:
            p.plotFFT()
        except AttributeError:
            messagebox.showinfo("FFT / Spectrum",
                                "plotFFT() not yet implemented in WavePlot.",
                                parent=self.root)

    def _plotEye(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        period = self._askFloat("Eye Diagram", "Period (seconds):", default=1e-9)
        if period is None:
            return
        try:
            p.plotEye(period)
        except AttributeError:
            messagebox.showinfo("Eye Diagram",
                                "plotEye() not yet implemented in WavePlot.\n"
                                "Period=%.4g s recorded." % period,
                                parent=self.root)

    def _addExpression(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        expr = self._askString("Expression",
                               "Math expression (use signal names as variables):")
        if not expr:
            return
        try:
            p.addExpression(expr)
        except AttributeError:
            messagebox.showinfo("Expression",
                                "addExpression() not yet implemented in WavePlot.\n"
                                "Expression: %s" % expr,
                                parent=self.root)

    def _measure(self, mtype):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        try:
            p.measure(mtype)
        except AttributeError:
            messagebox.showinfo("Measurement",
                                "measure() not yet implemented in WavePlot.\n"
                                "Type: %s" % mtype,
                                parent=self.root)

    # --- Signal menu delegates ---

    def _getSelectedFile(self):
        f = self.browser.files.getSelected()
        if f is None:
            messagebox.showwarning("Signal", "No file loaded.",
                                   parent=self.root)
        return f

    def _addSignalsByPattern(self, pattern):
        f = self._getSelectedFile()
        if not f:
            return
        names = [n for n in f.getWaveNames() if re.search(pattern, n)]
        if not names:
            messagebox.showinfo("Signal",
                                "No signals matching '%s' found." % pattern,
                                parent=self.root)
            return
        for name in names:
            wave = f.getWave(name)
            self.graph.show(wave)
        self._updateWindowTitle()

    def _selectAllSignals(self):
        f = self._getSelectedFile()
        if not f:
            return
        for name in f.getWaveNames():
            wave = f.getWave(name)
            self.graph.show(wave)
        self._updateWindowTitle()

    def _selectHdSignals(self):
        self._addSignalsByPattern(r'hd\[')

    def _selectOhSignals(self):
        self._addSignalsByPattern(r'oh\[')

    def _selectInputSignals(self):
        self._addSignalsByPattern(r'^[AaBb]\[')

    def _saveSignalList(self):
        p = self.graph.getCurrentPlot()
        if not p:
            return
        tags = list(p.wave_data.keys())
        if not tags:
            messagebox.showinfo("Save Signal List", "No signals in current plot.",
                                parent=self.root)
            return
        filename = tkinter.filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=os.getcwd(),
            title="Save Signal List",
            parent=self.root)
        if not filename:
            return
        names = [p.wave_data[t][0].key for t in tags]
        with open(filename, 'w') as fh:
            fh.write('\n'.join(names) + '\n')

    def _loadSignalList(self):
        f = self._getSelectedFile()
        if not f:
            return
        filename = tkinter.filedialog.askopenfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=os.getcwd(),
            title="Load Signal List",
            parent=self.root)
        if not filename:
            return
        with open(filename, 'r') as fh:
            names = [line.strip() for line in fh if line.strip()]
        available = set(f.getWaveNames())
        missing = []
        for name in names:
            if name in available:
                wave = f.getWave(name)
                self.graph.show(wave)
            else:
                missing.append(name)
        if missing:
            messagebox.showwarning("Load Signal List",
                                   "Signals not found in current file:\n" +
                                   '\n'.join(missing[:20]),
                                   parent=self.root)
        self._updateWindowTitle()

    # --- Help ---

    def _showHotkeyHelp(self):
        text = (
            "Keyboard Shortcuts\n"
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
            "\n"
            "File\n"
            "  Ctrl+O        Open raw file\n"
            "  Ctrl+P        Export PDF\n"
            "  Ctrl+S        Save session\n"
            "  Ctrl+L        Load session\n"
            "  Ctrl+Q        Quit\n"
            "\n"
            "Edit\n"
            "  Ctrl+N        New plot tab\n"
            "  Ctrl+A        Add axis\n"
            "  Ctrl+W        Close current tab\n"
            "  R             Reload all waves\n"
            "  F             Auto scale (fit)\n"
            "  Shift+Z       Zoom in\n"
            "  Ctrl+Z        Zoom out\n"
            "  Delete        Remove selected wave\n"
            "\n"
            "Cursors\n"
            "  A             Set cursor A at mouse\n"
            "  B             Set cursor B at mouse\n"
            "  Escape        Clear cursors\n"
            "  Click         Place cursor A\n"
            "  Shift+Click   Place cursor B\n"
            "  Right-Click   Place cursor B\n"
            "  Drag cursor   Move cursor\n"
            "\n"
            "View\n"
            "  L             Toggle legend\n"
            "  H             Toggle crosshair\n"
            "  T             Dark/Light theme\n"
            "  O             Overlay compare\n"
            "  Ctrl+Up       Increase line width\n"
            "  Ctrl+Down     Decrease line width\n"
            "  Ctrl+=        Increase font size\n"
            "  Ctrl+-        Decrease font size\n"
            "\n"
            "Tabs\n"
            "  Ctrl+Tab      Next tab\n"
            "  Ctrl+Shift+Tab  Previous tab\n"
            "  Ctrl+1..9     Jump to tab N\n"
            "  Ctrl+W        Close current tab\n"
            "  Double-click  Rename tab\n"
            "  Right-click   Tab context menu\n"
            "\n"
            "Analysis\n"
            "  Ctrl+F        FFT / Spectrum\n"
            "  Ctrl+E        Eye Diagram\n"
            "  Ctrl+M        Expression\n"
            "\n"
            "Zoom\n"
            "  Shift+Z       Zoom in (X+Y)\n"
            "  Ctrl+Z        Zoom out (X+Y)\n"
            "  x             Zoom in X only\n"
            "  Shift+X       Zoom out X only\n"
            "  y             Zoom in Y only\n"
            "  Shift+Y       Zoom out Y only\n"
            "  c             Zoom to cursor region\n"
            "  u             Undo zoom\n"
            "  Scroll        Zoom x-axis (at mouse)\n"
            "  Shift+Scroll  Zoom y-axis (at mouse)\n"
            "  Middle-drag   Rubber-band zoom\n"
            "\n"
            "Pan\n"
            "  \u2190 \u2192 \u2191 \u2193      Pan view\n"
            "  Ctrl+drag     Pan with mouse\n"
        )
        win = Toplevel(self.root)
        win.title("Keyboard Shortcuts")
        win.resizable(False, False)
        theme = _get_theme()
        label = Label(win, text=text, justify=LEFT,
                      font=("Courier", 11),
                      bg=theme['panel_bg'], fg=theme['panel_fg'],
                      padx=16, pady=12)
        label.pack(fill=BOTH, expand=True)
        btn = ttk.Button(win, text="Close", command=win.destroy)
        btn.pack(pady=(0, 10))
        win.transient(self.root)
        win.grab_set()

    # --- Menu actions ---

    def newPlot(self):
        self.graph.addPlot()

    def reloadPlots(self):
        self.graph.reloadPlots()
        self._updateWindowTitle()

    def openFile(self, fname, sheet_name=None):
        self.browser.openFile(fname)
        self._current_file = fname
        _add_recent_file(fname)
        self._refreshRecentMenu()
        self._updateWindowTitle()

    def openDataFrame(self, df, name, **kwargs):
        self.browser.openDataFrame(df, name)
        self._updateWindowTitle()

    def run(self):
        tkinter.mainloop()

    def openFileDialog(self):
        filename = tkinter.filedialog.askopenfilename(initialdir=os.getcwd())
        if filename:
            self.browser.openFile(filename)
            self._current_file = filename
            _add_recent_file(filename)
            self._refreshRecentMenu()
            self._updateWindowTitle()
