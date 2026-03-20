#!/usr/bin/env python3

import cicsim as cs
import os
import json
import numpy as np
import pandas as pd
from matplotlib.ticker import EngFormatter

#- Model for wavefiles

class Wave():

    def __init__(self,wfile,key,xaxis):
        self.xaxis = xaxis
        self.wfile = wfile
        self.x = None
        self.y = None
        self.xlabel = "Samples"
        self.key = key
        self.ylabel = key + f" ({wfile.name})"
        self.logx = False
        self.logy = False
        self.xunit = ""
        self.yunit = self._infer_yunit(key)
        self.tag = wfile.getTag(self.key)
        self.line = None
        self.reload()

    @staticmethod
    def _infer_yunit(key):
        kl = key.lower()
        if kl.startswith("v(") or kl.startswith("v-"):
            return "V"
        if kl.startswith("i(") or kl.startswith("i-"):
            return "A"
        return ""

    def deleteLine(self):
        if(self.line):
            self.line.remove()
            self.line = None

    def plot(self,ax):
        x = np.real(self.x) if self.x is not None else None
        y = np.real(self.y) if self.y is not None else self.y
        if(x is not None):
            if(not self.logx and not self.logy):
                self.line, = ax.plot(x,y,label=self.ylabel)
            elif(self.logx and not self.logy):
                self.line, = ax.semilogx(x,y,label=self.ylabel)
            elif(not self.logx and self.logy):
                self.line, = ax.semilogy(x,y,label=self.ylabel)
            elif(self.logx and self.logy):
                self.line, = ax.loglog(x,y,label=self.ylabel)
        else:
            self.line, = ax.plot(y,label=self.ylabel)

        if self.xunit:
            ax.xaxis.set_major_formatter(EngFormatter(unit=self.xunit))
        if self.yunit:
            ax.yaxis.set_major_formatter(EngFormatter(unit=self.yunit))

    def reload(self):
        self.wfile.reload()

        keys = self.wfile.df.columns

        if("time" in keys):
            self.x = self.wfile.df["time"].to_numpy()
            self.xlabel = "Time"
            self.xunit = "s"
            self.y = self.wfile.df[self.key].to_numpy()
        elif("frequency" in keys):
            self.x = self.wfile.df["frequency"].to_numpy()
            self.xlabel = "Frequency"
            self.xunit = "Hz"
            self.logx = True
            self.y = self.wfile.df[self.key].to_numpy()
        elif("v(v-sweep)" in keys):
            self.x = self.wfile.df["v(v-sweep)"].to_numpy()
            self.xlabel = "Voltage"
            self.xunit = "V"
            self.y = self.wfile.df[self.key].to_numpy()
        elif("i(i-sweep)" in keys):
            self.x = self.wfile.df["i(i-sweep)"].to_numpy()
            self.xlabel = "Current"
            self.xunit = "A"
            self.y = self.wfile.df[self.key].to_numpy()
        elif("temp-sweep" in keys):
            self.x = self.wfile.df["temp-sweep"].to_numpy()
            self.xlabel = "Temperature"
            self.xunit = "°C"
            self.y = self.wfile.df[self.key].to_numpy()
        elif(self.xaxis in keys):
            self.x = self.wfile.df[self.xaxis].to_numpy()
            self.xlabel = " "
            self.xunit = ""
            self.y = self.wfile.df[self.key].to_numpy()

        if(self.line):
            if(self.x is not None):
                self.line.set_xdata(self.x)
            self.line.set_ydata(self.y)
        pass


class MathWave():
    """A computed waveform that behaves like a first-class Wave.

    Stores arbitrary x/y data produced from an expression, FFT, derivative,
    or any other computation.  Can be displayed, measured, and exported
    exactly like raw-file waves.
    """

    def __init__(self, x, y, name, xunit="", yunit="", xlabel="", ylabel=None,
                 logx=False, logy=False, source_tag=None):
        self.x = np.asarray(x, dtype=float) if x is not None else None
        self.y = np.asarray(y, dtype=float) if y is not None else None
        self.key = name
        self.ylabel = ylabel or name
        self.xlabel = xlabel
        self.xunit = xunit
        self.yunit = yunit
        self.logx = logx
        self.logy = logy
        self.tag = "::math::" + name
        self.line = None
        self._source_tag = source_tag

    def deleteLine(self):
        if self.line:
            self.line.remove()
            self.line = None

    def plot(self, ax):
        xp = np.real(self.x) if self.x is not None else None
        yp = np.real(self.y) if self.y is not None else self.y
        if xp is not None:
            if not self.logx and not self.logy:
                self.line, = ax.plot(xp, yp, label=self.ylabel)
            elif self.logx and not self.logy:
                self.line, = ax.semilogx(xp, yp, label=self.ylabel)
            elif not self.logx and self.logy:
                self.line, = ax.semilogy(xp, yp, label=self.ylabel)
            else:
                self.line, = ax.loglog(xp, yp, label=self.ylabel)
        else:
            self.line, = ax.plot(yp, label=self.ylabel)

        if self.xunit:
            ax.xaxis.set_major_formatter(EngFormatter(unit=self.xunit))
        if self.yunit:
            ax.yaxis.set_major_formatter(EngFormatter(unit=self.yunit))

    def reload(self):
        if self.line and self.y is not None:
            if self.x is not None:
                self.line.set_xdata(np.real(self.x))
            self.line.set_ydata(np.real(self.y))

    @staticmethod
    def fromExpression(expr_str, waves_dict, name=None):
        """Create a MathWave by evaluating *expr_str* over loaded waves.

        *waves_dict* maps signal key (e.g. ``v(out)``) to a Wave or
        MathWave object.  Returns a MathWave or raises on error.
        """
        ns = {}
        ref_x = None
        ref_xunit = ""
        ref_xlabel = ""
        for key, wave in waves_dict.items():
            if wave.y is not None:
                ns[key] = np.real(wave.y).copy()
                if ref_x is None and wave.x is not None:
                    ref_x = np.real(wave.x).copy()
                    ref_xunit = wave.xunit
                    ref_xlabel = wave.xlabel
        if ref_x is None:
            raise ValueError("No x-axis data available for expression")

        eval_expr = expr_str
        sorted_keys = sorted(ns.keys(), key=len, reverse=True)
        local_ns = {}
        for i, key in enumerate(sorted_keys):
            var = "_sig%d" % i
            local_ns[var] = ns[key]
            eval_expr = eval_expr.replace(key, var)

        local_ns['abs'] = np.abs
        local_ns['max'] = np.maximum
        local_ns['min'] = np.minimum
        local_ns['np'] = np

        result = eval(eval_expr, {"__builtins__": {}}, local_ns)
        if not isinstance(result, np.ndarray):
            result = np.full_like(ref_x, float(result))

        label = name or expr_str
        return MathWave(ref_x, result, label, xunit=ref_xunit,
                        xlabel=ref_xlabel)

    @staticmethod
    def fromDerivative(wave, name=None):
        """Create a MathWave that is dy/dx of *wave*."""
        if wave.x is None or wave.y is None:
            raise ValueError("Wave has no data")
        x = np.real(wave.x)
        y = np.real(wave.y)
        dydx = np.gradient(y, x)
        label = name or ("d/dx(%s)" % wave.key)
        yunit = ""
        if wave.yunit and wave.xunit:
            yunit = "%s/%s" % (wave.yunit, wave.xunit)
        return MathWave(x, dydx, label, xunit=wave.xunit, yunit=yunit,
                        xlabel=wave.xlabel, source_tag=wave.tag)

    @staticmethod
    def fromIntegral(wave, name=None):
        """Create a MathWave that is the cumulative integral of *wave*."""
        if wave.x is None or wave.y is None:
            raise ValueError("Wave has no data")
        x = np.real(wave.x)
        y = np.real(wave.y)
        integral = np.cumsum(y) * np.gradient(x)
        label = name or ("integral(%s)" % wave.key)
        yunit = ""
        if wave.yunit and wave.xunit:
            yunit = "%s*%s" % (wave.yunit, wave.xunit)
        return MathWave(x, integral, label, xunit=wave.xunit, yunit=yunit,
                        xlabel=wave.xlabel, source_tag=wave.tag)

    @staticmethod
    def fromFFT(wave, name=None):
        """Create a MathWave with the magnitude spectrum (dB) of *wave*."""
        if wave.x is None or wave.y is None:
            raise ValueError("Wave has no data")
        x = np.real(wave.x)
        y = np.real(wave.y)
        N = len(y)
        if N < 4:
            raise ValueError("Too few points for FFT")
        dt = np.mean(np.diff(x))
        if dt <= 0:
            raise ValueError("Non-positive time step")
        win = np.hanning(N)
        Y = np.fft.rfft(y * win)
        freqs = np.fft.rfftfreq(N, d=dt)
        mag = np.abs(Y) * 2.0 / np.sum(win)
        mag[mag < 1e-30] = 1e-30
        mag_db = 20.0 * np.log10(mag)
        label = name or ("FFT(%s)" % wave.key)
        return MathWave(freqs[1:], mag_db[1:], label, xunit="Hz",
                        yunit="dB", xlabel="Frequency",
                        source_tag=wave.tag)


class WaveFile():

    def __init__(self,fname,xaxis,sheet_name=0,df=None):
        self.xaxis = xaxis
        self.fname = fname
        self.sheet_name = sheet_name
        self.name = os.path.basename(fname)
        if isinstance(sheet_name, str):
            self.name += " [%s]" % sheet_name
        self.waves = dict()
        self.df = df
        self._virtual = df is not None
        self.reload()
        pass

    def reload(self):
        if self._virtual:
            return
        if(self.df is None):
            self.df = self._read_file()
            self.modified = os.path.getmtime(self.fname)
        else:
            newmodified = os.path.getmtime(self.fname)

            if(newmodified > self.modified):
                self.df = self._read_file()
                self.modified = newmodified

    PANDAS_READERS = {
        '.csv':     lambda self: self._read_csv(','),
        '.tsv':     lambda self: self._read_csv('\t'),
        '.txt':     lambda self: self._read_csv('\t'),
        '.xlsx':    lambda self: self._read_excel(),
        '.xls':     lambda self: self._read_excel(),
        '.ods':     lambda self: self._read_excel(),
        '.pkl':     lambda self: pd.read_pickle(self.fname),
        '.pickle':  lambda self: pd.read_pickle(self.fname),
        '.json':    lambda self: pd.read_json(self.fname),
        '.parquet': lambda self: pd.read_parquet(self.fname),
        '.feather': lambda self: pd.read_feather(self.fname),
        '.h5':      lambda self: pd.read_hdf(self.fname),
        '.hdf5':    lambda self: pd.read_hdf(self.fname),
        '.html':    lambda self: pd.read_html(self.fname)[0],
        '.xml':     lambda self: pd.read_xml(self.fname),
        '.fwf':     lambda self: pd.read_fwf(self.fname),
        '.stata':   lambda self: pd.read_stata(self.fname),
        '.dta':     lambda self: pd.read_stata(self.fname),
        '.sas7bdat': lambda self: pd.read_sas(self.fname),
        '.sav':     lambda self: pd.read_spss(self.fname),
    }

    def _read_file(self):
        ext = os.path.splitext(self.fname)[1].lower()
        reader = self.PANDAS_READERS.get(ext)
        if reader:
            return reader(self)
        return cs.toDataFrame(self.fname)

    def _read_csv(self, sep):
        try:
            df = pd.read_csv(self.fname, sep=sep)
        except Exception:
            df = pd.read_csv(self.fname, sep=None, engine='python')
        df.columns = [c.strip() for c in df.columns]
        return df

    def _read_excel(self):
        df = pd.read_excel(self.fname, sheet_name=self.sheet_name)
        df.columns = [c.strip() for c in df.columns]
        return df

    @staticmethod
    def excel_sheet_names(fname):
        xl = pd.ExcelFile(fname)
        return xl.sheet_names

    def getWaveNames(self):
        cols = self.df.columns
        return cols

    def getWave(self,yname):

        if(yname not in self.waves):
            wave = Wave(self,yname,self.xaxis)
            self.waves[yname] = wave

        wave = self.waves[yname]
        wave.reload()

        return wave

    def getTag(self,yname):
        return self.fname + "/" + yname


class WaveFiles(dict):

    def __init__(self):
        self.current = None
        self._groups = {}       # group_name -> list of signal names
        self._aliases = {}      # signal_name -> alias string
        self._session_path = None

    def open(self,fname,xaxis,sheet_name=0):
        key = fname if sheet_name == 0 else "%s::%s" % (fname, sheet_name)
        self[key] = WaveFile(fname,xaxis,sheet_name)
        self.current = key
        self._deriveSessionPath()
        self._loadSession()
        return self[key]

    def openDataFrame(self, df, name, xaxis):
        key = "::virtual::" + name
        self[key] = WaveFile(name, xaxis, df=df)
        self.current = key
        self._deriveSessionPath()
        self._loadSession()
        return self[key]

    def select(self,fname):
        if(fname in self):
            self.current = fname
            self._deriveSessionPath()
            self._loadSession()

    def getSelected(self):
        if(self.current is not None):
            return self[self.current]

    # ------------------------------------------------------------------
    # Virtual signal groups
    # ------------------------------------------------------------------

    def createGroup(self, name, signal_list):
        """Create a named group of signals that can be added/removed as a unit.

        Groups persist to the session file alongside favorites.
        """
        self._groups[name] = list(signal_list)
        self._saveSession()

    def removeGroup(self, name):
        """Remove a named group."""
        self._groups.pop(name, None)
        self._saveSession()

    def getGroup(self, name):
        """Return the signal list for a named group, or None."""
        return self._groups.get(name)

    def getGroupNames(self):
        """Return sorted list of all group names."""
        return sorted(self._groups.keys())

    def getGroupForSignal(self, signal_name):
        """Return list of group names that contain *signal_name*."""
        return [g for g, sigs in self._groups.items()
                if signal_name in sigs]

    # ------------------------------------------------------------------
    # Signal aliasing
    # ------------------------------------------------------------------

    def setAlias(self, signal_name, alias):
        """Set a display alias for a signal.

        Pass *alias* as ``""`` or ``None`` to clear the alias.
        Aliases are shown in the browser tree and plot legend.
        """
        if alias:
            self._aliases[signal_name] = alias
        else:
            self._aliases.pop(signal_name, None)
        self._saveSession()

    def getAlias(self, signal_name):
        """Return the alias for *signal_name*, or None if not aliased."""
        return self._aliases.get(signal_name)

    def getDisplayName(self, signal_name):
        """Return the alias if set, otherwise the raw signal name."""
        return self._aliases.get(signal_name, signal_name)

    def getAllAliases(self):
        """Return a copy of the alias dict."""
        return dict(self._aliases)

    # ------------------------------------------------------------------
    # Session persistence (groups + aliases)
    # ------------------------------------------------------------------

    def _deriveSessionPath(self):
        f = self.getSelected()
        if f is None:
            self._session_path = None
            return
        fname = f.fname
        if fname.startswith("::virtual::"):
            self._session_path = os.path.join(os.getcwd(), '.cicsession')
        else:
            base = os.path.splitext(fname)[0]
            self._session_path = base + '.cicsession'

    def _loadSession(self):
        self._groups = {}
        self._aliases = {}
        path = self._session_path
        if path and os.path.exists(path):
            try:
                with open(path, 'r') as fh:
                    data = json.load(fh)
                if isinstance(data.get('groups'), dict):
                    self._groups = data['groups']
                if isinstance(data.get('aliases'), dict):
                    self._aliases = data['aliases']
            except Exception:
                pass

    def _saveSession(self):
        path = self._session_path
        if not path:
            return
        data = {
            'groups': self._groups,
            'aliases': self._aliases,
        }
        try:
            with open(path, 'w') as fh:
                json.dump(data, fh, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CSV / VCD export
    # ------------------------------------------------------------------

    @staticmethod
    def exportCSV(filename, waves):
        """Export selected waveforms to a CSV file (time + values).

        *waves* is a list of Wave or MathWave objects.  The first wave's
        x-axis is used as the common time column; all others are
        interpolated onto it.
        """
        if not waves:
            return
        ref_x = None
        for w in waves:
            if w.x is not None:
                ref_x = np.real(w.x)
                break
        if ref_x is None:
            return

        cols = {'time': ref_x}
        for w in waves:
            key = w.key
            if w.x is not None and w.y is not None:
                y_interp = np.interp(ref_x, np.real(w.x), np.real(w.y))
            elif w.y is not None:
                y_interp = np.real(w.y)
                if len(y_interp) != len(ref_x):
                    y_interp = np.interp(ref_x,
                                         np.arange(len(y_interp)),
                                         y_interp)
            else:
                y_interp = np.full_like(ref_x, np.nan)
            cols[key] = y_interp

        df = pd.DataFrame(cols)
        df.to_csv(filename, index=False)

    @staticmethod
    def exportVCD(filename, waves, threshold=0.5):
        """Export selected waveforms to a VCD file (digital with threshold).

        Analog values are digitized: value >= *threshold* maps to ``1``,
        else ``0``.  The time base is derived from the first wave's x-axis
        and scaled to integer picoseconds.
        """
        if not waves:
            return
        ref_x = None
        for w in waves:
            if w.x is not None:
                ref_x = np.real(w.x)
                break
        if ref_x is None:
            return

        # Build digitized data for each wave
        wire_data = []
        for idx, w in enumerate(waves):
            key = w.key
            if w.x is not None and w.y is not None:
                y_interp = np.interp(ref_x, np.real(w.x), np.real(w.y))
            elif w.y is not None:
                y_interp = np.real(w.y)
                if len(y_interp) != len(ref_x):
                    y_interp = np.interp(ref_x,
                                         np.arange(len(y_interp)),
                                         y_interp)
            else:
                continue
            digital = (y_interp >= threshold).astype(int)
            # VCD identifier character (start from '!')
            ident = chr(33 + idx)
            wire_data.append((key, ident, digital))

        # Convert time to integer picoseconds
        t_ps = (ref_x * 1e12).astype(np.int64)

        with open(filename, 'w') as fh:
            import datetime
            fh.write("$date\n  %s\n$end\n" % datetime.datetime.now().isoformat())
            fh.write("$version\n  cicsim VCD export\n$end\n")
            fh.write("$timescale 1ps $end\n")
            fh.write("$scope module top $end\n")
            for key, ident, _ in wire_data:
                safe = key.replace(' ', '_')
                fh.write("$var wire 1 %s %s $end\n" % (ident, safe))
            fh.write("$upscope $end\n")
            fh.write("$enddefinitions $end\n")
            fh.write("#0\n")
            fh.write("$dumpvars\n")
            for _, ident, digital in wire_data:
                fh.write("%d%s\n" % (digital[0], ident))
            fh.write("$end\n")

            # Only emit changes
            prev = {ident: digital[0] for _, ident, digital in wire_data}
            for i in range(1, len(t_ps)):
                changes = []
                for key, ident, digital in wire_data:
                    val = digital[i]
                    if val != prev[ident]:
                        changes.append((ident, val))
                        prev[ident] = val
                if changes:
                    fh.write("#%d\n" % t_ps[i])
                    for ident, val in changes:
                        fh.write("%d%s\n" % (val, ident))
