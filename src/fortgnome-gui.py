#!/usr/bin/env python3
"""FortGNOME VPN — GUI + top-bar indicator for a FortiGate IPsec VPN.

Settings (server / username / password / PSK / destination subnet) are stored
per-user in ~/.config/fortgnome/config.ini and applied to strongSwan via the
privileged helper `fortgnome-apply` (run through sudo). First run with no config
opens the Settings dialog automatically.
"""
import os, sys, signal, configparser, subprocess, threading, time, gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, GdkPixbuf, AyatanaAppIndicator3 as AppIndicator

PREFIX   = "/usr/lib/fortgnome"
ICONS    = os.path.join(PREFIX, "icons")
LOGO     = os.path.join(ICONS, "fortgnome-app.png")
DEFAULTS = os.path.join(PREFIX, "defaults.conf")
CFG_DIR  = os.path.expanduser("~/.config/fortgnome")
CFG      = os.path.join(CFG_DIR, "config.ini")
HELPER   = "/usr/bin/fortgnome"
APPLY    = "/usr/bin/fortgnome-apply"
APP_ID   = "fortgnome-vpn"
PIDFILE  = os.path.join(GLib.get_user_runtime_dir() or "/tmp", "fortgnome-gui.pid")
CONNECT_TIMEOUT = 30   # seconds before a connection attempt is abandoned with a timeout

FIELDS = [  # key, label, is_secret
    ("server",        "VPN server (gateway IP/host)", False),
    ("username",      "Username",                     False),
    ("password",      "Password",                     True),
    ("psk",           "Pre-shared key (PSK)",         True),
    ("remote_subnet", "Destination network (CIDR)",   False),
]

GLib.set_prgname("fortgnome-vpn")
try: Gtk.Window.set_default_icon_from_file(LOGO)
except Exception: pass


def load_config():
    cp = configparser.ConfigParser()
    cp.read([DEFAULTS, CFG])  # shipped defaults, then the user's own values on top
    return dict(cp["vpn"]) if cp.has_section("vpn") else {}

def have_config():
    return os.path.exists(CFG)

def write_config(values):
    # merge onto any existing file so advanced keys (e.g. client_subnet) survive
    cp = configparser.ConfigParser(); cp.read(CFG)
    if not cp.has_section("vpn"): cp.add_section("vpn")
    for k, v in values.items():
        cp.set("vpn", k, v)
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG, "w") as f:
        cp.write(f)
    os.chmod(CFG, 0o600)

def apply_config():
    """Run the privileged apply. Returns (ok, message). Safe to call off the
    main thread; has a timeout so a stuck daemon can't block forever."""
    try:
        r = subprocess.run(["sudo", "-n", APPLY], capture_output=True, text=True, timeout=90)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "apply timed out (is the VPN daemon stuck? try Disconnect first)"
    except Exception as e:
        return False, str(e)

def vpn_is_up():
    try:
        out = subprocess.run(["ip", "route", "show", "table", "220"],
                             capture_output=True, text=True, timeout=4).stdout
        return bool(out.strip())
    except Exception:
        return False


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, on_saved):
        super().__init__(title="FortGNOME VPN — Settings", transient_for=parent, flags=0)
        self.on_saved = on_saved
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        self.set_default_size(400, -1)
        cur = load_config()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        for m in ("top", "bottom", "start", "end"): getattr(grid, "set_margin_"+m)(16)
        self.entries = {}
        for row, (key, label, secret) in enumerate(FIELDS):
            lbl = Gtk.Label(label=label, xalign=0)
            ent = Gtk.Entry(); ent.set_hexpand(True); ent.set_text(cur.get(key, ""))
            if secret:
                ent.set_visibility(False)
                ent.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
                ent.connect("icon-press", lambda e, *a: e.set_visibility(not e.get_visibility()))
            if key == "remote_subnet":
                ent.set_placeholder_text("e.g. 10.0.0.0/24")
            grid.attach(lbl, 0, row, 1, 1); grid.attach(ent, 1, row, 1, 1)
            self.entries[key] = ent
        self.msg = Gtk.Label(xalign=0); self.msg.get_style_context().add_class("dim-label")
        grid.attach(self.msg, 0, len(FIELDS), 2, 1)
        self.get_content_area().add(grid)
        self.show_all()
        self.connect("response", self._on_response)

    def _on_response(self, dlg, resp):
        if resp != Gtk.ResponseType.OK:
            self.destroy(); return
        values = {k: e.get_text().strip() for k, e in self.entries.items()}
        missing = [lbl for (k, lbl, _) in FIELDS if not values[k]]
        if missing:
            self.msg.set_markup('<span foreground="red">Please fill: %s</span>' % ", ".join(missing))
            self.stop_emission_by_name("response"); return
        # write the (fast) config file now, then apply in the background so the
        # GUI never freezes while strongSwan reloads.
        write_config(values)
        self.stop_emission_by_name("response")          # keep dialog open until apply finishes
        self.set_response_sensitive(Gtk.ResponseType.OK, False)
        self.set_response_sensitive(Gtk.ResponseType.CANCEL, False)
        self.msg.set_markup("<i>Applying…</i>")
        def worker():
            ok, info = apply_config()
            GLib.idle_add(self._apply_done, ok, info)
        threading.Thread(target=worker, daemon=True).start()

    def _apply_done(self, ok, info):
        if ok:
            self.destroy(); self.on_saved()
        else:
            self.set_response_sensitive(Gtk.ResponseType.OK, True)
            self.set_response_sensitive(Gtk.ResponseType.CANCEL, True)
            self.msg.set_markup('<span foreground="red">Apply failed: %s</span>'
                                % GLib.markup_escape_text(info or "see terminal"))
        return False


class StatusWindow(Gtk.Window):
    _COL = {"Connected": "#1a8a1a", "Connecting…": "#1976d2", "Disconnected": "#888888"}

    def __init__(self, app):
        super().__init__(title="FortGNOME VPN")
        self.app = app
        try: self.set_icon_from_file(LOGO)
        except Exception: pass
        self.set_default_size(360, 300); self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        # destroy on close (don't hide) so reopening always works cleanly
        self.connect("destroy", lambda *_: setattr(self.app, "win", None))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ("top", "bottom", "start", "end"): getattr(box, "set_margin_"+m)(18)
        self.img = Gtk.Image(); box.pack_start(self.img, False, False, 0)
        self.spinner = Gtk.Spinner(); self.spinner.set_size_request(28, 28)
        self.spinner.set_no_show_all(True)
        box.pack_start(self.spinner, False, False, 0)
        self.lbl = Gtk.Label(); box.pack_start(self.lbl, False, False, 0)
        self.btn = Gtk.Button(); self.btn.set_size_request(-1, 44)
        self.btn.connect("clicked", self.app.on_toggle)
        box.pack_start(self.btn, False, False, 0)
        self.err = Gtk.Label(); self.err.set_line_wrap(True)
        self.err.set_justify(Gtk.Justification.CENTER)
        box.pack_start(self.err, False, False, 0)
        setb = Gtk.Button(label="Settings…")
        setb.connect("clicked", lambda *_: self.app.open_settings())
        box.pack_start(setb, False, False, 0)
        self.add(box)

    def render(self, icon, status, btn_label, btn_sensitive, err):
        self.img.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(ICONS, icon + ".png"), 96, 96))
        if status == "Connecting…":
            self.spinner.show(); self.spinner.start()
        else:
            self.spinner.stop(); self.spinner.hide()
        col = self._COL.get(status, "#888888")
        self.lbl.set_markup('<b><span foreground="%s">%s</span></b>'
                            % (col, GLib.markup_escape_text(status)))
        self.btn.set_label(btn_label); self.btn.set_sensitive(btn_sensitive)
        self.err.set_markup(('<span foreground="#c0271a"><small>%s</small></span>'
                             % GLib.markup_escape_text(err)) if err else "")


class FortGnome:
    # the single-line progress steps shown with an N/5 counter while connecting
    STEPS = ["Starting VPN service", "Contacting VPN gateway", "Authenticating",
             "Getting network configuration", "Establishing encrypted tunnel"]

    def __init__(self):
        self.busy = False
        self.mode = None       # 'connecting' | 'disconnecting' | None
        self.win = None
        self.progress = None   # step text shown on the button while connecting
        self.failed = None     # last failure reason (small red sub-line)
        self._proc = None      # the running 'ipsec up' process (for cancel)
        self._cancelled = False
        self._abort = None     # 'cancel' | 'timeout' | None
        self._timeout_id = None
        self.ind = AppIndicator.Indicator.new_with_path(
            APP_ID, "fortgnome-off", AppIndicator.IndicatorCategory.SYSTEM_SERVICES, ICONS)
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.ind.set_title("FortGNOME VPN")
        m = Gtk.Menu()
        self.mi_status = Gtk.MenuItem(label="…"); self.mi_status.set_sensitive(False)
        self.mi_toggle = Gtk.MenuItem(label="Connect"); self.mi_toggle.connect("activate", self.on_toggle)
        mi_win = Gtk.MenuItem(label="Open window…");   mi_win.connect("activate", lambda *_: self.show_window())
        mi_set = Gtk.MenuItem(label="Settings…");      mi_set.connect("activate", lambda *_: self.open_settings())
        mi_quit = Gtk.MenuItem(label="Quit FortGNOME"); mi_quit.connect("activate", self._quit)
        for w in (self.mi_status, Gtk.SeparatorMenuItem(), self.mi_toggle, mi_win, mi_set,
                  Gtk.SeparatorMenuItem(), mi_quit):
            m.append(w)
        m.show_all(); self.ind.set_menu(m)
        # let a second launch (or `kill -USR1`) raise our window
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self._on_signal)
        self._apply()
        GLib.timeout_add_seconds(5, self._tick)
        if not have_config():
            GLib.timeout_add(400, lambda: (self.open_settings(), False)[1])

    # ---- one place that renders state into both the tray menu and the window ----
    def _apply(self):
        up = (not self.busy) and vpn_is_up()
        if self.busy and self.mode == "connecting":
            status, icon = "Connecting…", "fortgnome-wait"
            btn, sens = (self.progress or "Connecting…"), True   # click cancels
        elif self.busy:                                          # disconnecting
            status, icon = "Disconnected", "fortgnome-wait"
            btn, sens = "Disconnecting…", False
        elif up:
            self.failed = None
            status, icon = "Connected", "fortgnome-on"
            btn, sens = "Disconnect", True
        else:
            status, icon = "Disconnected", "fortgnome-off"
            btn, sens = "Connect", True
        err = self.failed if (not self.busy and not up and self.failed) else ""
        self.ind.set_icon_full(icon, status)
        self.mi_status.set_label(status)
        self.mi_toggle.set_label(btn); self.mi_toggle.set_sensitive(sens)
        if self.win: self.win.render(icon, status, btn, sens, err)

    def refresh(self): self._apply()
    def _tick(self):
        if not self.busy: self._apply()
        return True

    def _set_progress(self, text):
        self.progress = text; self._apply(); return False

    def _result(self, ok, msg):
        if self._timeout_id:
            GLib.source_remove(self._timeout_id); self._timeout_id = None
        self.busy = False; self.mode = None; self.progress = None
        self._proc = None; self._cancelled = False; self._abort = None
        self.failed = None if (ok or msg is None) else msg
        self._apply(); return False

    def _stepline(self, i, extra=""):
        return "%s… (%d/%d)%s" % (self.STEPS[i], i + 1, len(self.STEPS), extra)

    def _on_signal(self):
        self.show_window(); return True       # a 2nd launch / kill -USR1 raises the window

    def _on_timeout(self):
        self._timeout_id = None
        if self.busy and self.mode == "connecting" and not self._abort:
            self._abort_attempt("timeout")
        return False

    def _quit(self, *_):
        if vpn_is_up():
            d = Gtk.MessageDialog(transient_for=self.win, modal=True,
                                  message_type=Gtk.MessageType.WARNING,
                                  buttons=Gtk.ButtonsType.OK_CANCEL,
                                  text="Quit FortGNOME VPN?")
            d.format_secondary_text("The VPN is currently connected. Quitting will disconnect it.")
            d.set_default_response(Gtk.ResponseType.CANCEL)
            resp = d.run(); d.destroy()
            if resp != Gtk.ResponseType.OK:
                return
            subprocess.run([HELPER, "down"], capture_output=True)
        try:
            if os.path.exists(PIDFILE): os.remove(PIDFILE)
        except Exception: pass
        Gtk.main_quit()

    def on_toggle(self, *_):
        if self.busy:
            if self.mode == "connecting" and not self._abort:
                self._abort_attempt("cancel")   # click while connecting = abandon
            return
        if not have_config():
            self.open_settings(); return
        if vpn_is_up(): self._disconnect()
        else:           self._connect()

    def _connect(self):
        self.busy = True; self.mode = "connecting"
        self.failed = None; self._cancelled = False; self._abort = None; self._proc = None
        self.progress = self._stepline(0)
        self._timeout_id = GLib.timeout_add_seconds(CONNECT_TIMEOUT, self._on_timeout)
        self._apply()
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _disconnect(self):
        self.busy = True; self.mode = "disconnecting"; self.failed = None
        self._apply()
        def w():
            subprocess.run([HELPER, "down"], capture_output=True)
            GLib.idle_add(self._result, False, None)
        threading.Thread(target=w, daemon=True).start()

    def _abort_attempt(self, kind):
        self._abort = kind; self._cancelled = True
        self.progress = "Cancelling…" if kind == "cancel" else "Timing out…"
        self._apply()
        # tell the daemon to abort the negotiation, and stop the 'ipsec up' client
        threading.Thread(target=lambda: subprocess.run(
            ["sudo", "-n", "ipsec", "down", "fortgnome"], capture_output=True),
            daemon=True).start()
        p = self._proc
        if p and p.poll() is None:
            try: p.terminate()
            except Exception: pass

    def _connect_worker(self):
        done, fail = set(), None
        # make sure the daemon is up first
        if subprocess.run(["pgrep", "-x", "charon"], capture_output=True).returncode != 0:
            subprocess.run(["sudo", "-n", "ipsec", "start"], capture_output=True)
            for _ in range(20):
                if self._cancelled: break
                if subprocess.run(["sudo", "-n", "ipsec", "status"], capture_output=True).returncode == 0:
                    break
                time.sleep(0.3)
        if not self._cancelled:
            GLib.idle_add(self._set_progress, self._stepline(1))   # contacting gateway
            try:
                proc = subprocess.Popen(["sudo", "-n", "ipsec", "up", "fortgnome"],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1)
                self._proc = proc
                for line in proc.stdout:
                    if self._cancelled:
                        break
                    l = line.strip()
                    if "IKE_SA" in l and "established between" in l and "contact" not in done:
                        done.add("contact"); GLib.idle_add(self._set_progress, self._stepline(2))
                    elif "XAuth authentication" in l and "successful" in l and "auth" not in done:
                        done.add("auth"); GLib.idle_add(self._set_progress, self._stepline(3))
                    elif "installing new virtual IP" in l and "netcfg" not in done:
                        done.add("netcfg"); GLib.idle_add(self._set_progress, self._stepline(4, "  " + l.split()[-1]))
                    elif ("established successfully" in l or ("CHILD_SA" in l and "established with" in l)) and "tunnel" not in done:
                        done.add("tunnel")
                    if "giving up after" in l and not fail:
                        fail = ("No reply from the VPN gateway. Check your internet connection "
                                "and server address, and that this network allows VPN "
                                "(UDP 500/4500 — some Wi-Fi/hotspots block them).")
                    elif "NO_PROPOSAL_CHOSEN" in l and not fail:
                        fail = ("The gateway rejected the connection settings (encryption or "
                                "destination network). Check the destination CIDR in Settings.")
                proc.wait(); time.sleep(0.4)
            except Exception as e:
                GLib.idle_add(self._result, False, str(e)); return
        # ---- decide the outcome ----
        if self._abort == "timeout":
            GLib.idle_add(self._result, False,
                          "Connection timed out — the VPN gateway didn't respond in time."); return
        if self._abort == "cancel":
            GLib.idle_add(self._result, False, None); return
        up = subprocess.run(["ip", "route", "show", "table", "220"],
                            capture_output=True, text=True).stdout.strip() != ""
        if up and "tunnel" in done:
            GLib.idle_add(self._result, True, None)
        else:
            if not fail:
                if "contact" not in done:
                    fail = "Couldn't reach the VPN gateway — check your network and the server address."
                elif "auth" not in done:
                    fail = "Login rejected — check your username and password."
                elif "netcfg" not in done:
                    fail = "The gateway didn't assign a network configuration."
                else:
                    fail = "Couldn't establish the encrypted tunnel."
            GLib.idle_add(self._result, False, fail)

    def open_settings(self):
        SettingsDialog(self.win, on_saved=self.refresh)  # shows itself; response-driven

    def show_window(self):
        if self.win is None:
            self.win = StatusWindow(self)
        self.win.show_all(); self.win.deiconify(); self.win.present()
        self._apply()


def _running_instance():
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)            # raises if that process is gone
        return pid
    except Exception:
        return None


if __name__ == "__main__":
    other = _running_instance()
    if other:
        # already running: ask that instance to open its window, then exit
        try: os.kill(other, signal.SIGUSR1)
        except Exception: pass
        sys.exit(0)
    try:
        with open(PIDFILE, "w") as f: f.write(str(os.getpid()))
    except Exception: pass
    import atexit
    atexit.register(lambda: os.path.exists(PIDFILE) and os.remove(PIDFILE))
    app = FortGnome()
    if "--tray" not in sys.argv:      # launched by the user → open the window
        app.show_window()
    Gtk.main()
