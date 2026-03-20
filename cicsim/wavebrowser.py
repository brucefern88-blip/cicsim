#!/usr/bin/env python3

#- Controller for waves

from tkinter import *
from tkinter import ttk
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import colorchooser
import cicsim as cs
import re
import os
import fnmatch
import json
import numpy as np

from .theme import _get_theme

#- Data Model
from .wavefiles import *


def _classify_signal(name):
    """Extract a group name from a signal name.

    Recognises patterns like:
        v(oh0[3])  -> "oh0"
        v(hd[6])   -> "hd"
        v(a[15])   -> "a"
        i(vdd)     -> "i(...)"
        time       -> ""  (ungrouped)
    """
    m = re.match(r'^([vi])\(([A-Za-z_][A-Za-z0-9_]*)', name)
    if m:
        prefix, base = m.group(1), m.group(2)
        return "%s(%s)" % (prefix, base)
    return ""


class WaveBrowser(ttk.Frame):
    """
The WaveBrowser keeps track of files loaded, and shows the waves in the files.

Click on a wave will ask the WaveGraph to show the plot
    """
    def __init__(self, simfolder, graph, xaxis, master=None, **kw):

        self.xaxis = xaxis
        super().__init__(master, width=300, borderwidth=1, relief="raised", **kw)
        self.simfolder = simfolder
        self.graph = graph

        # Favorites set and persistence path (set when a file is opened)
        self._favorites = set()
        self._fav_path = None

        p = ttk.PanedWindow(self, orient=VERTICAL)
        p.pack(fill="both", expand=1)

        self.tr_files = ttk.Treeview(p)
        self.tr_files.bind('<<TreeviewSelect>>', self.fileSelected)

        # --- Search / filter box ---
        search_frame = ttk.Frame(p)
        self.search = StringVar()
        self.search.set("")
        self.tr_search = ttk.Entry(search_frame, textvariable=self.search)
        self.tr_search.pack(side=LEFT, fill=X, expand=True)
        self.search.trace_add("write", self.updateSearch)

        self._search_mode = StringVar(value="glob")
        self._mode_btn = ttk.Button(search_frame, text="glob", width=5,
                                     command=self._toggle_search_mode)
        self._mode_btn.pack(side=RIGHT, padx=(2, 0))

        self._tooltip = None
        self._tooltip_id = None
        self.tr_search.bind('<Enter>', self._show_tooltip)
        self.tr_search.bind('<Leave>', self._hide_tooltip)

        # --- Wave treeview (hierarchical with sortable columns) ---
        tree_cols = ('type', 'min', 'max', 'group')
        self.tr_waves = ttk.Treeview(p, selectmode="extended",
                                      columns=tree_cols)
        self.tr_waves.heading('#0', text='Name',
                               command=lambda: self._sort_column('#0'))
        self.tr_waves.column('#0', width=160, minwidth=80)
        self.tr_waves.heading('type', text='Type',
                               command=lambda: self._sort_column('type'))
        self.tr_waves.column('type', width=50, minwidth=30)
        self.tr_waves.heading('min', text='Min',
                               command=lambda: self._sort_column('min'))
        self.tr_waves.column('min', width=70, minwidth=40)
        self.tr_waves.heading('max', text='Max',
                               command=lambda: self._sort_column('max'))
        self.tr_waves.column('max', width=70, minwidth=40)
        self.tr_waves.heading('group', text='Group',
                               command=lambda: self._sort_column('group'))
        self.tr_waves.column('group', width=60, minwidth=40)

        self.tr_waves.bind('<<TreeviewSelect>>', self.waveSelected)
        self.tr_waves.bind('<Button-3>', self._on_right_click)  # macOS right-click
        self.tr_waves.bind('<Button-2>', self._on_right_click)  # macOS ctrl-click
        self.tr_waves.bind('<Control-Button-1>', self._on_right_click)

        # Column sort state
        self._sort_col = None
        self._sort_reverse = False

        # Signal preview tooltip state
        self._preview_tooltip = None
        self._preview_tooltip_id = None
        self.tr_waves.bind('<Motion>', self._on_tree_motion)
        self.tr_waves.bind('<Leave>', self._hide_preview_tooltip)
        self._preview_last_iid = None

        # Drag-and-drop support
        self._drag_data = None
        self.tr_waves.bind('<ButtonPress-1>', self._on_drag_start)
        self.tr_waves.bind('<B1-Motion>', self._on_drag_motion)
        self.tr_waves.bind('<ButtonRelease-1>', self._on_drag_end)
        self._drag_indicator = None

        p.add(self.tr_files)
        p.add(search_frame)
        p.add(self.tr_waves)

        # --- Batch operations toolbar ---
        batch_frame = ttk.Frame(p)
        ttk.Button(batch_frame, text="Add Selected",
                   command=self._batch_add_selected).pack(
                       side=LEFT, padx=1, pady=1)
        ttk.Button(batch_frame, text="Remove Selected",
                   command=self._batch_remove_selected).pack(
                       side=LEFT, padx=1, pady=1)
        ttk.Button(batch_frame, text="Group Selected",
                   command=self._batch_group_selected).pack(
                       side=LEFT, padx=1, pady=1)
        ttk.Button(batch_frame, text="Alias Selected",
                   command=self._batch_alias_selected).pack(
                       side=LEFT, padx=1, pady=1)
        p.add(batch_frame)

        self.files = WaveFiles()

        # Map: tree iid -> signal name (for group nodes the iid is the group tag)
        self._iid_to_signal = {}
        # Map: group tag -> list of signal names
        self._group_signals = {}
        # Reverse: signal name -> group tag
        self._signal_group = {}

    # ------------------------------------------------------------------
    # Search mode toggle
    # ------------------------------------------------------------------

    def _toggle_search_mode(self):
        if self._search_mode.get() == "glob":
            self._search_mode.set("regex")
            self._mode_btn.config(text="regex")
        else:
            self._search_mode.set("glob")
            self._mode_btn.config(text="glob")
        self.fillColumns()

    # ------------------------------------------------------------------
    # Tooltip
    # ------------------------------------------------------------------

    _REGEX_HELP = (
        "Search filter\n"
        "---------------------\n"
        "Glob mode (default):\n"
        "  *        match anything\n"
        "  ?        match one char\n"
        "  *hd*     signals containing hd\n"
        "  v(a[*    signals starting v(a[\n"
        "\n"
        "Regex mode (toggle button):\n"
        "  .        any character\n"
        "  .*       match anything\n"
        "  ^abc     starts with abc\n"
        "  abc$     ends with abc\n"
        "  [abc]    a, b, or c\n"
        "  a|b      a or b\n"
        "  \\(       literal (\n"
        "Examples:\n"
        "  v\\(.*out   signals matching v(...out\n"
        "  ^i\\(       current signals\n"
        "  vdd|vss    vdd or vss"
    )

    def _show_tooltip(self, event):
        self._tooltip_id = self.tr_search.after(500, self._create_tooltip)

    def _hide_tooltip(self, event=None):
        if self._tooltip_id:
            self.tr_search.after_cancel(self._tooltip_id)
            self._tooltip_id = None
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None

    def _create_tooltip(self):
        x = self.tr_search.winfo_rootx() + 20
        y = self.tr_search.winfo_rooty() + self.tr_search.winfo_height() + 4
        self._tooltip = Toplevel(self.tr_search)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.wm_geometry("+%d+%d" % (x, y))
        theme = _get_theme()
        label = Label(self._tooltip, text=self._REGEX_HELP,
                      justify=LEFT, font=("Courier", 10),
                      bg=theme['panel_bg'], fg=theme['panel_fg'],
                      borderwidth=1, relief="solid", padx=6, pady=4)
        label.pack()

    # ------------------------------------------------------------------
    # Search filter
    # ------------------------------------------------------------------

    def _matches_filter(self, name):
        pattern = self.search.get()
        if not pattern:
            return True
        if self._search_mode.get() == "glob":
            # Case-insensitive glob
            if '*' not in pattern and '?' not in pattern:
                pattern = '*' + pattern + '*'
            return fnmatch.fnmatch(name.lower(), pattern.lower())
        else:
            try:
                return bool(re.search(pattern, name, re.IGNORECASE))
            except re.error:
                return True

    def updateSearch(self, *args):
        self.fillColumns()

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------

    def fileSelected(self, event):
        fname = self.tr_files.focus()
        self.files.select(fname)
        self._load_favorites()
        self.fillColumns()

    # ------------------------------------------------------------------
    # Wave selection  (single click = select only, double-click = add to plot)
    # ------------------------------------------------------------------

    def waveSelected(self, event):
        # On single select in extended mode, do nothing (wait for double-click
        # or context menu).  But preserve backwards compat: the original code
        # added signal on any select.  We keep that for double-click via a
        # separate binding.
        pass

    def _on_double_click(self, event):
        sel = self.tr_waves.selection()
        for iid in sel:
            self._add_signal_by_iid(iid)

    def _add_signal_by_iid(self, iid):
        if iid in self._iid_to_signal:
            name = self._iid_to_signal[iid]
            f = self.files.getSelected()
            if f:
                self.graph.show(f.getWave(name))
        elif iid in self._group_signals:
            # It's a group node - add all children
            f = self.files.getSelected()
            if f:
                for name in self._group_signals[iid]:
                    self.graph.show(f.getWave(name))

    # ------------------------------------------------------------------
    # Populate tree with hierarchical groups
    # ------------------------------------------------------------------

    @staticmethod
    def _signal_type(name):
        """Return 'V', 'I', or '' based on signal name prefix."""
        nl = name.lower()
        if nl.startswith("v(") or nl.startswith("v-"):
            return "V"
        if nl.startswith("i(") or nl.startswith("i-"):
            return "I"
        return ""

    def _signal_stats(self, name):
        """Return (min_str, max_str) for a signal, or ('', '') on error."""
        f = self.files.getSelected()
        if f is None:
            return ('', '')
        try:
            wave = f.getWave(name)
            if wave.y is not None:
                y = np.real(wave.y)
                from matplotlib.ticker import EngFormatter
                unit = wave.yunit or ""
                eng = EngFormatter(unit=unit)
                return (eng(float(np.min(y))), eng(float(np.max(y))))
        except Exception:
            pass
        return ('', '')

    def _display_name(self, name):
        """Return alias-decorated display name for the tree."""
        alias = self.files.getAlias(name)
        if alias:
            return "%s  [%s]" % (alias, name)
        return name

    def fillColumns(self):
        # Unbind double-click before clearing (re-bind after)
        self.tr_waves.unbind('<Double-1>')

        for item in self.tr_waves.get_children():
            self.tr_waves.delete(item)

        self._iid_to_signal = {}
        self._group_signals = {}
        self._signal_group = {}

        f = self.files.getSelected()
        if f is None:
            return

        # Classify all wave names into groups
        groups = {}  # group_name -> [signal_name, ...]
        ungrouped = []
        all_names = list(f.getWaveNames())

        for wn in all_names:
            if not self._matches_filter(wn):
                continue
            g = _classify_signal(wn)
            if g:
                groups.setdefault(g, []).append(wn)
            else:
                ungrouped.append(wn)

        # Favorites first -- collect all matching favorites
        fav_names = []
        non_fav_ungrouped = []
        for wn in ungrouped:
            if wn in self._favorites:
                fav_names.append(wn)
            else:
                non_fav_ungrouped.append(wn)

        fav_grouped = {}  # group -> [names that are favorites]
        non_fav_grouped = {}
        for g, names in sorted(groups.items()):
            for wn in names:
                if wn in self._favorites:
                    fav_grouped.setdefault(g, []).append(wn)
                else:
                    non_fav_grouped.setdefault(g, []).append(wn)

        # Insert favorites section
        has_any_fav = bool(fav_names) or bool(fav_grouped)
        if has_any_fav:
            fav_root = self.tr_waves.insert('', 'end', '::fav_root',
                                             text='* Favorites', open=True)
            for wn in fav_names:
                iid = '::fav::' + wn
                disp = '* ' + self._display_name(wn)
                stype = self._signal_type(wn)
                mn, mx = self._signal_stats(wn)
                grp_str = ', '.join(self.files.getGroupForSignal(wn))
                self.tr_waves.insert(fav_root, 'end', iid, text=disp,
                                      values=(stype, mn, mx, grp_str))
                self._iid_to_signal[iid] = wn
            for g, names in sorted(fav_grouped.items()):
                g_iid = '::fav_grp::' + g
                self.tr_waves.insert(fav_root, 'end', g_iid,
                                      text='* ' + g, open=True)
                self._group_signals[g_iid] = names
                for wn in names:
                    iid = '::fav::' + wn
                    disp = '* ' + self._display_name(wn)
                    stype = self._signal_type(wn)
                    mn, mx = self._signal_stats(wn)
                    grp_str = ', '.join(self.files.getGroupForSignal(wn))
                    self.tr_waves.insert(g_iid, 'end', iid, text=disp,
                                          values=(stype, mn, mx, grp_str))
                    self._iid_to_signal[iid] = wn
                    self._signal_group[wn] = g_iid

        # Insert user-defined groups
        for ugrp_name in self.files.getGroupNames():
            ugrp_sigs = self.files.getGroup(ugrp_name)
            visible = [s for s in ugrp_sigs if self._matches_filter(s)]
            if not visible:
                continue
            g_iid = '::ugrp::' + ugrp_name
            is_open = bool(self.search.get())
            self.tr_waves.insert('', 'end', g_iid,
                                  text='[G] %s [%d]' % (ugrp_name, len(visible)),
                                  open=is_open)
            self._group_signals[g_iid] = visible
            for wn in visible:
                iid = '::usig::' + ugrp_name + '::' + wn
                disp = self._display_name(wn)
                stype = self._signal_type(wn)
                mn, mx = self._signal_stats(wn)
                self.tr_waves.insert(g_iid, 'end', iid, text=disp,
                                      values=(stype, mn, mx, ugrp_name))
                self._iid_to_signal[iid] = wn
                self._signal_group[wn] = g_iid

        # Insert ungrouped signals
        for wn in non_fav_ungrouped:
            iid = '::sig::' + wn
            prefix = '* ' if wn in self._favorites else ''
            disp = prefix + self._display_name(wn)
            stype = self._signal_type(wn)
            mn, mx = self._signal_stats(wn)
            grp_str = ', '.join(self.files.getGroupForSignal(wn))
            self.tr_waves.insert('', 'end', iid, text=disp,
                                  values=(stype, mn, mx, grp_str))
            self._iid_to_signal[iid] = wn

        # Insert grouped signals
        for g, names in sorted(non_fav_grouped.items()):
            g_iid = '::grp::' + g
            is_open = bool(self.search.get())
            self.tr_waves.insert('', 'end', g_iid,
                                  text=g + (' [%d]' % len(names)), open=is_open)
            self._group_signals[g_iid] = names
            for wn in names:
                iid = '::sig::' + wn
                prefix = '* ' if wn in self._favorites else ''
                disp = prefix + self._display_name(wn)
                stype = self._signal_type(wn)
                mn, mx = self._signal_stats(wn)
                grp_str = ', '.join(self.files.getGroupForSignal(wn))
                self.tr_waves.insert(g_iid, 'end', iid, text=disp,
                                      values=(stype, mn, mx, grp_str))
                self._iid_to_signal[iid] = wn
                self._signal_group[wn] = g_iid

        # Re-bind double-click
        self.tr_waves.bind('<Double-1>', self._on_double_click)

    # ------------------------------------------------------------------
    # Right-click context menu
    # ------------------------------------------------------------------

    def _on_right_click(self, event):
        # Select the item under cursor if not already selected
        iid = self.tr_waves.identify_row(event.y)
        if iid:
            sel = self.tr_waves.selection()
            if iid not in sel:
                self.tr_waves.selection_set(iid)

        menu = Menu(self.tr_waves, tearoff=0)
        menu.add_command(label="Add to Plot", command=self._ctx_add_to_plot)
        menu.add_command(label="Add All in Group",
                         command=self._ctx_add_all_in_group)
        menu.add_separator()
        menu.add_command(label="Toggle Favorite",
                         command=self._ctx_toggle_favorite)
        menu.add_separator()
        menu.add_command(label="Properties...",
                         command=self._ctx_properties)
        menu.add_command(label="Copy Signal Name",
                         command=self._ctx_copy_name)
        menu.add_command(label="Signal Info", command=self._ctx_signal_info)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _get_selected_signal_names(self):
        """Return list of signal names for all currently selected tree items."""
        names = []
        for iid in self.tr_waves.selection():
            if iid in self._iid_to_signal:
                names.append(self._iid_to_signal[iid])
            elif iid in self._group_signals:
                names.extend(self._group_signals[iid])
        return names

    def _ctx_add_to_plot(self):
        f = self.files.getSelected()
        if not f:
            return
        for name in self._get_selected_signal_names():
            self.graph.show(f.getWave(name))

    def _ctx_add_all_in_group(self):
        f = self.files.getSelected()
        if not f:
            return
        # Determine the group(s) for the selected items
        added = set()
        for iid in self.tr_waves.selection():
            # If it's a group node itself
            if iid in self._group_signals:
                for name in self._group_signals[iid]:
                    if name not in added:
                        self.graph.show(f.getWave(name))
                        added.add(name)
            elif iid in self._iid_to_signal:
                sig = self._iid_to_signal[iid]
                # Find the group this signal belongs to
                parent = self.tr_waves.parent(iid)
                if parent and parent in self._group_signals:
                    for name in self._group_signals[parent]:
                        if name not in added:
                            self.graph.show(f.getWave(name))
                            added.add(name)
                else:
                    if sig not in added:
                        self.graph.show(f.getWave(sig))
                        added.add(sig)

    def _ctx_copy_name(self):
        names = self._get_selected_signal_names()
        if names:
            text = '\n'.join(names)
            self.clipboard_clear()
            self.clipboard_append(text)

    def _ctx_signal_info(self):
        f = self.files.getSelected()
        if not f:
            return
        names = self._get_selected_signal_names()
        if not names:
            return

        info_parts = []
        for name in names[:10]:  # cap at 10 to avoid huge dialogs
            wave = f.getWave(name)
            y = wave.y
            if y is not None:
                y_real = np.real(y)
                mn = float(np.min(y_real))
                mx = float(np.max(y_real))
                avg = float(np.mean(y_real))
                rms = float(np.sqrt(np.mean(y_real ** 2)))
                pp = mx - mn
                unit = wave.yunit or ""
                from matplotlib.ticker import EngFormatter
                eng = EngFormatter(unit=unit)
                info_parts.append(
                    "%s\n"
                    "  Unit:  %s\n"
                    "  Min:   %s\n"
                    "  Max:   %s\n"
                    "  Avg:   %s\n"
                    "  RMS:   %s\n"
                    "  Pk-Pk: %s\n"
                    "  Points: %d"
                    % (name, unit or "(none)",
                       eng(mn), eng(mx), eng(avg), eng(rms), eng(pp),
                       len(y_real))
                )
            else:
                info_parts.append("%s\n  (no data)" % name)

        theme = _get_theme()
        win = Toplevel(self)
        win.title("Signal Info")
        win.resizable(False, False)
        label = Label(win, text='\n\n'.join(info_parts), justify=LEFT,
                      font=("Courier", 11),
                      bg=theme['panel_bg'], fg=theme['panel_fg'],
                      padx=12, pady=8)
        label.pack(fill=BOTH, expand=True)
        btn = ttk.Button(win, text="Close", command=win.destroy)
        btn.pack(pady=(0, 8))
        win.transient(self.winfo_toplevel())
        win.grab_set()

    # ------------------------------------------------------------------
    # Signal property editor dialog
    # ------------------------------------------------------------------

    def _ctx_properties(self):
        names = self._get_selected_signal_names()
        if not names:
            return
        # Open property editor for the first selected signal
        name = names[0]
        f = self.files.getSelected()
        if not f:
            return

        wave = f.getWave(name)
        theme = _get_theme()
        win = Toplevel(self)
        win.title("Signal Properties: %s" % name)
        win.resizable(False, False)

        row = 0
        pad = dict(padx=8, pady=3, sticky=W)

        # --- Alias ---
        Label(win, text="Alias:", bg=theme['panel_bg'],
              fg=theme['panel_fg']).grid(row=row, column=0, **pad)
        alias_var = StringVar(value=self.files.getAlias(name) or "")
        Entry(win, textvariable=alias_var, width=30).grid(
            row=row, column=1, padx=8, pady=3)
        row += 1

        # --- Color ---
        Label(win, text="Color:", bg=theme['panel_bg'],
              fg=theme['panel_fg']).grid(row=row, column=0, **pad)
        current_color = wave.line.get_color() if wave.line else '#1f77b4'
        color_var = StringVar(value=current_color)
        color_frame = Frame(win)
        color_frame.grid(row=row, column=1, padx=8, pady=3, sticky=W)
        color_swatch = Label(color_frame, text="    ", bg=current_color,
                             borderwidth=1, relief="solid")
        color_swatch.pack(side=LEFT)
        def _pick_color():
            result = colorchooser.askcolor(color=color_var.get(),
                                           parent=win)
            if result[1]:
                color_var.set(result[1])
                color_swatch.config(bg=result[1])
        ttk.Button(color_frame, text="Choose...",
                   command=_pick_color).pack(side=LEFT, padx=4)
        row += 1

        # --- Line style ---
        Label(win, text="Line Style:", bg=theme['panel_bg'],
              fg=theme['panel_fg']).grid(row=row, column=0, **pad)
        style_options = ['solid', 'dashed', 'dotted', 'dashdot']
        current_style = 'solid'
        if wave.line:
            ls = wave.line.get_linestyle()
            ls_map = {'-': 'solid', '--': 'dashed', ':': 'dotted',
                      '-.': 'dashdot'}
            current_style = ls_map.get(ls, ls)
        style_var = StringVar(value=current_style)
        style_combo = ttk.Combobox(win, textvariable=style_var,
                                    values=style_options, state="readonly",
                                    width=12)
        style_combo.grid(row=row, column=1, padx=8, pady=3, sticky=W)
        row += 1

        # --- Line width ---
        Label(win, text="Line Width:", bg=theme['panel_bg'],
              fg=theme['panel_fg']).grid(row=row, column=0, **pad)
        current_width = wave.line.get_linewidth() if wave.line else 1.5
        width_var = DoubleVar(value=current_width)
        Spinbox(win, from_=0.5, to=10.0, increment=0.5,
                textvariable=width_var, width=8).grid(
            row=row, column=1, padx=8, pady=3, sticky=W)
        row += 1

        # --- Y-axis assignment ---
        Label(win, text="Y-Axis:", bg=theme['panel_bg'],
              fg=theme['panel_fg']).grid(row=row, column=0, **pad)
        # Determine current axis index from graph's wave_data
        current_ax = 0
        plot = self.graph.getCurrentPlot() if hasattr(self.graph, 'getCurrentPlot') else None
        if plot and wave.tag in plot.wave_data:
            _, current_ax = plot.wave_data[wave.tag]
        num_axes = plot._num_axes if plot else 1
        axis_var = IntVar(value=current_ax)
        axis_combo = ttk.Combobox(win, textvariable=axis_var,
                                   values=list(range(num_axes)),
                                   state="readonly", width=8)
        axis_combo.grid(row=row, column=1, padx=8, pady=3, sticky=W)
        row += 1

        # --- Visibility toggle ---
        visible_var = BooleanVar(value=True)
        if wave.line:
            visible_var.set(wave.line.get_visible())
        Checkbutton(win, text="Visible", variable=visible_var,
                    bg=theme['panel_bg'], fg=theme['panel_fg'],
                    selectcolor=theme['panel_bg']).grid(
            row=row, column=0, columnspan=2, padx=8, pady=3, sticky=W)
        row += 1

        # --- Apply / Cancel ---
        def _apply():
            # Alias
            alias_val = alias_var.get().strip()
            self.files.setAlias(name, alias_val if alias_val else None)

            # Line properties
            if wave.line:
                wave.line.set_color(color_var.get())
                style_map = {'solid': '-', 'dashed': '--',
                              'dotted': ':', 'dashdot': '-.'}
                wave.line.set_linestyle(style_map.get(style_var.get(), '-'))
                wave.line.set_linewidth(width_var.get())
                wave.line.set_visible(visible_var.get())

                # Update tree tag color
                if plot and wave.tag in plot.wave_data:
                    if plot.tree.exists(wave.tag):
                        plot.tree.tag_configure(
                            wave.tag, foreground=color_var.get())

                # Y-axis reassignment
                new_ax = int(axis_var.get())
                if plot and wave.tag in plot.wave_data:
                    _, old_ax = plot.wave_data[wave.tag]
                    if new_ax != old_ax and new_ax < len(plot.axes):
                        wave.line.remove()
                        wave.line = None
                        wave.plot(plot.axes[new_ax])
                        plot.wave_data[wave.tag] = (wave, new_ax)
                        if plot.tree.exists(wave.tag):
                            text = "A%d: %s" % (new_ax, wave.ylabel)
                            plot.tree.item(wave.tag, text=text)
                            plot.tree.tag_configure(
                                wave.tag,
                                foreground=wave.line.get_color())

                plot.canvas.draw_idle()

            # Update alias in ylabel for legend
            if alias_val:
                wave.ylabel = alias_val
                if wave.line:
                    wave.line.set_label(alias_val)
            else:
                if hasattr(wave, 'wfile'):
                    wave.ylabel = wave.key + " (%s)" % wave.wfile.name
                else:
                    wave.ylabel = wave.key
                if wave.line:
                    wave.line.set_label(wave.ylabel)

            self.fillColumns()
            win.destroy()

        btn_frame = Frame(win, bg=theme['panel_bg'])
        btn_frame.grid(row=row, column=0, columnspan=2, pady=8)
        ttk.Button(btn_frame, text="Apply", command=_apply).pack(
            side=LEFT, padx=8)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy).pack(
            side=LEFT, padx=8)

        win.transient(self.winfo_toplevel())
        win.grab_set()

    # ------------------------------------------------------------------
    # Column sorting
    # ------------------------------------------------------------------

    def _sort_column(self, col):
        """Sort the treeview by the given column, toggling direction."""
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False

        # Collect top-level items
        items = list(self.tr_waves.get_children(''))
        if not items:
            return

        def sort_key(iid):
            if col == '#0':
                return self.tr_waves.item(iid, 'text').lower()
            else:
                vals = self.tr_waves.item(iid, 'values')
                idx = {'type': 0, 'min': 1, 'max': 2, 'group': 3}.get(col, 0)
                if idx < len(vals):
                    return str(vals[idx]).lower()
                return ''

        items.sort(key=sort_key, reverse=self._sort_reverse)

        for idx, iid in enumerate(items):
            self.tr_waves.move(iid, '', idx)

    # ------------------------------------------------------------------
    # Signal preview tooltip (mini waveform + stats on hover)
    # ------------------------------------------------------------------

    def _on_tree_motion(self, event):
        iid = self.tr_waves.identify_row(event.y)
        if iid == self._preview_last_iid:
            return
        self._preview_last_iid = iid
        self._hide_preview_tooltip()
        if iid and iid in self._iid_to_signal:
            self._preview_tooltip_id = self.tr_waves.after(
                400, lambda: self._show_preview_tooltip(event, iid))

    def _hide_preview_tooltip(self, event=None):
        if self._preview_tooltip_id:
            self.tr_waves.after_cancel(self._preview_tooltip_id)
            self._preview_tooltip_id = None
        if self._preview_tooltip:
            self._preview_tooltip.destroy()
            self._preview_tooltip = None
        self._preview_last_iid = None

    def _show_preview_tooltip(self, event, iid):
        if iid not in self._iid_to_signal:
            return
        name = self._iid_to_signal[iid]
        f = self.files.getSelected()
        if not f:
            return

        wave = f.getWave(name)
        if wave.y is None:
            return

        y_real = np.real(wave.y)
        mn = float(np.min(y_real))
        mx = float(np.max(y_real))
        avg = float(np.mean(y_real))
        from matplotlib.ticker import EngFormatter
        unit = wave.yunit or ""
        eng = EngFormatter(unit=unit)

        # Create tooltip window
        x_pos = self.tr_waves.winfo_rootx() + event.x + 20
        y_pos = self.tr_waves.winfo_rooty() + event.y + 10
        self._preview_tooltip = Toplevel(self.tr_waves)
        self._preview_tooltip.wm_overrideredirect(True)
        self._preview_tooltip.wm_geometry("+%d+%d" % (x_pos, y_pos))

        theme = _get_theme()
        frame = Frame(self._preview_tooltip, bg=theme['panel_bg'],
                      borderwidth=1, relief="solid")
        frame.pack()

        # Mini waveform thumbnail using matplotlib
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            fig = Figure(figsize=(2.0, 0.8), dpi=72)
            fig.patch.set_facecolor(theme['panel_bg'])
            ax = fig.add_subplot(111)
            ax.set_facecolor(theme['panel_bg'])

            x_data = np.real(wave.x) if wave.x is not None else np.arange(len(y_real))
            # Downsample if too many points for the thumbnail
            step = max(1, len(x_data) // 200)
            ax.plot(x_data[::step], y_real[::step], color='#2196F3',
                    linewidth=0.8)
            ax.tick_params(labelbottom=False, labelleft=False,
                           bottom=False, left=False)
            for spine in ax.spines.values():
                spine.set_visible(False)
            fig.tight_layout(pad=0.1)

            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().pack(padx=2, pady=2)
        except Exception:
            pass

        # Stats text
        stats_text = ("Min: %s  Max: %s  Avg: %s  Pts: %d"
                      % (eng(mn), eng(mx), eng(avg), len(y_real)))
        alias = self.files.getAlias(name)
        if alias:
            stats_text = "Alias: %s\n%s" % (alias, stats_text)
        Label(frame, text=stats_text, font=("Courier", 8),
              bg=theme['panel_bg'], fg=theme['panel_fg'],
              justify=LEFT, padx=4, pady=2).pack()

    # ------------------------------------------------------------------
    # Batch operations toolbar handlers
    # ------------------------------------------------------------------

    def _batch_add_selected(self):
        """Add all selected signals to the current plot."""
        self._ctx_add_to_plot()

    def _batch_remove_selected(self):
        """Remove selected signals from the current plot."""
        names = self._get_selected_signal_names()
        if not names:
            return
        plot = (self.graph.getCurrentPlot()
                if hasattr(self.graph, 'getCurrentPlot') else None)
        if not plot:
            return
        f = self.files.getSelected()
        if not f:
            return
        for name in names:
            wave = f.getWave(name)
            if wave.tag in plot.wave_data:
                plot._remove_tag(wave.tag)
        plot.canvas.draw_idle()

    def _batch_group_selected(self):
        """Create a user-defined group from selected signals."""
        names = self._get_selected_signal_names()
        if not names:
            messagebox.showinfo("Group Selected",
                                "No signals selected.",
                                parent=self.winfo_toplevel())
            return
        grp_name = simpledialog.askstring(
            "Group Selected",
            "Group name for %d signal(s):" % len(names),
            parent=self.winfo_toplevel())
        if not grp_name:
            return
        self.files.createGroup(grp_name, names)
        self.fillColumns()

    def _batch_alias_selected(self):
        """Set an alias for each selected signal (prompted one by one)."""
        names = self._get_selected_signal_names()
        if not names:
            messagebox.showinfo("Alias Selected",
                                "No signals selected.",
                                parent=self.winfo_toplevel())
            return

        if len(names) == 1:
            current = self.files.getAlias(names[0]) or ""
            alias = simpledialog.askstring(
                "Set Alias",
                "Alias for %s:" % names[0],
                initialvalue=current,
                parent=self.winfo_toplevel())
            if alias is not None:
                self.files.setAlias(names[0], alias if alias else None)
        else:
            prefix = simpledialog.askstring(
                "Batch Alias",
                "Prefix for %d signals (e.g. 'cell0_').\n"
                "Each signal gets prefix + its base name:" % len(names),
                parent=self.winfo_toplevel())
            if prefix is not None:
                for name in names:
                    # Extract a short base: last component after dots/parens
                    base = name
                    m = re.search(r'[vi]\((.+)\)', name)
                    if m:
                        base = m.group(1)
                    self.files.setAlias(name, prefix + base)
        self.fillColumns()

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    def _ctx_toggle_favorite(self):
        names = self._get_selected_signal_names()
        for name in names:
            if name in self._favorites:
                self._favorites.discard(name)
            else:
                self._favorites.add(name)
        self._save_favorites()
        self.fillColumns()

    def _fav_file_path(self):
        """Derive the .cicfav path from the currently selected file."""
        f = self.files.getSelected()
        if f is None:
            return None
        fname = f.fname
        if fname.startswith("::virtual::"):
            # Virtual dataframes -- use cwd
            return os.path.join(os.getcwd(), '.cicfav')
        base = os.path.splitext(fname)[0]
        return base + '.cicfav'

    def _load_favorites(self):
        self._favorites = set()
        path = self._fav_file_path()
        self._fav_path = path
        if path and os.path.exists(path):
            try:
                with open(path, 'r') as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        self._favorites = set(data)
            except Exception:
                pass

    def _save_favorites(self):
        path = self._fav_path or self._fav_file_path()
        if not path:
            return
        try:
            with open(path, 'w') as fh:
                json.dump(sorted(self._favorites), fh, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Drag and drop (browser tree -> plot area)
    # ------------------------------------------------------------------

    def _on_drag_start(self, event):
        iid = self.tr_waves.identify_row(event.y)
        if not iid:
            self._drag_data = None
            return
        # Record start position; we only begin a drag if the mouse moves
        self._drag_data = {'iid': iid, 'x': event.x, 'y': event.y,
                           'started': False}

    def _on_drag_motion(self, event):
        if self._drag_data is None:
            return
        # Require a minimum movement to distinguish click from drag
        dx = abs(event.x - self._drag_data['x'])
        dy = abs(event.y - self._drag_data['y'])
        if not self._drag_data['started'] and (dx > 5 or dy > 5):
            self._drag_data['started'] = True
            self.tr_waves.config(cursor="plus")
            # Show a floating indicator
            if self._drag_indicator is None:
                iid = self._drag_data['iid']
                text = self.tr_waves.item(iid, 'text')
                theme = _get_theme()
                self._drag_indicator = Toplevel(self)
                self._drag_indicator.wm_overrideredirect(True)
                self._drag_indicator.attributes('-alpha', 0.8)
                lbl = Label(self._drag_indicator, text=text,
                            font=("Courier", 9),
                            bg=theme['panel_bg'], fg=theme['panel_fg'],
                            borderwidth=1, relief="solid", padx=4, pady=2)
                lbl.pack()

        if self._drag_data.get('started') and self._drag_indicator:
            self._drag_indicator.wm_geometry(
                "+%d+%d" % (event.x_root + 12, event.y_root + 12))

    def _on_drag_end(self, event):
        if self._drag_indicator:
            self._drag_indicator.destroy()
            self._drag_indicator = None

        if self._drag_data is None:
            return

        was_drag = self._drag_data.get('started', False)
        self.tr_waves.config(cursor="")

        if was_drag:
            # Check if the drop target is over the graph area
            # Get the widget under the cursor
            target = event.widget.winfo_containing(event.x_root, event.y_root)
            # Walk up widget hierarchy to see if we're over the graph
            w = target
            graph_hit = False
            while w is not None:
                if w is self.graph:
                    graph_hit = True
                    break
                try:
                    w = w.master
                except Exception:
                    break

            if graph_hit:
                # Add all selected signals (or the dragged one)
                sel = self.tr_waves.selection()
                if not sel:
                    sel = (self._drag_data['iid'],)
                f = self.files.getSelected()
                if f:
                    for iid in sel:
                        self._add_signal_by_iid(iid)

        self._drag_data = None

    # ------------------------------------------------------------------
    # File open
    # ------------------------------------------------------------------

    def openFile(self, fname):
        f = self.files.open(fname, self.xaxis)
        self.tr_files.insert('', 'end', f.fname, text=f.name)
        self._load_favorites()
        self.fillColumns()

    def openDataFrame(self, df, name):
        f = self.files.openDataFrame(df, name, self.xaxis)
        key = self.files.current
        self.tr_files.insert('', 'end', key, text=f.name)
        self._load_favorites()
        self.fillColumns()
