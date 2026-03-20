#!/usr/bin/env python3

from tkinter import *
from tkinter import ttk
import tkinter
import tkinter.filedialog
import os
import numpy as np
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                               NavigationToolbar2Tk)
from matplotlib.figure import Figure
from matplotlib.ticker import EngFormatter, AutoMinorLocator
from matplotlib import gridspec as mpl_gridspec

from .theme import _get_theme, _set_active_theme

CURSOR_KWARGS = {'linestyle': '--', 'linewidth': 1.0, 'alpha': 0.8}
DRAG_TOLERANCE_PX = 10
ZOOM_FACTOR = 1.3
PAN_FRACTION = 0.15


class WavePlot(ttk.PanedWindow):

    def __init__(self, master, **kw):
        super().__init__(master, orient=HORIZONTAL, **kw)

        # --- Left panel: wave list and controls ---
        left = ttk.Frame(self)
        self.add(left)

        self.combo = ttk.Combobox(left)
        self.combo.grid(column=0, row=0, columnspan=2, sticky=(N, E, W))
        self.combo.state(["readonly"])
        self.combo.bind('<<ComboboxSelected>>', self._set_axis_index)

        self.tree = ttk.Treeview(left)
        self.tree.grid(column=0, row=1, columnspan=2, sticky=(N, S, E, W))

        ttk.Button(left, text="Remove", command=self.removeLine).grid(
            column=0, row=2, sticky=(S, E, W))
        ttk.Button(left, text="Remove All", command=self.removeAll).grid(
            column=1, row=2, sticky=(S, E, W))
        ttk.Button(left, text="Reload", command=self.reloadAll).grid(
            column=0, row=3, sticky=(S, E, W))
        ttk.Button(left, text="Auto Scale", command=self.autoSize).grid(
            column=1, row=3, sticky=(S, E, W))
        ttk.Button(left, text="Add Axis", command=self.addAxis).grid(
            column=0, row=4, sticky=(S, E, W))
        ttk.Button(left, text="Rm Axis", command=self.removeAxis).grid(
            column=1, row=4, sticky=(S, E, W))
        ttk.Button(left, text="Legend", command=self.toggleLegend).grid(
            column=0, row=5, sticky=(S, E, W))
        ttk.Button(left, text="Export PDF", command=self.exportPdf).grid(
            column=1, row=5, sticky=(S, E, W))

        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)
        left.rowconfigure(1, weight=1)

        # --- Right panel: figure, toolbar, readout ---
        right = ttk.Frame(self)
        self.add(right)

        self.fig = Figure(dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.toolbar = NavigationToolbar2Tk(self.canvas, right, pack_toolbar=False)
        self.toolbar.update()

        theme = _get_theme()
        self.readout = Text(right, height=1, font=("Courier", 9),
                            state=DISABLED, bg=theme['panel_bg'],
                            fg=theme['panel_fg'],
                            wrap=NONE, borderwidth=1, relief="sunken",
                            insertbackground='white')
        self.status_var = StringVar(value="")
        self.status = tkinter.Label(right, textvariable=self.status_var,
                                    font=("Courier", 9), anchor=W,
                                    bg=theme['panel_bg'],
                                    fg=theme['panel_fg'])

        self.canvas.get_tk_widget().pack(side=TOP, fill=BOTH, expand=True)
        self.toolbar.pack(side=TOP, fill=X)
        self.readout.pack(side=TOP, fill=X, padx=2, pady=(2, 0))
        self.status.pack(side=BOTTOM, fill=X, padx=2)

        # --- State ---
        self.axes = []
        self._num_axes = 0
        self.axis_index = 0
        self.wave_data = {}
        self._legend_visible = False

        # Cursor state
        self.cursor_a_x = None
        self.cursor_b_x = None
        self._cursor_a_lines = []
        self._cursor_b_lines = []
        self._delta_annotations = []
        self._dragging = None
        self._last_mouse_x = None
        self._last_mouse_y = None

        # Rubber-band zoom state
        self._rubber_band = None
        self._rubber_rect = None
        self._rb_start = None

        # Pan state
        self._panning = False
        self._pan_start = None

        # Zoom history for undo
        self._zoom_history = []

        # Crosshair state
        self._crosshair_enabled = False
        self._crosshair_h_lines = []
        self._crosshair_v_lines = []

        # Dark mode state
        self._dark_mode = True

        # Measurement annotations
        self._measure_annotations = []

        # Overlay tracking
        self._overlay_lines = []

        # Snap-to-edge state
        self._snap_enabled = False

        # Waveform markers (persistent labeled vertical lines)
        self._markers = []  # list of {'x': float, 'label': str, 'lines': [], 'texts': []}

        # Bus display tracking
        self._bus_displays = []

        # Derived waveforms
        self._derived_waves = []

        # Split view state
        self._split_panes = []  # list of {'gs': GridSpec, 'axes': [], 'waves': {}}

        # Waveform style cycling state
        self._style_cycle_index = {}  # tag -> int
        self._fill_patches = {}  # tag -> PolyCollection or None

        # Minor grid state
        self._minor_grid_enabled = False

        # Marker color cycle
        self._marker_colors = ['#E91E63', '#00BCD4', '#8BC34A', '#FF5722',
                                '#673AB7', '#009688', '#FFC107', '#795548']

        # --- Events ---
        self.canvas.mpl_connect('button_press_event', self._on_press)
        self.canvas.mpl_connect('button_release_event', self._on_release)
        self.canvas.mpl_connect('motion_notify_event', self._on_motion)
        self.canvas.mpl_connect('scroll_event', self._on_scroll)
        self.canvas.mpl_connect('key_press_event', self._on_key)

        self.addAxis()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self, wave):
        if wave.tag in self.wave_data:
            return

        idx = self.axis_index
        wave.plot(self.axes[idx])
        self.wave_data[wave.tag] = (wave, idx)

        if idx == 0 and len(self.wave_data) == 1:
            self.axes[0].set_xlabel(wave.xlabel)

        text = "A%d: %s" % (idx, wave.ylabel)
        self.tree.insert('', 'end', wave.tag, text=text, tags=(wave.tag,))
        self.tree.tag_configure(wave.tag, foreground=wave.line.get_color())

        self._create_cursor_lines()
        self.canvas.draw_idle()

    def removeAll(self):
        for tag in list(self.tree.get_children()):
            self._remove_tag(tag)
        self.canvas.draw_idle()

    def removeLine(self):
        tag = self.tree.focus()
        self._remove_tag(tag)
        self.canvas.draw_idle()

    def addAxis(self):
        self._num_axes += 1
        self._rebuild_axes()
        self.axis_index = self._num_axes - 1
        self._update_combo()

    def removeAxis(self):
        if self._num_axes <= 1:
            return
        last = self._num_axes - 1
        tags_to_remove = [t for t, (_, ai) in self.wave_data.items() if ai == last]
        for t in tags_to_remove:
            self._remove_tag(t)
        self._num_axes -= 1
        self.axis_index = min(self.axis_index, self._num_axes - 1)
        self._rebuild_axes()
        self._update_combo()

    def autoSize(self):
        for ax in self.axes:
            ax.relim()
            ax.autoscale_view(True, True, True)
        self.canvas.draw_idle()

    def zoomIn(self):
        self._keyboard_zoom(1.0 / ZOOM_FACTOR)

    def zoomOut(self):
        self._keyboard_zoom(ZOOM_FACTOR)

    def _keyboard_zoom(self, scale):
        self._save_zoom()
        for ax in self.axes:
            xlo, xhi = ax.get_xlim()
            xmid = (xlo + xhi) / 2.0
            ax.set_xlim(xmid - (xmid - xlo) * scale,
                        xmid + (xhi - xmid) * scale)
            ylo, yhi = ax.get_ylim()
            ymid = (ylo + yhi) / 2.0
            ax.set_ylim(ymid - (ymid - ylo) * scale,
                        ymid + (yhi - ymid) * scale)
        self.canvas.draw_idle()

    # --- Independent X/Y zoom ---
    def zoomInX(self):
        self._save_zoom()
        for ax in self.axes:
            xlo, xhi = ax.get_xlim()
            xmid = (xlo + xhi) / 2.0
            s = 1.0 / ZOOM_FACTOR
            ax.set_xlim(xmid - (xmid - xlo) * s, xmid + (xhi - xmid) * s)
        self.canvas.draw_idle()

    def zoomOutX(self):
        self._save_zoom()
        for ax in self.axes:
            xlo, xhi = ax.get_xlim()
            xmid = (xlo + xhi) / 2.0
            s = ZOOM_FACTOR
            ax.set_xlim(xmid - (xmid - xlo) * s, xmid + (xhi - xmid) * s)
        self.canvas.draw_idle()

    def zoomInY(self):
        self._save_zoom()
        for ax in self.axes:
            ylo, yhi = ax.get_ylim()
            ymid = (ylo + yhi) / 2.0
            s = 1.0 / ZOOM_FACTOR
            ax.set_ylim(ymid - (ymid - ylo) * s, ymid + (yhi - ymid) * s)
        self.canvas.draw_idle()

    def zoomOutY(self):
        self._save_zoom()
        for ax in self.axes:
            ylo, yhi = ax.get_ylim()
            ymid = (ylo + yhi) / 2.0
            s = ZOOM_FACTOR
            ax.set_ylim(ymid - (ymid - ylo) * s, ymid + (yhi - ymid) * s)
        self.canvas.draw_idle()

    # --- Zoom to cursor region ---
    def zoomToCursors(self):
        if self.cursor_a_x is not None and self.cursor_b_x is not None:
            self._save_zoom()
            xlo = min(self.cursor_a_x, self.cursor_b_x)
            xhi = max(self.cursor_a_x, self.cursor_b_x)
            margin = (xhi - xlo) * 0.05
            for ax in self.axes:
                ax.set_xlim(xlo - margin, xhi + margin)
                ax.relim()
                ax.autoscale_view(False, False, True)
            self.canvas.draw_idle()

    # --- Pan left/right/up/down ---
    def panLeft(self):
        for ax in self.axes:
            xlo, xhi = ax.get_xlim()
            dx = (xhi - xlo) * PAN_FRACTION
            ax.set_xlim(xlo - dx, xhi - dx)
        self.canvas.draw_idle()

    def panRight(self):
        for ax in self.axes:
            xlo, xhi = ax.get_xlim()
            dx = (xhi - xlo) * PAN_FRACTION
            ax.set_xlim(xlo + dx, xhi + dx)
        self.canvas.draw_idle()

    def panUp(self):
        for ax in self.axes:
            ylo, yhi = ax.get_ylim()
            dy = (yhi - ylo) * PAN_FRACTION
            ax.set_ylim(ylo + dy, yhi + dy)
        self.canvas.draw_idle()

    def panDown(self):
        for ax in self.axes:
            ylo, yhi = ax.get_ylim()
            dy = (yhi - ylo) * PAN_FRACTION
            ax.set_ylim(ylo - dy, yhi - dy)
        self.canvas.draw_idle()

    # --- Zoom history (undo) ---
    def _save_zoom(self):
        state = []
        for ax in self.axes:
            state.append((ax.get_xlim(), ax.get_ylim()))
        self._zoom_history.append(state)
        if len(self._zoom_history) > 20:
            self._zoom_history.pop(0)

    def zoomUndo(self):
        if self._zoom_history:
            state = self._zoom_history.pop()
            for ax, (xlim, ylim) in zip(self.axes, state):
                ax.set_xlim(xlim)
                ax.set_ylim(ylim)
            self.canvas.draw_idle()

    # --- Rubber-band zoom (drag to zoom) ---
    def _start_rubber_band(self, event):
        if event.inaxes is None:
            return
        self._rb_start = (event.xdata, event.ydata, event.inaxes)

    def _update_rubber_band(self, event):
        if self._rb_start is None or event.inaxes is None:
            return
        x0, y0, ax0 = self._rb_start
        if event.inaxes != ax0:
            return
        if self._rubber_rect:
            self._rubber_rect.remove()
        from matplotlib.patches import Rectangle
        w = event.xdata - x0
        h = event.ydata - y0
        self._rubber_rect = ax0.add_patch(
            Rectangle((x0, y0), w, h, fill=False,
                       edgecolor='red', linewidth=1.5, linestyle='--', alpha=0.7))
        self.canvas.draw_idle()

    def _finish_rubber_band(self, event):
        if self._rb_start is None:
            return
        x0, y0, ax0 = self._rb_start
        self._rb_start = None
        if self._rubber_rect:
            self._rubber_rect.remove()
            self._rubber_rect = None
        if event.inaxes != ax0 or event.xdata is None:
            self.canvas.draw_idle()
            return
        x1, y1 = event.xdata, event.ydata
        if abs(x1 - x0) < 1e-15 or abs(y1 - y0) < 1e-15:
            self.canvas.draw_idle()
            return
        self._save_zoom()
        xlo, xhi = sorted([x0, x1])
        ylo, yhi = sorted([y0, y1])
        for ax in self.axes:
            ax.set_xlim(xlo, xhi)
        ax0.set_ylim(ylo, yhi)
        self.canvas.draw_idle()

    def setLineWidth(self, width):
        for tag, (wave, _) in self.wave_data.items():
            if wave.line:
                wave.line.set_linewidth(width)
        self.canvas.draw_idle()

    def setFontSize(self, size):
        for ax in self.axes:
            ax.tick_params(axis='both', labelsize=size)
        self.readout.configure(font=("Courier", size))
        self.status.configure(font=("Courier", size))
        self.canvas.draw_idle()

    def reloadAll(self):
        for tag, (wave, _) in self.wave_data.items():
            wave.reload()
        self.autoSize()

    def clearCursors(self):
        for line in self._cursor_a_lines + self._cursor_b_lines:
            line.remove()
        self._cursor_a_lines.clear()
        self._cursor_b_lines.clear()
        self._clear_delta_annotations()
        self.cursor_a_x = None
        self.cursor_b_x = None
        self._update_readout()
        self.canvas.draw_idle()

    def toggleLegend(self):
        self._legend_visible = not self._legend_visible
        for ax in self.axes:
            legend = ax.get_legend()
            if self._legend_visible:
                ax.legend(loc='best', fontsize=7, framealpha=0.8)
            elif legend:
                legend.remove()
        self.canvas.draw_idle()

    def exportPdf(self):
        filename = tkinter.filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialdir=os.getcwd())
        if filename:
            self.fig.savefig(filename, bbox_inches='tight')

    # ------------------------------------------------------------------
    # Signal math / expression plotting
    # ------------------------------------------------------------------

    def addExpression(self, expr_str):
        """Plot a computed signal from an expression on existing waveform data.

        Supports references like v(name) or i(name) that resolve to loaded
        waveforms, plus operators +, -, *, / and functions abs, max, min.

        Example: "v(out)-v(in)", "abs(v(hd[0]))", "v(a)*v(b)"
        """
        # Build a namespace of all loaded waveform y-data keyed by their
        # signal key (e.g. "v(out)").  Also find common x-axis data.
        ns = {}
        ref_x = None
        ref_xunit = ""
        ref_xlabel = ""
        for tag, (wave, ax_idx) in self.wave_data.items():
            if wave.y is not None:
                safe = wave.key  # keep original for lookup
                ns[safe] = np.real(wave.y).copy()
                if ref_x is None and wave.x is not None:
                    ref_x = np.real(wave.x).copy()
                    ref_xunit = wave.xunit
                    ref_xlabel = wave.xlabel

        if ref_x is None:
            return

        # Replace signal references in the expression with namespace lookups.
        # Match patterns like v(name), i(name), v-name etc.
        eval_expr = expr_str

        # Sort keys longest-first to avoid partial replacement
        sorted_keys = sorted(ns.keys(), key=len, reverse=True)
        local_ns = {}
        for i, key in enumerate(sorted_keys):
            var = "_sig%d" % i
            local_ns[var] = ns[key]
            # Escape the key for regex (handles brackets, parens, etc.)
            eval_expr = eval_expr.replace(key, var)

        # Add safe math functions
        local_ns['abs'] = np.abs
        local_ns['max'] = np.maximum
        local_ns['min'] = np.minimum
        local_ns['np'] = np

        try:
            result = eval(eval_expr, {"__builtins__": {}}, local_ns)
        except Exception as e:
            self.status_var.set("Expression error: %s" % str(e))
            return

        if not isinstance(result, np.ndarray):
            result = np.full_like(ref_x, float(result))

        # Plot on current axis
        idx = self.axis_index
        ax = self.axes[idx]
        label = expr_str
        line, = ax.plot(ref_x, result, label=label, linestyle='-')

        # Create a lightweight object to act like a Wave for the tree / readout
        class _ExprWave:
            pass
        ew = _ExprWave()
        ew.x = ref_x
        ew.y = result
        ew.key = expr_str
        ew.ylabel = expr_str
        ew.xlabel = ref_xlabel
        ew.xunit = ref_xunit
        ew.yunit = ""
        ew.tag = "::expr::" + expr_str
        ew.line = line
        ew.logx = False
        ew.logy = False
        ew.reload = lambda: None

        tag = ew.tag
        self.wave_data[tag] = (ew, idx)
        text = "A%d: %s" % (idx, expr_str)
        self.tree.insert('', 'end', tag, text=text, tags=(tag,))
        self.tree.tag_configure(tag, foreground=line.get_color())

        self._create_cursor_lines()
        self.canvas.draw_idle()
        return ew

    # ------------------------------------------------------------------
    # Eye diagram
    # ------------------------------------------------------------------

    def plotEye(self, wave, period):
        """Fold a periodic signal into an eye diagram.

        Overlays multiple periods of *wave* on a single [0, period] window
        on a new axis.

        Args:
            wave: A Wave object (must have .x and .y arrays).
            period: The period in the same units as wave.x (e.g. seconds).
        """
        if wave.x is None or wave.y is None or period <= 0:
            return

        x = np.real(wave.x)
        y = np.real(wave.y)
        t_start = x[0]
        t_end = x[-1]

        # Add a dedicated axis for the eye diagram
        self.addAxis()
        ax = self.axes[self.axis_index]
        ax.set_title("Eye: %s (T=%.4g)" % (wave.key, period), fontsize=8)
        ax.set_xlabel("Time within period")

        n_periods = int((t_end - t_start) / period)
        if n_periods < 1:
            self.status_var.set("Eye: signal shorter than one period")
            return

        for i in range(n_periods):
            p_start = t_start + i * period
            p_end = p_start + period
            mask = (x >= p_start) & (x < p_end)
            if np.sum(mask) < 2:
                continue
            t_folded = x[mask] - p_start
            ax.plot(t_folded, y[mask], color='#2196F3', alpha=0.15, linewidth=0.8)

        if wave.xunit:
            ax.xaxis.set_major_formatter(EngFormatter(unit=wave.xunit))
        if wave.yunit:
            ax.yaxis.set_major_formatter(EngFormatter(unit=wave.yunit))

        ax.grid(True, alpha=0.3)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # FFT / spectrum
    # ------------------------------------------------------------------

    def plotFFT(self, wave):
        """Compute and display the frequency spectrum of a time-domain signal.

        Plots magnitude in dB vs frequency using numpy.fft.  Creates a new
        axis for the spectrum.

        Args:
            wave: A Wave object with time-domain data (.x in seconds, .y).
        """
        if wave.x is None or wave.y is None:
            return

        x = np.real(wave.x)
        y = np.real(wave.y)
        N = len(y)
        if N < 4:
            return

        dt = np.mean(np.diff(x))
        if dt <= 0:
            return

        # Apply Hann window to reduce spectral leakage
        win = np.hanning(N)
        y_win = y * win

        Y = np.fft.rfft(y_win)
        freqs = np.fft.rfftfreq(N, d=dt)

        # Magnitude in dB (normalised to window energy)
        mag = np.abs(Y) * 2.0 / np.sum(win)
        mag[mag < 1e-30] = 1e-30  # floor to avoid log(0)
        mag_db = 20.0 * np.log10(mag)

        # Plot on a new axis
        self.addAxis()
        ax = self.axes[self.axis_index]
        line, = ax.plot(freqs[1:], mag_db[1:], linewidth=0.9,
                        label="FFT(%s)" % wave.key)
        ax.set_title("FFT: %s" % wave.key, fontsize=8)
        ax.set_xlabel("Frequency")
        ax.set_ylabel("Magnitude (dB)")
        ax.xaxis.set_major_formatter(EngFormatter(unit='Hz'))
        ax.grid(True, alpha=0.3)

        # Store as a pseudo-wave for cursor readout
        class _FFTWave:
            pass
        fw = _FFTWave()
        fw.x = freqs[1:]
        fw.y = mag_db[1:]
        fw.key = "FFT(%s)" % wave.key
        fw.ylabel = fw.key
        fw.xlabel = "Frequency"
        fw.xunit = "Hz"
        fw.yunit = "dB"
        fw.tag = "::fft::" + wave.key
        fw.line = line
        fw.logx = False
        fw.logy = False
        fw.reload = lambda: None

        tag = fw.tag
        self.wave_data[tag] = (fw, self.axis_index)
        text = "A%d: %s" % (self.axis_index, fw.key)
        self.tree.insert('', 'end', tag, text=text, tags=(tag,))
        self.tree.tag_configure(tag, foreground=line.get_color())

        self._create_cursor_lines()
        self.canvas.draw_idle()
        return fw

    # ------------------------------------------------------------------
    # Measurement annotations
    # ------------------------------------------------------------------

    def addMeasure(self, wave, mtype):
        """Compute a measurement on a waveform and annotate the plot.

        Args:
            wave: A Wave object.
            mtype: One of 'rise_time', 'fall_time', 'period', 'frequency',
                   'pk2pk', 'rms', 'average', 'min', 'max', 'overshoot'.

        Returns:
            The computed measurement value, or None on error.
        """
        if wave.x is None or wave.y is None:
            return None

        x = np.real(wave.x)
        y = np.real(wave.y)
        result = None
        unit = wave.yunit

        if mtype == 'min':
            result = float(np.min(y))
        elif mtype == 'max':
            result = float(np.max(y))
        elif mtype == 'pk2pk':
            result = float(np.max(y) - np.min(y))
        elif mtype == 'average':
            result = float(np.mean(y))
        elif mtype == 'rms':
            result = float(np.sqrt(np.mean(y ** 2)))
        elif mtype in ('rise_time', 'fall_time'):
            ymin, ymax = float(np.min(y)), float(np.max(y))
            span = ymax - ymin
            if span <= 0:
                return None
            lo = ymin + 0.1 * span
            hi = ymin + 0.9 * span
            if mtype == 'rise_time':
                crossings_lo = self._find_crossings(x, y, lo, 'rising')
                crossings_hi = self._find_crossings(x, y, hi, 'rising')
                if crossings_lo and crossings_hi:
                    # First rise: time from 10% to 90%
                    t_lo = crossings_lo[0]
                    t_hi = next((t for t in crossings_hi if t > t_lo), None)
                    if t_hi is not None:
                        result = t_hi - t_lo
                        unit = wave.xunit
            else:
                crossings_hi = self._find_crossings(x, y, hi, 'falling')
                crossings_lo = self._find_crossings(x, y, lo, 'falling')
                if crossings_hi and crossings_lo:
                    t_hi = crossings_hi[0]
                    t_lo = next((t for t in crossings_lo if t > t_hi), None)
                    if t_lo is not None:
                        result = t_lo - t_hi
                        unit = wave.xunit
        elif mtype in ('period', 'frequency'):
            ymid = (float(np.min(y)) + float(np.max(y))) / 2.0
            crossings = self._find_crossings(x, y, ymid, 'rising')
            if len(crossings) >= 2:
                periods = np.diff(crossings)
                avg_period = float(np.mean(periods))
                if mtype == 'period':
                    result = avg_period
                    unit = wave.xunit
                else:
                    result = 1.0 / avg_period if avg_period > 0 else None
                    unit = 'Hz'
        elif mtype == 'overshoot':
            ymin, ymax = float(np.min(y)), float(np.max(y))
            yss = float(y[-1])  # steady-state = final value
            if yss != ymin:
                result = (ymax - yss) / abs(yss - ymin) * 100.0
                unit = '%'

        if result is None:
            self.status_var.set("Measure '%s': could not compute" % mtype)
            return None

        # Find which axis this wave is on and annotate
        ax_idx = 0
        for tag, (w, ai) in self.wave_data.items():
            if w is wave:
                ax_idx = ai
                break
        ax = self.axes[min(ax_idx, len(self.axes) - 1)]

        text = "%s(%s) = %s" % (mtype, wave.key, self._eng(result, unit))
        theme = _get_theme()
        ann = ax.annotate(
            text,
            xy=(0.02, 0.95 - 0.06 * len(self._measure_annotations)),
            xycoords='axes fraction',
            fontsize=7, fontfamily='monospace',
            color=theme['panel_fg'],
            bbox=dict(boxstyle='round,pad=0.3',
                      fc=theme['panel_bg'], ec='#666666', alpha=0.9),
            ha='left', va='top')
        self._measure_annotations.append(ann)
        self.canvas.draw_idle()
        self.status_var.set(text)
        return result

    @staticmethod
    def _find_crossings(x, y, threshold, direction='rising'):
        """Find x-values where y crosses threshold."""
        crossings = []
        for i in range(len(y) - 1):
            if direction == 'rising' and y[i] <= threshold < y[i + 1]:
                frac = (threshold - y[i]) / (y[i + 1] - y[i])
                crossings.append(x[i] + frac * (x[i + 1] - x[i]))
            elif direction == 'falling' and y[i] >= threshold > y[i + 1]:
                frac = (y[i] - threshold) / (y[i] - y[i + 1])
                crossings.append(x[i] + frac * (x[i + 1] - x[i]))
        return crossings

    # ------------------------------------------------------------------
    # Grid crosshairs (live mouse-tracking)
    # ------------------------------------------------------------------

    def toggleCrosshair(self):
        """Toggle a live crosshair that follows the mouse across all axes.

        This is distinct from cursors A/B -- it tracks the mouse position
        in real time and draws thin cross-lines at the pointer.
        """
        self._crosshair_enabled = not self._crosshair_enabled
        if not self._crosshair_enabled:
            self._remove_crosshair_lines()
            self.canvas.draw_idle()
        self.status_var.set("Crosshair: %s" % ("ON" if self._crosshair_enabled else "OFF"))

    def _remove_crosshair_lines(self):
        for line in self._crosshair_h_lines + self._crosshair_v_lines:
            try:
                line.remove()
            except ValueError:
                pass
        self._crosshair_h_lines.clear()
        self._crosshair_v_lines.clear()

    def _update_crosshair(self, event):
        """Called from _on_motion when crosshair is enabled."""
        self._remove_crosshair_lines()
        if event.inaxes is None or event.xdata is None:
            self.canvas.draw_idle()
            return

        ch_kwargs = {'color': '#888888', 'linewidth': 0.5, 'alpha': 0.6, 'linestyle': '-'}

        # Vertical line on all axes (shared x)
        for ax in self.axes:
            vl = ax.axvline(event.xdata, **ch_kwargs)
            self._crosshair_v_lines.append(vl)

        # Horizontal line only on the axis the mouse is in
        hl = event.inaxes.axhline(event.ydata, **ch_kwargs)
        self._crosshair_h_lines.append(hl)

        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Multi-cursor delta table (enhanced readout)
    # ------------------------------------------------------------------

    def _update_readout(self):
        self.readout.config(state=NORMAL)
        self.readout.delete('1.0', END)

        if self.cursor_a_x is None and self.cursor_b_x is None:
            self._clear_delta_annotations()
            self.readout.config(state=DISABLED, height=1)
            return

        xunit = self._get_xunit()
        lines = []

        # Header line with cursor positions and delta
        parts = []
        if self.cursor_a_x is not None:
            parts.append("A: %s" % self._eng(self.cursor_a_x, xunit))
        if self.cursor_b_x is not None:
            parts.append("B: %s" % self._eng(self.cursor_b_x, xunit))
        if self.cursor_a_x is not None and self.cursor_b_x is not None:
            dx = self.cursor_b_x - self.cursor_a_x
            parts.append("dX: %s" % self._eng(dx, xunit))
            if dx != 0:
                if xunit == 's':
                    parts.append("(1/dX: %s)" % self._eng(1.0 / abs(dx), 'Hz'))
                else:
                    parts.append("(1/dX: %s)" % self._eng(1.0 / abs(dx)))
        lines.append("  ".join(parts))

        # Full signal table with A, B, delta, % change
        both = (self.cursor_a_x is not None and self.cursor_b_x is not None)
        if both:
            hdr = "  %-22s  %-14s  %-14s  %-14s  %s" % (
                "Signal", "@ A", "@ B", "Delta", "% Change")
            lines.append(hdr)
            lines.append("  " + "-" * 80)

        for tag, (wave, _) in self.wave_data.items():
            yu = wave.yunit
            ya = self._interp_y(wave, self.cursor_a_x)
            yb = self._interp_y(wave, self.cursor_b_x)

            if both and ya is not None and yb is not None:
                delta = yb - ya
                if ya != 0:
                    pct = "%.2f%%" % (delta / abs(ya) * 100.0)
                else:
                    pct = "---"
                row = "  %-22s  %-14s  %-14s  %-14s  %s" % (
                    wave.key,
                    self._eng(ya, yu),
                    self._eng(yb, yu),
                    self._eng(delta, yu),
                    pct)
                lines.append(row)
            else:
                parts = ["  %-22s" % wave.key]
                if ya is not None:
                    parts.append("A: %-14s" % self._eng(ya, yu))
                if yb is not None:
                    parts.append("B: %-14s" % self._eng(yb, yu))
                if ya is not None and yb is not None:
                    parts.append("d: %-14s" % self._eng(yb - ya, yu))
                lines.append("".join(parts))

        self._update_delta_annotations()

        # Auto-measure between cursors (frequency, duty cycle, slew rate)
        auto_lines = self._auto_measure_between_cursors()
        if auto_lines:
            lines.append("  --- auto-measure ---")
            lines.extend(auto_lines)

        self.readout.insert('1.0', "\n".join(lines))
        self.readout.config(state=DISABLED, height=min(len(lines), 12))

    # ------------------------------------------------------------------
    # Waveform comparison overlay
    # ------------------------------------------------------------------

    def overlayWave(self, wave, x_offset=0.0, y_offset=0.0, y_scale=1.0):
        """Plot a shifted/scaled copy of a waveform for comparison.

        Args:
            wave: A Wave object to overlay.
            x_offset: Horizontal shift applied to the x data.
            y_offset: Vertical shift applied after scaling.
            y_scale: Multiplicative scaling of y data.

        Returns:
            The matplotlib Line2D of the overlay.
        """
        if wave.x is None or wave.y is None:
            return None

        x = np.real(wave.x) + x_offset
        y = np.real(wave.y) * y_scale + y_offset

        idx = self.axis_index
        ax = self.axes[idx]

        label = "%s (ov: x%+.3g y*%.3g%+.3g)" % (wave.key, x_offset, y_scale, y_offset)
        line, = ax.plot(x, y, linestyle='--', alpha=0.7, linewidth=1.0, label=label)
        self._overlay_lines.append(line)

        # Register as a pseudo-wave for cursor readout
        class _OverlayWave:
            pass
        ow = _OverlayWave()
        ow.x = x
        ow.y = y
        ow.key = label
        ow.ylabel = label
        ow.xlabel = wave.xlabel
        ow.xunit = wave.xunit
        ow.yunit = wave.yunit
        ow.tag = "::overlay::%s::%.6g::%.6g::%.6g" % (wave.key, x_offset, y_scale, y_offset)
        ow.line = line
        ow.logx = False
        ow.logy = False
        ow.reload = lambda: None

        tag = ow.tag
        self.wave_data[tag] = (ow, idx)
        text = "A%d: %s" % (idx, label)
        self.tree.insert('', 'end', tag, text=text, tags=(tag,))
        self.tree.tag_configure(tag, foreground=line.get_color())

        self._create_cursor_lines()
        self.canvas.draw_idle()
        return line

    # ------------------------------------------------------------------
    # Color theme toggle (dark / light)
    # ------------------------------------------------------------------

    def toggleDarkMode(self):
        """Switch between dark and light color themes."""
        self._dark_mode = not self._dark_mode
        theme_name = 'dark' if self._dark_mode else 'light'
        _set_active_theme(theme_name)
        theme = _get_theme()

        # Update figure and axes colors
        fig_bg = theme['panel_bg']
        fig_fg = theme['panel_fg']
        self.fig.set_facecolor(fig_bg)

        for ax in self.axes:
            ax.set_facecolor(fig_bg)
            ax.tick_params(colors=fig_fg, which='both')
            ax.xaxis.label.set_color(fig_fg)
            ax.yaxis.label.set_color(fig_fg)
            ax.title.set_color(fig_fg)
            for spine in ax.spines.values():
                spine.set_edgecolor(fig_fg)

        # Update cursor line colors
        for line in self._cursor_a_lines:
            line.set_color(theme['cursor_a'])
        for line in self._cursor_b_lines:
            line.set_color(theme['cursor_b'])

        # Update readout and status bar
        self.readout.configure(bg=theme['panel_bg'], fg=theme['panel_fg'])
        self.status.configure(bg=theme['panel_bg'], fg=theme['panel_fg'])

        # Redraw delta annotations with new colors
        self._update_delta_annotations()
        self.canvas.draw_idle()
        self.status_var.set("Theme: %s" % theme_name)

    # ------------------------------------------------------------------
    # 1. Snap-to-edge
    # ------------------------------------------------------------------

    def toggleSnap(self):
        """Toggle snap-to-edge mode for cursor placement."""
        self._snap_enabled = not self._snap_enabled
        self.status_var.set("Snap to edge: %s" % ("ON" if self._snap_enabled else "OFF"))

    def snapToEdge(self, x):
        """Find the nearest rising/falling edge across all waveforms.

        Searches within a window around *x* for the closest zero-crossing
        or threshold crossing (midpoint of each waveform's range).  Returns
        the snapped x position, or *x* unchanged if no edge is found.
        """
        if not self.wave_data:
            return x

        # Determine window width: 2% of the visible x range
        if self.axes:
            xlo, xhi = self.axes[0].get_xlim()
            window = (xhi - xlo) * 0.02
        else:
            window = abs(x) * 0.02 if x != 0 else 1e-12

        best_x = x
        best_dist = float('inf')

        for tag, (wave, _) in self.wave_data.items():
            if wave.x is None or wave.y is None:
                continue
            wx = np.real(wave.x)
            wy = np.real(wave.y)
            if len(wx) < 2:
                continue

            # Threshold = midpoint of waveform range
            ymin, ymax = float(np.min(wy)), float(np.max(wy))
            threshold = (ymin + ymax) / 2.0
            if ymax - ymin < 1e-30:
                continue

            # Search for crossings near x
            mask = (wx >= x - window) & (wx <= x + window)
            indices = np.where(mask)[0]
            if len(indices) < 2:
                continue

            for i in indices[:-1]:
                if i + 1 >= len(wy):
                    break
                y0, y1 = wy[i], wy[i + 1]
                # Check for threshold crossing (rising or falling)
                if (y0 <= threshold < y1) or (y0 >= threshold > y1):
                    # Interpolate crossing position
                    if abs(y1 - y0) > 1e-30:
                        frac = (threshold - y0) / (y1 - y0)
                        cx = wx[i] + frac * (wx[i + 1] - wx[i])
                        dist = abs(cx - x)
                        if dist < best_dist:
                            best_dist = dist
                            best_x = cx

        return best_x

    # ------------------------------------------------------------------
    # 2. Waveform markers (persistent labeled vertical lines)
    # ------------------------------------------------------------------

    def addMarker(self, x, label=""):
        """Place a labeled vertical marker at time *x*.

        Markers are persistent annotations distinct from cursors A/B.
        They appear as thin colored vertical lines with a text label at
        the top of the plot.
        """
        color = self._marker_colors[len(self._markers) % len(self._marker_colors)]
        marker = {'x': x, 'label': label, 'color': color, 'lines': [], 'texts': []}

        for ax in self.axes:
            line = ax.axvline(x, color=color, linewidth=0.8, linestyle='-',
                              alpha=0.7)
            marker['lines'].append(line)

        # Place the label text at the top of the first axis
        if self.axes:
            txt = self.axes[0].annotate(
                label if label else "M%d" % len(self._markers),
                xy=(x, 1.0), xycoords=('data', 'axes fraction'),
                fontsize=7, fontfamily='monospace', color=color,
                ha='center', va='bottom',
                bbox=dict(boxstyle='round,pad=0.2', fc=_get_theme()['panel_bg'],
                          ec=color, alpha=0.85))
            marker['texts'].append(txt)

        self._markers.append(marker)
        self.canvas.draw_idle()
        self.status_var.set("Marker added: %s at %s" % (
            label if label else "M%d" % (len(self._markers) - 1),
            self._eng(x, self._get_xunit())))
        return marker

    def moveMarker(self, index, new_x):
        """Move marker at *index* to a new x position."""
        if index < 0 or index >= len(self._markers):
            return
        marker = self._markers[index]
        marker['x'] = new_x
        for line in marker['lines']:
            line.set_xdata([new_x, new_x])
        for txt in marker['texts']:
            txt.xy = (new_x, 1.0)
        self.canvas.draw_idle()

    def removeMarker(self, index):
        """Remove the marker at *index*."""
        if index < 0 or index >= len(self._markers):
            return
        marker = self._markers.pop(index)
        for line in marker['lines']:
            try:
                line.remove()
            except ValueError:
                pass
        for txt in marker['texts']:
            try:
                txt.remove()
            except ValueError:
                pass
        self.canvas.draw_idle()

    def clearMarkers(self):
        """Remove all markers."""
        while self._markers:
            self.removeMarker(0)

    # ------------------------------------------------------------------
    # 3. Bus/digital display
    # ------------------------------------------------------------------

    def addBusDisplay(self, waves, name="bus", radix=16):
        """Combine single-bit waveforms into a bus value display.

        Takes a list of Wave objects representing individual bits
        (LSB first: waves[0] = bit 0, waves[1] = bit 1, ...).
        Displays the combined value as a stepped waveform with numeric
        text labels at each transition.

        Args:
            waves: List of Wave objects (single-bit, ordered LSB to MSB).
            name: Display name for the bus signal.
            radix: 2 (binary), 10 (decimal), or 16 (hex) for value labels.

        Returns:
            The pseudo-wave object, or None on error.
        """
        if not waves:
            return None

        # Find the common x-axis (union of all x breakpoints)
        all_x = set()
        for w in waves:
            if w.x is not None:
                all_x.update(np.real(w.x).tolist())
        if not all_x:
            return None

        x_common = np.array(sorted(all_x))
        n_bits = len(waves)

        # Interpolate each bit onto the common x grid, threshold at midpoint
        bit_arrays = []
        for w in waves:
            if w.x is None or w.y is None:
                bit_arrays.append(np.zeros(len(x_common), dtype=int))
                continue
            wx = np.real(w.x)
            wy = np.real(w.y)
            interp_y = np.interp(x_common, wx, wy)
            threshold = (float(np.min(wy)) + float(np.max(wy))) / 2.0
            bit_arrays.append((interp_y > threshold).astype(int))

        # Compute bus value at each x point
        bus_values = np.zeros(len(x_common), dtype=int)
        for bit_idx, bits in enumerate(bit_arrays):
            bus_values += bits * (1 << bit_idx)

        # Build a stepped waveform (value as y)
        max_val = (1 << n_bits) - 1
        y_norm = bus_values.astype(float)

        # Plot on current axis
        idx = self.axis_index
        ax = self.axes[idx]
        line, = ax.step(x_common, y_norm, where='post', linewidth=1.2,
                        label=name)

        # Add text labels at transitions
        text_annotations = []
        prev_val = None
        for i, val in enumerate(bus_values):
            if val != prev_val:
                if radix == 16:
                    fmt = "0x%X" if max_val <= 0xFF else "0x%0*X" % (
                        (n_bits + 3) // 4, val)
                    lbl = ("0x%0*X" % ((n_bits + 3) // 4, val))
                elif radix == 2:
                    lbl = format(val, '0%db' % n_bits)
                else:
                    lbl = str(val)

                txt = ax.annotate(
                    lbl, xy=(x_common[i], val),
                    fontsize=6, fontfamily='monospace',
                    color=line.get_color(), alpha=0.9,
                    ha='left', va='bottom',
                    xytext=(2, 2), textcoords='offset points')
                text_annotations.append(txt)
                prev_val = val

        # Create pseudo-wave for tree/cursor readout
        class _BusWave:
            pass
        bw = _BusWave()
        bw.x = x_common
        bw.y = y_norm
        bw.key = name
        bw.ylabel = name
        bw.xlabel = waves[0].xlabel if hasattr(waves[0], 'xlabel') else ""
        bw.xunit = waves[0].xunit if hasattr(waves[0], 'xunit') else ""
        bw.yunit = ""
        bw.tag = "::bus::" + name
        bw.line = line
        bw.logx = False
        bw.logy = False
        bw.reload = lambda: None

        tag = bw.tag
        self.wave_data[tag] = (bw, idx)
        text = "A%d: %s [%d-bit bus]" % (idx, name, n_bits)
        self.tree.insert('', 'end', tag, text=text, tags=(tag,))
        self.tree.tag_configure(tag, foreground=line.get_color())

        self._bus_displays.append({
            'wave': bw, 'text_annotations': text_annotations,
            'bit_waves': waves, 'radix': radix})

        self._create_cursor_lines()
        self.canvas.draw_idle()
        return bw

    # ------------------------------------------------------------------
    # 4. Waveform math on-the-fly (derived waveforms)
    # ------------------------------------------------------------------

    def addDerivedWave(self, wave, operation):
        """Compute a derived signal from an existing waveform.

        Args:
            wave: A Wave object with .x and .y arrays.
            operation: One of 'derivative', 'integral', 'abs', 'envelope',
                       'moving_avg'.

        Returns:
            The pseudo-wave object, or None on error.
        """
        if wave.x is None or wave.y is None:
            return None

        x = np.real(wave.x)
        y = np.real(wave.y)
        yunit = wave.yunit if hasattr(wave, 'yunit') else ""
        xunit = wave.xunit if hasattr(wave, 'xunit') else ""
        derived_yunit = yunit

        if operation == 'derivative':
            dy = np.gradient(y, x)
            derived_y = dy
            label = "d(%s)/dt" % wave.key
            if yunit and xunit:
                derived_yunit = "%s/%s" % (yunit, xunit)
            elif yunit:
                derived_yunit = yunit + "/s"

        elif operation == 'integral':
            from scipy import integrate
            derived_y = integrate.cumulative_trapezoid(y, x, initial=0.0)
            label = "int(%s)" % wave.key
            if yunit and xunit:
                derived_yunit = "%s*%s" % (yunit, xunit)

        elif operation == 'abs':
            derived_y = np.abs(y)
            label = "|%s|" % wave.key

        elif operation == 'envelope':
            # Upper envelope via Hilbert transform
            from scipy.signal import hilbert
            analytic = hilbert(y)
            derived_y = np.abs(analytic)
            label = "env(%s)" % wave.key

        elif operation == 'moving_avg':
            # Moving average with window = 1% of total samples, min 3
            win = max(3, len(y) // 100)
            kernel = np.ones(win) / win
            derived_y = np.convolve(y, kernel, mode='same')
            label = "mavg(%s)" % wave.key

        else:
            self.status_var.set("Unknown operation: %s" % operation)
            return None

        # Plot on current axis
        idx = self.axis_index
        ax = self.axes[idx]
        line, = ax.plot(x, derived_y, linewidth=1.0, linestyle='--',
                        label=label)

        class _DerivedWave:
            pass
        dw = _DerivedWave()
        dw.x = x
        dw.y = derived_y
        dw.key = label
        dw.ylabel = label
        dw.xlabel = wave.xlabel if hasattr(wave, 'xlabel') else ""
        dw.xunit = xunit
        dw.yunit = derived_yunit
        dw.tag = "::derived::" + label
        dw.line = line
        dw.logx = False
        dw.logy = False
        dw.reload = lambda: None

        tag = dw.tag
        self.wave_data[tag] = (dw, idx)
        text = "A%d: %s" % (idx, label)
        self.tree.insert('', 'end', tag, text=text, tags=(tag,))
        self.tree.tag_configure(tag, foreground=line.get_color())

        self._derived_waves.append(dw)
        self._create_cursor_lines()
        self.canvas.draw_idle()
        self.status_var.set("Derived: %s" % label)
        return dw

    # ------------------------------------------------------------------
    # 5. Auto-measure between cursors
    # ------------------------------------------------------------------

    def _auto_measure_between_cursors(self):
        """Compute frequency, duty cycle, and slew rate between cursors.

        Called automatically when both cursors are placed. Results are
        appended to the readout text.
        """
        if self.cursor_a_x is None or self.cursor_b_x is None:
            return []

        xa = min(self.cursor_a_x, self.cursor_b_x)
        xb = max(self.cursor_a_x, self.cursor_b_x)
        dx = xb - xa
        lines = []

        if dx <= 0:
            return lines

        xunit = self._get_xunit()

        # Frequency = 1/period between cursors
        freq = 1.0 / dx
        freq_unit = 'Hz' if xunit == 's' else '1/' + xunit if xunit else ''
        lines.append("  Freq(A-B): %s" % self._eng(freq, freq_unit))

        for tag, (wave, _) in self.wave_data.items():
            if wave.x is None or wave.y is None:
                continue
            wx = np.real(wave.x)
            wy = np.real(wave.y)

            # Restrict to cursor region
            mask = (wx >= xa) & (wx <= xb)
            if np.sum(mask) < 4:
                continue
            rx = wx[mask]
            ry = wy[mask]

            ymin, ymax = float(np.min(ry)), float(np.max(ry))
            threshold = (ymin + ymax) / 2.0
            span = ymax - ymin

            if span < 1e-30:
                continue

            # Duty cycle: fraction of time signal is above threshold
            above = ry > threshold
            duty = float(np.sum(above)) / float(len(above)) * 100.0
            lines.append("  Duty(%s): %.1f%%" % (wave.key, duty))

            # Slew rate at cursor A and cursor B positions
            # Find the nearest index for each cursor in the full array
            for cursor_label, cx in [('A', self.cursor_a_x), ('B', self.cursor_b_x)]:
                ci = np.searchsorted(wx, cx)
                ci = min(ci, len(wx) - 2)
                ci = max(ci, 1)
                # Central difference for dV/dt
                dt_local = wx[ci + 1] - wx[ci - 1]
                if abs(dt_local) > 1e-30:
                    slew = (wy[ci + 1] - wy[ci - 1]) / dt_local
                    yu = wave.yunit if hasattr(wave, 'yunit') else ""
                    slew_unit = "%s/%s" % (yu, xunit) if yu and xunit else ""
                    lines.append("  Slew(%s@%s): %s" % (
                        wave.key, cursor_label, self._eng(slew, slew_unit)))

        return lines

    # ------------------------------------------------------------------
    # 6. Split view (horizontal/vertical panes with shared X-axis)
    # ------------------------------------------------------------------

    def splitHorizontal(self):
        """Split the plot area horizontally (side by side panes).

        Creates two independent plot panes sharing the X-axis, laid out
        left-to-right using matplotlib GridSpec.  Each pane gets its own
        Y-axis.  Existing waveforms stay in the left pane.
        """
        self._do_split(ncols=2, nrows=1)

    def splitVertical(self):
        """Split the plot area vertically (stacked panes).

        Creates two independent plot panes sharing the X-axis, laid out
        top-to-bottom using matplotlib GridSpec.  Each pane gets its own
        Y-axis.  Existing waveforms stay in the top pane.
        """
        self._do_split(ncols=1, nrows=2)

    def _do_split(self, ncols, nrows):
        """Internal: split the figure into *nrows* x *ncols* panes."""
        # Save current view limits
        saved_xlim = self.axes[0].get_xlim() if self.axes else None

        # Clear figure and rebuild with GridSpec
        self.fig.clear()
        gs = mpl_gridspec.GridSpec(nrows, ncols, figure=self.fig,
                                    hspace=0.15, wspace=0.25)

        # Create axes for each cell
        new_axes = []
        first_ax = None
        for r in range(nrows):
            for c in range(ncols):
                if first_ax is None:
                    ax = self.fig.add_subplot(gs[r, c])
                    first_ax = ax
                else:
                    ax = self.fig.add_subplot(gs[r, c], sharex=first_ax)
                ax.grid(True, alpha=0.3)
                ax.tick_params(axis='both', which='major', labelsize=8)
                new_axes.append(ax)

        # Re-plot existing waveforms on the first (primary) pane
        primary_ax = new_axes[0]
        for tag, (wave, ax_idx) in list(self.wave_data.items()):
            wave.line = None
            wave.plot(primary_ax)
            self.wave_data[tag] = (wave, 0)
            if self.tree.exists(tag) and wave.line:
                self.tree.tag_configure(tag, foreground=wave.line.get_color())

        # Restore x-axis
        if saved_xlim:
            primary_ax.set_xlim(saved_xlim)

        # Update axes list: the split creates additional axes that can
        # be targeted by setting axis_index after this call.
        old_count = self._num_axes
        self.axes = new_axes
        self._num_axes = len(new_axes)
        self.axis_index = 0

        # Rebuild cursors
        self._cursor_a_lines.clear()
        self._cursor_b_lines.clear()
        self._delta_annotations.clear()
        self._create_cursor_lines()
        self._update_delta_annotations()

        # Rebuild markers
        for marker in self._markers:
            marker['lines'] = []
            for ax in self.axes:
                line = ax.axvline(marker['x'], color=marker['color'],
                                  linewidth=0.8, linestyle='-', alpha=0.7)
                marker['lines'].append(line)

        self._update_combo()

        # Apply minor grid if enabled
        if self._minor_grid_enabled:
            self._apply_minor_grid()

        self.canvas.draw_idle()
        self.status_var.set("Split: %dx%d panes" % (nrows, ncols))

    # ------------------------------------------------------------------
    # 7. Waveform style cycling
    # ------------------------------------------------------------------

    _LINE_STYLES = ['-', '--', ':', '-.']
    _COLOR_CYCLE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    def cycleLineStyle(self):
        """Cycle the selected waveform's line style and color.

        Cycles through: solid, dashed, dotted, dash-dot.
        Also advances the color from a preset palette.
        Operates on the waveform currently selected in the tree view.
        """
        tag = self.tree.focus()
        if not tag or tag not in self.wave_data:
            self.status_var.set("Select a waveform first")
            return

        wave, _ = self.wave_data[tag]
        if wave.line is None:
            return

        idx = self._style_cycle_index.get(tag, 0) + 1
        self._style_cycle_index[tag] = idx

        style = self._LINE_STYLES[idx % len(self._LINE_STYLES)]
        color = self._COLOR_CYCLE[idx % len(self._COLOR_CYCLE)]

        wave.line.set_linestyle(style)
        wave.line.set_color(color)

        # Update tree color
        if self.tree.exists(tag):
            self.tree.tag_configure(tag, foreground=color)

        self.canvas.draw_idle()
        self.status_var.set("Style: %s  Color: %s" % (style, color))

    def toggleFill(self):
        """Toggle semi-transparent fill under the selected waveform.

        Operates on the waveform currently selected in the tree view.
        """
        tag = self.tree.focus()
        if not tag or tag not in self.wave_data:
            self.status_var.set("Select a waveform first")
            return

        wave, ax_idx = self.wave_data[tag]
        if wave.line is None or wave.x is None or wave.y is None:
            return

        ax = self.axes[min(ax_idx, len(self.axes) - 1)]

        if tag in self._fill_patches and self._fill_patches[tag] is not None:
            # Remove existing fill
            try:
                self._fill_patches[tag].remove()
            except ValueError:
                pass
            self._fill_patches[tag] = None
            self.status_var.set("Fill removed")
        else:
            # Add fill
            color = wave.line.get_color()
            fill = ax.fill_between(np.real(wave.x), np.real(wave.y),
                                   alpha=0.15, color=color)
            self._fill_patches[tag] = fill
            self.status_var.set("Fill added")

        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # 8. Persistent grid with major/minor
    # ------------------------------------------------------------------

    def toggleMinorGrid(self):
        """Toggle minor gridlines on all axes.

        Major gridlines: solid, alpha=0.3.
        Minor gridlines: dotted, alpha=0.1.
        """
        self._minor_grid_enabled = not self._minor_grid_enabled
        self._apply_minor_grid()
        self.canvas.draw_idle()
        self.status_var.set("Minor grid: %s" % (
            "ON" if self._minor_grid_enabled else "OFF"))

    def _apply_minor_grid(self):
        """Apply or remove minor grid on all axes based on state."""
        for ax in self.axes:
            # Always ensure major grid is consistent
            ax.grid(True, which='major', linestyle='-', alpha=0.3)

            if self._minor_grid_enabled:
                ax.minorticks_on()
                ax.xaxis.set_minor_locator(AutoMinorLocator())
                ax.yaxis.set_minor_locator(AutoMinorLocator())
                ax.grid(True, which='minor', linestyle=':', alpha=0.1)
            else:
                ax.grid(False, which='minor')
                ax.minorticks_off()

    # ------------------------------------------------------------------
    # Axis management
    # ------------------------------------------------------------------

    def _rebuild_axes(self):
        saved_xlim = self.axes[0].get_xlim() if self.axes else None
        saved_ylims = {i: ax.get_ylim() for i, ax in enumerate(self.axes)}

        self.fig.clear()
        n = self._num_axes

        if n == 1:
            self.axes = [self.fig.add_subplot(1, 1, 1)]
        else:
            axs = self.fig.subplots(n, 1, sharex=True)
            self.axes = list(axs)
            self.fig.subplots_adjust(hspace=0.08)

        for ax in self.axes:
            ax.grid(True, alpha=0.3)
            ax.tick_params(axis='both', which='major', labelsize=8)
        if n > 1:
            for ax in self.axes[:-1]:
                ax.tick_params(labelbottom=False)

        for tag, (wave, ax_idx) in list(self.wave_data.items()):
            ax_idx = min(ax_idx, n - 1)
            wave.line = None
            wave.plot(self.axes[ax_idx])
            self.wave_data[tag] = (wave, ax_idx)
            if self.tree.exists(tag) and wave.line:
                self.tree.tag_configure(tag, foreground=wave.line.get_color())

        if saved_xlim and self.axes:
            self.axes[0].set_xlim(saved_xlim)
        for i, ax in enumerate(self.axes):
            if i in saved_ylims:
                ax.set_ylim(saved_ylims[i])

        self._cursor_a_lines.clear()
        self._cursor_b_lines.clear()
        self._delta_annotations.clear()
        self._create_cursor_lines()
        self._update_delta_annotations()

        # Rebuild markers on new axes
        for marker in self._markers:
            marker['lines'] = []
            marker['texts'] = []
            for ax in self.axes:
                line = ax.axvline(marker['x'], color=marker['color'],
                                  linewidth=0.8, linestyle='-', alpha=0.7)
                marker['lines'].append(line)
            if self.axes:
                txt = self.axes[0].annotate(
                    marker['label'] if marker['label'] else "M",
                    xy=(marker['x'], 1.0), xycoords=('data', 'axes fraction'),
                    fontsize=7, fontfamily='monospace', color=marker['color'],
                    ha='center', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.2',
                              fc=_get_theme()['panel_bg'],
                              ec=marker['color'], alpha=0.85))
                marker['texts'].append(txt)

        # Re-apply minor grid if enabled
        if self._minor_grid_enabled:
            self._apply_minor_grid()

        self.canvas.draw_idle()

    def _update_combo(self):
        labels = ["Axes %d" % i for i in range(self._num_axes)]
        self.combo['values'] = labels
        self.combo.current(self.axis_index)

    def _set_axis_index(self, event):
        self.axis_index = self.combo.current()

    def _remove_tag(self, tag):
        if not tag or not self.tree.exists(tag):
            return
        self.tree.delete(tag)
        if tag in self.wave_data:
            wave, _ = self.wave_data[tag]
            if wave.line:
                wave.line.remove()
                wave.line = None
            del self.wave_data[tag]

    # ------------------------------------------------------------------
    # Cursor system
    # ------------------------------------------------------------------

    def _create_cursor_lines(self):
        existing_a = len(self._cursor_a_lines)
        existing_b = len(self._cursor_b_lines)
        for i, ax in enumerate(self.axes):
            if self.cursor_a_x is not None and i >= existing_a:
                line = ax.axvline(self.cursor_a_x,
                                  color=_get_theme()['cursor_a'],
                                  **CURSOR_KWARGS)
                self._cursor_a_lines.append(line)
            if self.cursor_b_x is not None and i >= existing_b:
                line = ax.axvline(self.cursor_b_x,
                                  color=_get_theme()['cursor_b'],
                                  **CURSOR_KWARGS)
                self._cursor_b_lines.append(line)

    def _set_cursor(self, which, x):
        if self._snap_enabled:
            x = self.snapToEdge(x)
        theme = _get_theme()
        if which == 'a':
            self.cursor_a_x = x
            if not self._cursor_a_lines:
                for ax in self.axes:
                    line = ax.axvline(x, color=theme['cursor_a'],
                                     **CURSOR_KWARGS)
                    self._cursor_a_lines.append(line)
            else:
                for line in self._cursor_a_lines:
                    line.set_xdata([x, x])
        else:
            self.cursor_b_x = x
            if not self._cursor_b_lines:
                for ax in self.axes:
                    line = ax.axvline(x, color=theme['cursor_b'],
                                     **CURSOR_KWARGS)
                    self._cursor_b_lines.append(line)
            else:
                for line in self._cursor_b_lines:
                    line.set_xdata([x, x])
        self._update_readout()
        self.canvas.draw_idle()

    def _near_cursor(self, event, cursor_x):
        if cursor_x is None or event.inaxes is None:
            return False
        disp_cursor, _ = event.inaxes.transData.transform((cursor_x, 0))
        return abs(event.x - disp_cursor) < DRAG_TOLERANCE_PX

    def _interp_y(self, wave, x):
        if wave.x is None or x is None:
            return None
        try:
            return float(np.interp(x, np.real(wave.x), np.real(wave.y)))
        except Exception:
            return None

    def _get_xunit(self):
        for wave, _ in self.wave_data.values():
            if wave.xunit:
                return wave.xunit
        return ""

    @staticmethod
    def _eng(value, unit=""):
        return EngFormatter(unit=unit)(value)

    def _clear_delta_annotations(self):
        for ann in self._delta_annotations:
            ann.remove()
        self._delta_annotations.clear()

    def _update_delta_annotations(self):
        self._clear_delta_annotations()
        if self.cursor_a_x is None or self.cursor_b_x is None:
            return

        xunit = self._get_xunit()
        dx = self.cursor_b_x - self.cursor_a_x
        mid_x = (self.cursor_a_x + self.cursor_b_x) / 2.0

        waves_per_axis = {}
        for tag, (wave, ax_idx) in self.wave_data.items():
            waves_per_axis.setdefault(ax_idx, []).append(wave)

        for ax_idx, ax in enumerate(self.axes):
            text_parts = ["ΔX: %s" % self._eng(dx, xunit)]
            if dx != 0 and xunit == 's':
                text_parts[0] += "  (1/ΔX: %s)" % self._eng(1.0 / abs(dx), 'Hz')

            for wave in waves_per_axis.get(ax_idx, []):
                ya = self._interp_y(wave, self.cursor_a_x)
                yb = self._interp_y(wave, self.cursor_b_x)
                if ya is not None and yb is not None:
                    text_parts.append("Δ%s: %s" % (wave.key, self._eng(yb - ya, wave.yunit)))

            theme = _get_theme()
            ann = ax.annotate(
                "\n".join(text_parts),
                xy=(mid_x, 0.97), xycoords=('data', 'axes fraction'),
                fontsize=7, fontfamily='monospace',
                color=theme['panel_fg'],
                bbox=dict(boxstyle='round,pad=0.3',
                          fc=theme['panel_bg'], ec='#666666', alpha=0.85),
                ha='center', va='top')
            self._delta_annotations.append(ann)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_press(self, event):
        if self.toolbar.mode != '' or event.inaxes is None:
            return
        if event.xdata is None:
            return

        # Middle-click: rubber-band zoom
        if event.button == 2:
            self._start_rubber_band(event)
            return

        # Ctrl+left-click: pan start
        if event.button == 1 and event.key == 'control':
            self._panning = True
            self._pan_start = (event.xdata, event.ydata)
            return

        if self._near_cursor(event, self.cursor_a_x):
            self._dragging = 'a'
            return
        if self._near_cursor(event, self.cursor_b_x):
            self._dragging = 'b'
            return

        if event.button == 1:
            if event.key == 'shift':
                self._set_cursor('b', event.xdata)
            else:
                self._set_cursor('a', event.xdata)
        elif event.button == 3:
            self._set_cursor('b', event.xdata)

    def _on_release(self, event):
        if self._rb_start is not None:
            self._finish_rubber_band(event)
        self._dragging = None
        self._panning = False
        self._pan_start = None

    def _on_motion(self, event):
        if event.inaxes is not None and event.xdata is not None:
            self._last_mouse_x = event.xdata
            self._last_mouse_y = event.ydata
            xu = self._get_xunit()
            self.status_var.set("x: %s   y: %.6g" % (self._eng(event.xdata, xu),
                                                       event.ydata))
        else:
            self.status_var.set("")

        if self._dragging and event.xdata is not None:
            self._set_cursor(self._dragging, event.xdata)
        elif self._rb_start is not None:
            self._update_rubber_band(event)
        elif self._panning and self._pan_start and event.xdata is not None:
            dx = event.xdata - self._pan_start[0]
            dy = event.ydata - self._pan_start[1]
            for ax in self.axes:
                xlo, xhi = ax.get_xlim()
                ax.set_xlim(xlo - dx, xhi - dx)
            if event.inaxes:
                ylo, yhi = event.inaxes.get_ylim()
                event.inaxes.set_ylim(ylo - dy, yhi - dy)
            self.canvas.draw_idle()

        if self._crosshair_enabled:
            self._update_crosshair(event)

    def _on_key(self, event):
        if event.key == 'a' and event.xdata is not None:
            self._set_cursor('a', event.xdata)
        elif event.key == 'b' and event.xdata is not None:
            self._set_cursor('b', event.xdata)
        elif event.key == 'x':
            self.zoomInX()
        elif event.key == 'X':
            self.zoomOutX()
        elif event.key == 'y':
            self.zoomInY()
        elif event.key == 'Y':
            self.zoomOutY()
        elif event.key == 'u':
            self.zoomUndo()
        elif event.key == 'c':
            self.zoomToCursors()
        elif event.key == 'left':
            self.panLeft()
        elif event.key == 'right':
            self.panRight()
        elif event.key == 'up':
            self.panUp()
        elif event.key == 'down':
            self.panDown()
        elif event.key == 'h':
            self.toggleCrosshair()
        elif event.key == 'd':
            self.toggleDarkMode()
        elif event.key == 's':
            self.toggleSnap()
        elif event.key == 'g':
            self.toggleMinorGrid()
        elif event.key == 'f':
            self.toggleFill()
        elif event.key == 'l':
            self.cycleLineStyle()

    def placeCursorA(self):
        if self._last_mouse_x is not None:
            self._set_cursor('a', self._last_mouse_x)

    def placeCursorB(self):
        if self._last_mouse_x is not None:
            self._set_cursor('b', self._last_mouse_x)

    def _on_scroll(self, event):
        ax = event.inaxes
        if ax is None or event.xdata is None:
            return

        if event.button == 'up':
            scale = 1.0 / ZOOM_FACTOR
        elif event.button == 'down':
            scale = ZOOM_FACTOR
        else:
            return

        if event.key == 'shift':
            # Zoom y-axis
            ydata = event.ydata
            ylo, yhi = ax.get_ylim()
            new_lo = ydata - (ydata - ylo) * scale
            new_hi = ydata + (yhi - ydata) * scale
            ax.set_ylim(new_lo, new_hi)
        else:
            # Zoom x-axis (affects all shared axes)
            xdata = event.xdata
            xlo, xhi = ax.get_xlim()
            new_lo = xdata - (xdata - xlo) * scale
            new_hi = xdata + (xhi - xdata) * scale
            ax.set_xlim(new_lo, new_hi)

        self.canvas.draw_idle()


class WaveGraph(ttk.Frame):

    def __init__(self, master=None, **kw):
        super().__init__(master, width=800, borderwidth=1, relief="raised", **kw)

        self.nb = ttk.Notebook(self, width=800)
        self.nb.grid(column=0, row=0, sticky=(N, S, E, W))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.index = 0
        self.addPlot()

    def addPlot(self):
        w = WavePlot(self.nb)
        self.nb.add(w, text="Plot %d" % self.index)
        self.index += 1

    def reloadPlots(self):
        for t in self.nb.tabs():
            self.nb.nametowidget(t).reloadAll()

    def show(self, wave):
        w = self.nb.nametowidget(self.nb.select())
        if w is not None:
            w.show(wave)

    def getCurrentPlot(self):
        tab = self.nb.select()
        if tab:
            return self.nb.nametowidget(tab)
        return None
