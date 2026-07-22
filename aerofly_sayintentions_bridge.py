"""
Aerofly FS4 -> SayIntentions.AI Bridge
======================================
Streams live Aerofly telemetry to SayIntentions' file-based SimAPI, handles the
radio/squawk commands SayIntentions can send back, and helps prepare a flight
(weather, real time, aircraft selection, origin/destination route) before
launching Aerofly via Steam.
"""

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog
import json
import threading
import math
import time
import os
import re
import subprocess
import datetime
import urllib.request
import urllib.parse

try:
    import websocket
except ImportError:
    messagebox.showerror("Missing module", "Please install the websocket-client module!\nRun in a terminal: pip install websocket-client")
    exit()


class AeroflyToSayIntentionsUI:
    STEAM_APP_ID = "1995890"

    # --- Aerofly aircraft name -> ICAO / display type / SimAPI title ---
    AIRCRAFT_DB = {
        "a320": {"icao": "A320", "type": "AIRBUS", "title": "FenixA320"},
        "a320_neo": {"icao": "A20N", "type": "AIRBUS", "title": "Airbus A320neo Asobo"},
        "b737_800": {"icao": "B738", "type": "BOEING", "title": "PMDG 737-800"},
        "b737_900": {"icao": "B739", "type": "BOEING", "title": "PMDG 737-900"},
        "b737_max9": {"icao": "B39M", "type": "BOEING", "title": "Boeing 737 MAX 9"},
        "b747": {"icao": "B744", "type": "BOEING", "title": "Boeing 747-8i Asobo"},
        "b777": {"icao": "B77W", "type": "BOEING", "title": "PMDG 777-300ER"},
        "a380": {"icao": "A388", "type": "AIRBUS", "title": "FlyByWire A380-800"},
        "a350_1000": {"icao": "A35K", "type": "AIRBUS", "title": "Airbus A350-1000"},
        "q400": {"icao": "DH8D", "type": "BOMBARDIER", "title": "Majestic Q400"},
        "concorde": {"icao": "CONC", "type": "AEROSPATIALE", "title": "DC Designs Concorde"},
        "c172": {"icao": "C172", "type": "CESSNA", "title": "Cessna Skyhawk G1000 Asobo"},
        "kingairc90": {"icao": "BE9L", "type": "BEECHCRAFT", "title": "Beechcraft King Air 350i Asobo"},
        "baron58": {"icao": "BE58", "type": "BEECHCRAFT", "title": "Beechcraft Baron G58 Asobo"},
        "lj45": {"icao": "LJ45", "type": "LEARJET", "title": "Learjet 45"},
        "f18": {"icao": "F18", "type": "BOEING", "title": "F/A-18E Super Hornet Asobo"},
        "f15": {"icao": "F15", "type": "MCDONNELL DOUGLAS", "title": "F-15 Eagle"},
        "extra330": {"icao": "E330", "type": "EXTRA", "title": "Extra 330LT Asobo"},
    }

    # --- ICAO -> (ENGINE TYPE, typical weight lbs), for SayIntentions' required fields ---
    # ENGINE TYPE: 0=Piston, 1=Jet, 2=None, 3=Helo(Bell), 4=Unsupported, 5=Turboprop
    AIRCRAFT_PERF = {
        "A320": (1, 150000), "A20N": (1, 170000), "B738": (1, 174200),
        "B739": (1, 187700), "B39M": (1, 194700), "B744": (1, 875000),
        "B77W": (1, 775000), "A388": (1, 1235000), "A35K": (1, 340000),
        "DH8D": (5, 64500), "CONC": (1, 408000), "C172": (0, 2450),
        "BE9L": (5, 10100), "BE58": (0, 5500), "LJ45": (1, 21500),
        "F18": (1, 66000), "F15": (1, 68000), "E330": (0, 1808),
    }
    DEFAULT_PERF = (1, 150000)  # unknown aircraft: assume jet, ~150000 lbs

    def __init__(self, root):
        self.root = root
        self.root.title("Aerofly FS4 -> SayIntentions.AI Bridge (First Officer Ready)")
        self.root.geometry("740x800")
        self.root.attributes("-topmost", True)

        self._init_state()
        self._build_ui()
        self._start_background_tasks()

    # ==========================================================
    # SETUP
    # ==========================================================
    def _init_state(self):
        self.values = {}          # ui-key -> ttk.Label, for update_ui()
        self.sim_state = {}       # latest websocket telemetry from Aerofly
        self.ws = None
        self.ws_connected = False
        self.last_simapi_write = 0
        self.last_output_pos = 0

        self.ambient_wind_kts = None   # read from main.mcf, fed to SayIntentions
        self.ambient_wind_dir = None

        self.pending_weather = None    # staged for the next Launch (Weather tab)
        self.pending_aircraft = None   # (aerofly_name, paintscheme) staged for the next Launch
        self.pending_route = None      # {origin, destination, cruise_alt_m} staged for the next Launch

        self.icao_to_aerofly = {v["icao"]: k for k, v in self.AIRCRAFT_DB.items()}

        local_appdata = os.environ.get('LOCALAPPDATA', '')
        self.si_dir = os.path.join(local_appdata, 'SayIntentionsAI')
        self.simapi_output_path = os.path.join(self.si_dir, 'simAPI_output.jsonl')

        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bridge_config.json')
        self.custom_mcf_path = self._load_mcf_path_config()

    def _start_background_tasks(self):
        self.running = True
        threading.Thread(target=self._websocket_thread, daemon=True).start()
        self.root.after(1000, self._check_sayintentions_commands)

        # main.mcf itself never changes mid-flight, but this keeps the ambient
        # wind current across app restarts / new flights.
        self._load_ambient_wind_from_mcf()
        self.root.after(60000, self._wind_refresh_loop)

    # ==========================================================
    # UI CONSTRUCTION
    # ==========================================================
    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_basic = ttk.Frame(self.notebook)
        self.tab_fo = ttk.Frame(self.notebook)
        self.tab_simbrief = ttk.Frame(self.notebook)
        self.tab_weather = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_basic, text="Base Systems")
        self.notebook.add(self.tab_fo, text="First Officer")
        self.notebook.add(self.tab_simbrief, text="SimBrief")
        self.notebook.add(self.tab_weather, text="Weather")

        self._build_tab_basic()
        self._build_tab_fo()
        self._build_tab_simbrief()
        self._build_tab_weather()
        self._build_bottom_bar()

    def _add_label_row(self, parent, row, label_text, key, width=30, columnspan=1):
        """Helper: add a bold caption + a value label, and register the value label in self.values."""
        ttk.Label(parent, text=label_text, font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="w", padx=10, pady=5)
        val_label = ttk.Label(parent, text="---", font=("Arial", 10), width=width, anchor="w")
        val_label.grid(row=row, column=1, columnspan=columnspan, sticky="w", padx=10, pady=5)
        self.values[key] = val_label

    def _build_tab_basic(self):
        """Base Systems: everything SayIntentions reads from us."""
        fields = [
            ("Latitude:", "latitude"),
            ("Longitude:", "longitude"),
            ("Altitude:", "altitude"),
            ("Heading (Mag):", "heading"),
            ("IAS:", "ias"),
            ("GS:", "gs"),
            ("Aircraft Type:", "ac_type"),
            ("Flight Status:", "flight_status"),
            ("Nearest Airport:", "nearest_airport"),
            ("Ambient Wind (from config):", "ambient_wind"),
        ]
        for row, (label, key) in enumerate(fields):
            self._add_label_row(self.tab_basic, row, label, key)

    def _build_tab_fo(self):
        """First Officer: only what SayIntentions can actually send commands for."""
        row = 0

        self._add_label_row(self.tab_fo, row, "COM1 Active:", "com1_active", width=20)
        row += 1

        ttk.Label(self.tab_fo, text="COM1 Standby (MHz):", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="e", padx=10, pady=5)
        self.com1_stby_entry = tk.Entry(self.tab_fo, width=12, font=("Consolas", 10))
        self.com1_stby_entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
        tk.Button(self.tab_fo, text="Send", font=("Arial", 9), bg="#d9ead3", command=self.send_com1_stby).grid(row=row, column=2, padx=5, pady=5)
        tk.Button(self.tab_fo, text="SWAP", font=("Arial", 9, "bold"), bg="#fff2cc", command=self.swap_com1).grid(row=row, column=3, padx=5, pady=5)
        row += 1

        self._add_label_row(self.tab_fo, row, "COM2 Active:", "com2_active", width=20)
        row += 1

        ttk.Label(self.tab_fo, text="COM2 Standby (MHz):", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="e", padx=10, pady=5)
        self.com2_stby_entry = tk.Entry(self.tab_fo, width=12, font=("Consolas", 10))
        self.com2_stby_entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
        tk.Button(self.tab_fo, text="Send", font=("Arial", 9), bg="#d9ead3", command=self.send_com2_stby).grid(row=row, column=2, padx=5, pady=5)
        tk.Button(self.tab_fo, text="SWAP", font=("Arial", 9, "bold"), bg="#fff2cc", command=self.swap_com2).grid(row=row, column=3, padx=5, pady=5)
        row += 1

        self._add_label_row(self.tab_fo, row, "Squawk:", "squawk", width=20)

    def _build_tab_simbrief(self):
        """SimBrief: reference OFP data, plus aircraft/route staging for the next Launch."""
        row = 0
        ttk.Label(self.tab_simbrief, text="SimBrief Username:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="e", padx=10, pady=5)
        self.simbrief_user_entry = tk.Entry(self.tab_simbrief, width=20, font=("Consolas", 10))
        self.simbrief_user_entry.insert(0, "Dav111")
        self.simbrief_user_entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
        tk.Button(self.tab_simbrief, text="Fetch OFP", font=("Arial", 9, "bold"), bg="#cfe2f3", command=self.fetch_simbrief).grid(row=row, column=2, padx=5, pady=5)
        row += 1

        fields = [
            ("Callsign:", "sb_callsign"),
            ("Route:", "sb_route_pair"),
            ("Cruise Altitude:", "sb_cruise_alt"),
            ("Planned Fuel:", "sb_fuel"),
            ("Planned Passengers:", "sb_pax"),
            ("Cargo:", "sb_cargo"),
            ("ZFW:", "sb_zfw"),
            ("Est. Time Enroute:", "sb_ete"),
            ("OFP Issued:", "sb_issued"),
        ]
        for label, key in fields:
            self._add_label_row(self.tab_simbrief, row, label, key, width=45, columnspan=2)
            row += 1

        self._add_label_row(self.tab_simbrief, row, "Aircraft (auto-matched):", "sb_aircraft_match", width=45, columnspan=2)
        row += 1

        ttk.Label(self.tab_simbrief, text="Override aircraft:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="w", padx=10, pady=5)
        self.aircraft_combo = ttk.Combobox(self.tab_simbrief, values=list(self.AIRCRAFT_DB.keys()), width=20, state="readonly")
        self.aircraft_combo.grid(row=row, column=1, sticky="w", padx=10, pady=5)
        self.aircraft_combo.bind("<<ComboboxSelected>>", self._on_aircraft_override)
        row += 1

        self._add_label_row(self.tab_simbrief, row, "Route Staging:", "sb_route_stage", width=55, columnspan=2)
        row += 1

        # Full route gets its own multi-line box - a single-line label was cutting it off
        ttk.Label(self.tab_simbrief, text="Full Route:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="nw", padx=10, pady=5)
        self.sb_route_text = tk.Text(self.tab_simbrief, height=3, width=58, font=("Consolas", 9), wrap="word")
        self.sb_route_text.grid(row=row, column=1, columnspan=2, sticky="w", padx=10, pady=5)
        self.sb_route_text.config(state="disabled")
        row += 1

        ttk.Label(
            self.tab_simbrief,
            text="This data is for your own reference only - it is NOT sent to SayIntentions\n"
                 "(that requires a Virtual Airline API key from SayIntentions support).\n"
                 "Aircraft + Origin/Destination/Cruise Altitude ARE staged for your next Launch.\n"
                 "Runways are NOT set automatically - pick them in Aerofly as usual. Cost Index\n"
                 "has no equivalent field in main.mcf, so it can't be set this way. Fuel/payload\n"
                 "are reference-only for now - Aerofly doesn't reliably apply externally written\n"
                 "fuel/payload values yet (under investigation on the Aerofly forum).",
            font=("Arial", 8, "italic"), foreground="gray"
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=10, pady=10)

    def _build_tab_weather(self):
        """Weather: fetch a real METAR and stage wind/visibility/clouds for the next Launch."""
        row = 0
        ttk.Label(self.tab_weather, text="Airport ICAO:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="e", padx=10, pady=5)
        self.weather_icao_entry = tk.Entry(self.tab_weather, width=10, font=("Consolas", 10))
        self.weather_icao_entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
        tk.Button(self.tab_weather, text="Fetch METAR", font=("Arial", 9, "bold"), bg="#cfe2f3", command=self.fetch_weather_metar).grid(row=row, column=2, padx=5, pady=5)
        row += 1

        ttk.Label(self.tab_weather, text="Raw METAR:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="nw", padx=10, pady=5)
        raw_label = ttk.Label(self.tab_weather, text="---", font=("Consolas", 9), width=55, anchor="w", wraplength=420)
        raw_label.grid(row=row, column=1, columnspan=2, sticky="w", padx=10, pady=5)
        self.values["wx_raw"] = raw_label
        row += 1

        fields = [
            ("Wind:", "wx_wind"),
            ("Visibility:", "wx_visibility"),
            ("Clouds:", "wx_clouds"),
            ("Temperature:", "wx_temp"),
            ("QNH (informational):", "wx_qnh"),
        ]
        for label, key in fields:
            self._add_label_row(self.tab_weather, row, label, key, width=35, columnspan=2)
            row += 1

        ttk.Label(
            self.tab_weather,
            text="Note: Aerofly has no temperature or barometric pressure model, so\n"
                 "these two can't be applied - only wind, visibility and clouds are staged.",
            font=("Arial", 8, "italic"), foreground="gray"
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=10, pady=5)
        row += 1

        self.weather_status = tk.Label(self.tab_weather, text="No weather fetched yet.", font=("Arial", 8, "italic"), fg="gray")
        self.weather_status.grid(row=row, column=0, columnspan=3, sticky="w", padx=10, pady=10)
        row += 1

        ttk.Separator(self.tab_weather, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", padx=10, pady=10)
        row += 1

        tk.Button(self.tab_weather, text="Browse main.mcf...", font=("Arial", 9), bg="#d9d2e9", command=self.browse_mcf).grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.mcf_path_label = tk.Label(self.tab_weather, text=self.custom_mcf_path or "(auto-detect)", font=("Arial", 8), fg="blue")
        self.mcf_path_label.grid(row=row, column=1, columnspan=2, sticky="w", padx=5, pady=5)

    def _build_bottom_bar(self):
        """Status + Launch controls, visible under every tab."""
        control_frame = tk.Frame(self.root)
        control_frame.pack(fill="x", padx=10, pady=5)

        launch_frame = tk.Frame(control_frame)
        launch_frame.pack(pady=5)
        tk.Button(launch_frame, text="Launch Normal", font=("Arial", 10, "bold"), bg="#b6d7a8",
                  command=lambda: self.launch_aerofly(vr=False)).grid(row=0, column=0, padx=10)
        tk.Button(launch_frame, text="Launch VR", font=("Arial", 10, "bold"), bg="#a4c2f4",
                  command=lambda: self.launch_aerofly(vr=True)).grid(row=0, column=1, padx=10)

        self.launch_status = tk.Label(control_frame, text="Not launched yet.", font=("Arial", 8, "italic"), fg="gray")
        self.launch_status.pack(pady=2)

        self.sayintentions_status = tk.Label(control_frame, text="SayIntentions SimAPI: Waiting...", fg="orange", font=("Arial", 10, "bold"))
        self.sayintentions_status.pack(pady=2)

        self.status_label = tk.Label(control_frame, text="FS4 Bridge: Waiting for connection...", fg="red", font=("Arial", 9, "italic"))
        self.status_label.pack(pady=2)

    def update_ui(self, key, value):
        if key in self.values:
            self.values[key].config(text=value)

    def set_status(self, text, color):
        self.status_label.config(text=text, fg=color)

    # ==========================================================
    # main.mcf: PATH HANDLING + LOW-LEVEL EDITING
    # ==========================================================
    def _load_mcf_path_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                path = cfg.get('mcf_path')
                if path and os.path.exists(path):
                    return path
        except Exception:
            pass
        return None

    def _save_mcf_path_config(self, path):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump({'mcf_path': path}, f)
        except Exception:
            pass

    def find_mcf_path(self):
        if self.custom_mcf_path and os.path.exists(self.custom_mcf_path):
            return self.custom_mcf_path

        home_dir = os.path.expanduser('~')
        candidates = [
            os.path.join(home_dir, 'Documents', 'Aerofly FS 4', 'main.mcf'),
            os.path.join(home_dir, 'OneDrive', 'Documents', 'Aerofly FS 4', 'main.mcf'),
            os.path.join(home_dir, 'OneDrive - Personal', 'Documents', 'Aerofly FS 4', 'main.mcf'),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def browse_mcf(self):
        initial_dir = os.path.dirname(self.custom_mcf_path) if self.custom_mcf_path else os.path.expanduser('~')
        path = filedialog.askopenfilename(
            title="Select main.mcf",
            initialdir=initial_dir,
            filetypes=[("Aerofly config files", "*.mcf"), ("All files", "*.*")]
        )
        if path:
            self.custom_mcf_path = path
            self._save_mcf_path_config(path)
            self.mcf_path_label.config(text=path)

    @staticmethod
    def replace_mcf_value(lines, key_name, new_value):
        """Replace the first '[key_name][...]' occurrence in main.mcf's line list. Returns True if found."""
        pattern = re.compile(r"(\[" + re.escape(key_name) + r"\])\[.*?\]")
        marker = f"[{key_name}]["
        for i, line in enumerate(lines):
            if marker in line:
                lines[i] = pattern.sub(lambda m: m.group(1) + f"[{new_value}]", line, count=1)
                return True
        return False

    @staticmethod
    def find_installed_paintscheme(mcf_content, aerofly_name):
        """Look up the last-used paintscheme for a given aircraft in main.mcf's aircraft_list,
        so we apply a livery you've actually used before instead of a blank/default one."""
        try:
            list_section = mcf_content[mcf_content.index("[aircraft_list]"):]
        except ValueError:
            return ""
        pattern = re.compile(r"\[name\]\[" + re.escape(aerofly_name) + r"\]>\s*<\[string8u\]\[paintscheme\]\[([^\]]*)\]")
        m = pattern.search(list_section)
        return m.group(1) if m else ""

    @staticmethod
    def lla_to_ecef(lat_deg, lon_deg, elev_m):
        """WGS84 geodetic (lat/lon in degrees, elevation in meters) -> ECEF X/Y/Z in meters."""
        a = 6378137.0
        f = 1 / 298.257223563
        e2 = f * (2 - f)
        lat = math.radians(lat_deg)
        lon = math.radians(lon_deg)
        sin_lat = math.sin(lat)
        n = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
        x = (n + elev_m) * math.cos(lat) * math.cos(lon)
        y = (n + elev_m) * math.cos(lat) * math.sin(lon)
        z = (n * (1 - e2) + elev_m) * sin_lat
        return x, y, z

    @staticmethod
    def find_block_range(lines, marker):
        """Find a '<[...][marker]...' block and its matching closing '>' line (by indentation)."""
        for i, line in enumerate(lines):
            if marker in line:
                indent = len(line) - len(line.lstrip())
                for j in range(i + 1, len(lines)):
                    if lines[j].strip() == ">" and (len(lines[j]) - len(lines[j].lstrip())) == indent:
                        return i, j
                return i, None
        return None, None

    def build_route_block(self, base_indent, origin, destination, cruise_alt_m):
        """Builds a replacement 'tmnav_route' block containing just Origin + Destination
        (no runway-specific entries, since we don't have runway threshold data)."""
        ind = " " * base_indent
        i1, i2, i3 = ind + "    ", ind + "        ", ind + "            "
        ox, oy, oz = self.lla_to_ecef(origin['lat'], origin['lon'], origin['elev_m'])
        dx, dy, dz = self.lla_to_ecef(destination['lat'], destination['lon'], destination['elev_m'])

        return [
            f"{ind}<[tmnav_route][Route][]\n",
            f"{i1}<[float64][CruiseAltitude][{cruise_alt_m:.2f}]>\n",
            f"{i1}<[pointer_list_tmnav_route_way][Ways][]\n",
            f"{i2}<[tmnav_route_origin][{origin['icao']}][0]\n",
            f"{i3}<[string8u][Identifier][{origin['icao']}]>\n",
            f"{i3}<[vector3_float64][Position][{ox:.6f} {oy:.6f} {oz:.6f}]>\n",
            f"{i3}<[uint64][Uid][0]>\n",
            f"{i3}<[float64][Elevation][{origin['elev_m']:.4f}]>\n",
            f"{i2}>\n",
            f"{i2}<[tmnav_route_destination][{destination['icao']}][1]\n",
            f"{i3}<[string8u][Identifier][{destination['icao']}]>\n",
            f"{i3}<[vector3_float64][Position][{dx:.6f} {dy:.6f} {dz:.6f}]>\n",
            f"{i3}<[uint64][Uid][0]>\n",
            f"{i3}<[float64][Elevation][{destination['elev_m']:.4f}]>\n",
            f"{i2}>\n",
            f"{i1}>\n",
            f"{ind}>\n",
        ]

    def apply_route_to_lines(self, lines):
        if not self.pending_route:
            return False
        start, end = self.find_block_range(lines, "[tmnav_route][Route]")
        if start is None or end is None:
            return False
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        new_block = self.build_route_block(
            base_indent,
            self.pending_route['origin'],
            self.pending_route['destination'],
            self.pending_route['cruise_alt_m'],
        )
        lines[start:end + 1] = new_block
        return True

    # ==========================================================
    # AMBIENT WIND (read-only, fed to SayIntentions)
    # ==========================================================
    def _wind_refresh_loop(self):
        self._load_ambient_wind_from_mcf()
        if self.running:
            self.root.after(60000, self._wind_refresh_loop)

    def _load_ambient_wind_from_mcf(self):
        mcf_path = self.find_mcf_path()
        if not mcf_path:
            return
        try:
            with open(mcf_path, 'r', encoding='utf-8') as f:
                content = f.read()
            s_match = re.search(r"\[strength\]\[([\d.eE+-]+)\]", content)
            d_match = re.search(r"\[direction_in_degree\]\[([\d.eE+-]+)\]", content)
            if s_match and d_match:
                x = float(s_match.group(1))
                # knots = 8 * (x + x^2), verified against fboes/aerofly-wettergeraet measurements
                self.ambient_wind_kts = 8 * (x + x * x)
                self.ambient_wind_dir = float(d_match.group(1)) % 360
                self.root.after(0, self.update_ui, "ambient_wind", f"{self.ambient_wind_kts:.0f} kt @ {self.ambient_wind_dir:.0f}°")
        except Exception:
            pass

    # ==========================================================
    # WEATHER TAB: FETCH + STAGE FOR NEXT LAUNCH
    # ==========================================================
    def fetch_weather_metar(self):
        icao = self.weather_icao_entry.get().strip().upper()
        if not icao:
            return
        try:
            url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data:
                messagebox.showwarning("No data", f"No METAR found for {icao}")
                return
            m = data[0]

            raw = m.get("rawOb", "---")
            wind_dir = float(m.get("wdir") or 0)
            wind_kt = float(m.get("wspd") or 0)

            try:
                visib_sm = float(str(m.get("visib", 10)).replace("+", ""))
            except ValueError:
                visib_sm = 10.0

            temp_c = m.get("temp", None)
            altim_hpa = m.get("altim", 1013)
            clouds = m.get("clouds", [])

            cover_density = {"FEW": 0.25, "SCT": 0.5, "BKN": 0.85, "OVC": 1.0}
            cloud_density, cloud_base_ft = 0.0, 0
            for c in clouds:
                cov = c.get("cover", "")
                if cov in cover_density:
                    cloud_density = cover_density[cov]
                    cloud_base_ft = c.get("base", 0) or 0
                    break

            visib_m = visib_sm * 1609.34
            visibility_pct = min(visib_m / 15000.0, 1.0)
            # Inverse of knots = 8*(x + x^2)  ->  x = (sqrt(1 + 0.5*knots) - 1) / 2
            wind_pct = (math.sqrt(1 + 0.5 * wind_kt) - 1) / 2
            cloud_height_pct = min(cloud_base_ft / 10000.0, 1.0) if cloud_base_ft else 0.0

            self.pending_weather = {
                'wind_pct': wind_pct, 'wind_dir': wind_dir,
                'visibility_pct': visibility_pct,
                'cloud_density': cloud_density, 'cloud_height_pct': cloud_height_pct,
            }

            self.update_ui("wx_raw", raw)
            self.update_ui("wx_wind", f"{wind_dir:.0f}° @ {wind_kt:.0f} kt")
            self.update_ui("wx_visibility", f"{visib_sm:.1f} SM (~{visib_m:.0f} m)")
            self.update_ui("wx_clouds", f"{cloud_base_ft:.0f} ft AGL" if cloud_base_ft else "Clear / few")
            self.update_ui("wx_temp", f"{temp_c}°C" if temp_c is not None else "---")
            self.update_ui("wx_qnh", f"{altim_hpa} hPa (can't be applied - see note)")
            self.weather_status.config(text=f"Weather for {icao} parsed and staged - applied on your next Launch.", fg="blue")

        except Exception as e:
            messagebox.showerror("Weather fetch error", f"Could not fetch METAR:\n{e}")

    # ==========================================================
    # LAUNCH: WRITE REAL TIME + STAGED WEATHER/AIRCRAFT/ROUTE, THEN START AEROFLY VIA STEAM
    # ==========================================================
    @staticmethod
    def is_aerofly_running():
        try:
            output = subprocess.check_output('tasklist', shell=True, text=True, errors='ignore')
            return 'aerofly_fs_4.exe' in output.lower()
        except Exception:
            return False

    def launch_aerofly(self, vr):
        if self.is_aerofly_running():
            messagebox.showwarning(
                "Aerofly is running",
                "Aerofly is already running. Close it first so the updated time/weather/"
                "aircraft/route settings can actually take effect on the next start."
            )
            return

        mcf_path = self.find_mcf_path()
        if not mcf_path:
            messagebox.showerror("Error", "Could not find main.mcf - use 'Browse main.mcf...' on the Weather tab to select it manually.")
            return

        try:
            with open(mcf_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            now = datetime.datetime.utcnow()
            self.replace_mcf_value(lines, "time_year", now.year)
            self.replace_mcf_value(lines, "time_month", now.month)
            self.replace_mcf_value(lines, "time_day", now.day)
            time_hours = now.hour + now.minute / 60 + now.second / 3600
            self.replace_mcf_value(lines, "time_hours", f"{time_hours:.6f}")

            applied_parts = []

            if self.pending_weather:
                w = self.pending_weather
                self.replace_mcf_value(lines, "visibility", f"{w['visibility_pct']:.4f}")
                self.replace_mcf_value(lines, "strength", f"{w['wind_pct']:.4f}")
                self.replace_mcf_value(lines, "direction_in_degree", f"{w['wind_dir']:.1f}")
                self.replace_mcf_value(lines, "cumulus_density", f"{w['cloud_density']:.4f}")
                self.replace_mcf_value(lines, "cumulus_height", f"{w['cloud_height_pct']:.4f}")
                applied_parts.append("weather")

            if self.pending_aircraft:
                name, paintscheme = self.pending_aircraft
                self.replace_mcf_value(lines, "name", name)
                if paintscheme:
                    self.replace_mcf_value(lines, "paintscheme", paintscheme)
                applied_parts.append("aircraft")

            if self.pending_route and self.apply_route_to_lines(lines):
                applied_parts.append("route (origin/destination/cruise alt)")

            self.replace_mcf_value(lines, "vr_use_openvr", "true" if vr else "false")

            with open(mcf_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            os.startfile(f"steam://rungameid/{self.STEAM_APP_ID}")

            extra = f" + staged {', '.join(applied_parts)}" if applied_parts else ""
            self.launch_status.config(
                text=f"Real time written{extra}. Launching Aerofly in {'VR' if vr else 'Normal'} mode via Steam...",
                fg="green"
            )

        except Exception as e:
            messagebox.showerror("Error", f"Failed to prepare/launch Aerofly:\n{e}")

    # ==========================================================
    # SIMBRIEF
    # ==========================================================
    def _on_aircraft_override(self, _event):
        self.pending_aircraft = (self.aircraft_combo.get(), "")

    def fetch_simbrief(self):
        username = self.simbrief_user_entry.get().strip()
        if not username:
            return
        try:
            url = f"https://www.simbrief.com/api/xml.fetcher.php?username={urllib.parse.quote(username)}&json=1"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            self._apply_simbrief_flight_info(data)
            self._match_simbrief_aircraft(data)
            self._stage_simbrief_route(data)

            orig = data.get("origin", {}).get("icao_code", "")
            if orig:
                self.weather_icao_entry.delete(0, tk.END)
                self.weather_icao_entry.insert(0, orig)
                self.fetch_weather_metar()  # departure weather, since that's where the flight starts

        except Exception as e:
            messagebox.showerror("SimBrief error", f"Could not fetch the OFP:\n{e}")

    def _apply_simbrief_flight_info(self, data):
        callsign = data.get("atc", {}).get("callsign", "---")
        orig = data.get("origin", {}).get("icao_code", "----")
        orig_rwy = data.get("origin", {}).get("plan_rwy", "")
        dest = data.get("destination", {}).get("icao_code", "----")
        dest_rwy = data.get("destination", {}).get("plan_rwy", "")
        route = data.get("general", {}).get("route", "---")
        cruise_alt = data.get("general", {}).get("initial_altitude", "---")
        fuel = data.get("fuel", {}).get("plan_ramp", None)
        pax = data.get("weights", {}).get("pax_count", None)
        cargo = data.get("weights", {}).get("cargo", None)
        zfw = data.get("weights", {}).get("est_zfw", "---")
        units = data.get("params", {}).get("units", "lbs")
        ete_sec = data.get("times", {}).get("est_time_enroute", None)
        issued = data.get("params", {}).get("time_generated", "---")

        self.update_ui("sb_callsign", callsign)
        self.update_ui("sb_route_pair", f"{orig} -> {dest}")
        self.update_ui("sb_cruise_alt", f"{cruise_alt} ft")
        self.update_ui("sb_fuel", f"{fuel} {units}" if fuel is not None else "---")
        self.update_ui("sb_pax", str(pax) if pax is not None else "---")
        self.update_ui("sb_cargo", f"{cargo} {units}" if cargo is not None else "---")
        self.update_ui("sb_zfw", f"{zfw} {units}" if zfw != "---" else "---")
        if ete_sec:
            h, mnt = divmod(int(ete_sec) // 60, 60)
            self.update_ui("sb_ete", f"{h}h {mnt:02d}m")
        self.update_ui("sb_issued", str(issued))

        self.sb_route_text.config(state="normal")
        self.sb_route_text.delete("1.0", tk.END)
        self.sb_route_text.insert("1.0", f"{orig}/{orig_rwy} {route} {dest}/{dest_rwy}".strip())
        self.sb_route_text.config(state="disabled")

    def _match_simbrief_aircraft(self, data):
        icao = data.get("aircraft", {}).get("icaocode", "")
        aerofly_name = self.icao_to_aerofly.get(icao)

        if not aerofly_name:
            self.update_ui("sb_aircraft_match", f"No match for ICAO {icao} - pick manually below")
            return

        paintscheme = ""
        mcf_path = self.find_mcf_path()
        if mcf_path:
            try:
                with open(mcf_path, 'r', encoding='utf-8') as f:
                    paintscheme = self.find_installed_paintscheme(f.read(), aerofly_name)
            except Exception:
                pass

        self.pending_aircraft = (aerofly_name, paintscheme)
        self.aircraft_combo.set(aerofly_name)
        self.update_ui("sb_aircraft_match", f"Matched: {aerofly_name} ({icao}) - will be applied on Launch")

    def _stage_simbrief_route(self, data):
        try:
            origin = data.get("origin", {})
            destination = data.get("destination", {})
            cruise_ft = float(data.get("general", {}).get("initial_altitude", 0) or 0)

            self.pending_route = {
                'origin': {
                    'icao': origin.get("icao_code", ""),
                    'lat': float(origin.get("pos_lat", 0)),
                    'lon': float(origin.get("pos_long", 0)),
                    'elev_m': float(origin.get("elevation", 0) or 0) * 0.3048,
                },
                'destination': {
                    'icao': destination.get("icao_code", ""),
                    'lat': float(destination.get("pos_lat", 0)),
                    'lon': float(destination.get("pos_long", 0)),
                    'elev_m': float(destination.get("elevation", 0) or 0) * 0.3048,
                },
                'cruise_alt_m': cruise_ft * 0.3048,
            }
            o, d = self.pending_route['origin']['icao'], self.pending_route['destination']['icao']
            self.update_ui("sb_route_stage", f"Staged: {o} -> {d} @ {cruise_ft:.0f} ft - applied on next Launch (runways NOT set, pick manually)")
        except Exception as e:
            self.update_ui("sb_route_stage", f"Could not stage route: {e}")

    # ==========================================================
    # WEBSOCKET SEND HELPERS
    # ==========================================================
    def _send_ws_payload(self, var_name, value):
        if not self.ws_connected or not self.ws:
            return
        try:
            json_str = json.dumps({"variable": var_name, "value": value})
            self.ws.send(json_str)
            print(f"WS payload sent: {json_str.strip()}")
        except Exception as e:
            print(f"Error sending WS payload: {str(e)}")

    def update_entry_from_ai(self, entry_widget, mhz_value):
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, f"{mhz_value:.3f}")

    def execute_auto_swap(self, is_com1=True):
        if is_com1:
            self.send_com1_stby()
            self.root.after(300, self.swap_com1)
        else:
            self.send_com2_stby()
            self.root.after(300, self.swap_com2)

    def send_com1_stby(self):
        self._send_com_stby(self.com1_stby_entry, "Communication.COM1StandbyFrequency")

    def send_com2_stby(self):
        self._send_com_stby(self.com2_stby_entry, "Communication.COM2StandbyFrequency")

    def _send_com_stby(self, entry, var_name):
        val_str = entry.get().strip()
        if not val_str:
            return
        try:
            value = float(val_str)
            if value < 1000:
                value = int(value * 1000000)
            self._send_ws_payload(var_name, value)
        except ValueError:
            pass

    def swap_com1(self):
        self._send_ws_payload("Communication.COM1FrequencySwap", 1)

    def swap_com2(self):
        self._send_ws_payload("Communication.COM2FrequencySwap", 1)

    # ==========================================================
    # SAYINTENTIONS RECEIVER (commands it actually sends)
    # ==========================================================
    def _check_sayintentions_commands(self):
        # Per SayIntentions' official output_variables.txt, the file-based SimAPI only
        # ever sends: COM_RADIO_SET_HZ, COM_STBY_RADIO_SET_HZ, COM_RADIO_SWAP,
        # COM2_RADIO_SET_HZ, COM2_STBY_RADIO_SET_HZ, COM2_RADIO_SWAP, XPNDR_SET,
        # COM1_VOLUME_SET, COM2_VOLUME_SET, AUDIO_PANEL_VOLUME_SET.
        # The volume commands are received but not acted on below, because the
        # Aerofly Bridge does not expose any radio/audio volume variable to write to.
        if self.running and os.path.exists(self.simapi_output_path):
            try:
                current_size = os.path.getsize(self.simapi_output_path)
                if current_size < self.last_output_pos:
                    self.last_output_pos = 0
                if current_size > self.last_output_pos:
                    with open(self.simapi_output_path, 'r', encoding='utf-8') as f:
                        f.seek(self.last_output_pos)
                        lines = f.readlines()
                        self.last_output_pos = f.tell()
                    self._process_sayintentions_commands(lines)
            except Exception:
                pass

        if self.running:
            self.root.after(1000, self._check_sayintentions_commands)

    def _process_sayintentions_commands(self, lines):
        trigger_com1_swap = False
        trigger_com2_swap = False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                var_name = data.get("setvar")
                var_val = data.get("value")
                if not var_name or var_val == "":
                    continue

                try:
                    val_float = float(var_val)
                    mhz_val = val_float / 1000000.0 if val_float > 1000000 else val_float

                    if var_name == "COM_RADIO_SET_HZ":
                        self.update_entry_from_ai(self.com1_stby_entry, mhz_val)
                        trigger_com1_swap = True
                        print(f"FO Action: setting COM1 active: {mhz_val}")
                    elif var_name == "COM_STBY_RADIO_SET_HZ":
                        self.update_entry_from_ai(self.com1_stby_entry, mhz_val)
                        print(f"FO Action: setting COM1 standby: {mhz_val}")
                    elif var_name == "COM2_RADIO_SET_HZ":
                        self.update_entry_from_ai(self.com2_stby_entry, mhz_val)
                        trigger_com2_swap = True
                    elif var_name == "COM2_STBY_RADIO_SET_HZ":
                        self.update_entry_from_ai(self.com2_stby_entry, mhz_val)
                    elif var_name == "XPNDR_SET":
                        self._send_ws_payload("Communication.TransponderAltitude", int(var_val))
                        print(f"FO Action: squawk set to: {var_val}")
                except ValueError:
                    pass

            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"FO error: {e}")

        if trigger_com1_swap:
            self.execute_auto_swap(is_com1=True)
        if trigger_com2_swap:
            self.execute_auto_swap(is_com1=False)

    # ==========================================================
    # WRITING THE SAYINTENTIONS INPUT FILE
    # ==========================================================
    def get_simapi_input_path(self):
        os.makedirs(self.si_dir, exist_ok=True)
        return os.path.join(self.si_dir, 'simAPI_input.json')

    def write_simapi_file(self, t):
        current_time = time.time()
        if current_time - self.last_simapi_write < 0.5:
            return

        try:
            simapi_data = {
                "sim": {
                    "variables": {
                        "PLANE LATITUDE": t['lat_deg'],
                        "PLANE LONGITUDE": t['lon_deg'],
                        "PLANE ALTITUDE": int(round(t['alt_ft'])),
                        "INDICATED ALTITUDE": int(round(t['alt_ft'])),
                        "AIRSPEED INDICATED": int(round(t['spd_kts'])),
                        "AIRSPEED TRUE": int(round(t['gs_kts'])),
                        "PLANE HEADING DEGREES TRUE": int(round(t['hdg_true'])) % 360,
                        "MAGNETIC COMPASS": int(round(t['hdg_mag'])) % 360,
                        "MAGVAR": int(round(t['magvar'])),
                        "PLANE PITCH DEGREES": int(round(t['pitch_deg'])),
                        "PLANE BANK DEGREES": int(round(t['roll_deg'])),
                        "VERTICAL SPEED": int(round(t['vs_fpm'])),
                        "PLANE ALT ABOVE GROUND MINUS CG": int(round(t['agl_ft'])),
                        "SIM ON GROUND": int(t['on_ground']),
                        "ENGINE TYPE": int(t['engine_type']),
                        "TOTAL WEIGHT": int(t['total_weight']),
                        "WHEEL RPM:1": int(t['wheel_rpm']),
                        # Aerofly has no barometric pressure model at all (confirmed via main.mcf -
                        # only wind/clouds/visibility exist), so this is always standard pressure.
                        "SEA LEVEL PRESSURE": 1013,
                        "AMBIENT WIND DIRECTION": int(round(t['wind_dir'])) if t['wind_dir'] is not None else 0,
                        "AMBIENT WIND VELOCITY": int(round(t['wind_kts'])) if t['wind_kts'] is not None else 0,
                        "COM ACTIVE FREQUENCY:1": t['com1_mhz'],
                        "COM STANDBY FREQUENCY:1": t['com1_mhz'] + 0.5,
                        "COM ACTIVE FREQUENCY:2": t['com2_mhz'],
                        "COM STANDBY FREQUENCY:2": t['com2_mhz'] + 0.5,
                        "COM TRANSMIT:1": 1,
                        "COM RECEIVE:1": 1,
                        "COM TRANSMIT:2": 1,
                        "COM RECEIVE:2": 1,
                        "TRANSPONDER CODE:1": int(t['squawk']),
                        "TRANSPONDER STATE:1": 4,
                        "ATC ID": "HA-FS4",
                        "TITLE": t['ac_title'],
                        "ATC MODEL": t['ac_icao'],
                        "ATC TYPE": t['ac_type'],
                    },
                    "exe": "aerofly_fs_4.exe",
                    "simapi_version": "1.0",
                    "name": "AeroflyFS4",
                    "version": "7.0.0",
                    "adapter_version": "1.7.0"
                }
            }

            input_file_path = self.get_simapi_input_path()
            temp_path = f"{input_file_path}.tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(simapi_data, f, indent=2)
            os.replace(temp_path, input_file_path)

            self.last_simapi_write = current_time
            self.root.after(0, lambda: self.sayintentions_status.config(text="SayIntentions SimAPI: ACTIVE (First Officer Ready)", fg="green"))

        except Exception as e:
            self.root.after(0, lambda err=e: self.sayintentions_status.config(text=f"SimAPI error: {err}", fg="red"))

    # ==========================================================
    # WEBSOCKET CONNECTION + TELEMETRY PROCESSING
    # ==========================================================
    def _on_ws_message(self, ws, message):
        try:
            json_data = json.loads(message)
            self.process_variables(json_data.get("variables", json_data))
        except json.JSONDecodeError:
            pass

    def _on_ws_error(self, ws, error):
        pass

    def _on_ws_close(self, ws, close_status_code, close_msg):
        self.ws_connected = False
        self.root.after(0, self.set_status, "FS4 Bridge: Waiting for simulator...", "red")
        self.root.after(0, lambda: self.sayintentions_status.config(text="SayIntentions SimAPI: Stopped", fg="red"))

    def _on_ws_open(self, ws):
        self.ws_connected = True
        self.root.after(0, self.set_status, "FS4 Bridge: Connected (WebSocket)", "green")

    def _websocket_thread(self):
        while self.running:
            self.root.after(0, self.set_status, "FS4 Bridge: Connecting (WebSocket)...", "orange")
            self.ws = websocket.WebSocketApp(
                "ws://127.0.0.1:8765",
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
            )
            self.ws.on_open = self._on_ws_open
            self.ws.run_forever()
            if self.running:
                time.sleep(2)

    def process_variables(self, vars_dict):
        self.sim_state.update(vars_dict)

        def get_var(name, default=0.0):
            return self.sim_state.get(name, default)

        # --- Position, attitude, speed ---
        lat_raw = get_var("Aircraft.Latitude")
        lon_raw = get_var("Aircraft.Longitude")
        lat_deg = math.degrees(lat_raw) if abs(lat_raw) <= 3.15 else lat_raw
        lon_deg = math.degrees(lon_raw) if abs(lon_raw) <= 6.3 else lon_raw

        alt_ft = get_var("Aircraft.Altitude", 0.0) * 3.28084
        height_ft = get_var("Aircraft.Height", 0.0) * 3.28084
        vs_fpm = get_var("Aircraft.VerticalSpeed", 0.0) * 196.85

        # Aerofly reports a mathematical angle (0=East, CCW) -> convert to compass heading (0=North, CW)
        hdg_true = (90 - math.degrees(get_var("Aircraft.TrueHeading", 0.0))) % 360
        hdg_mag = (90 - math.degrees(get_var("Aircraft.MagneticHeading", 0.0))) % 360

        pitch_deg = math.degrees(get_var("Aircraft.Pitch", 0.0))
        roll_deg = math.degrees(get_var("Aircraft.Bank", 0.0))

        spd_kts = get_var("Aircraft.IndicatedAirspeed", 0.0) * 1.94384
        gs_kts = get_var("Aircraft.GroundSpeed", 0.0) * 1.94384

        nearest_airport = str(get_var("Aircraft.NearestAirportIdentifier", ""))

        # On-ground detection: the raw Aerofly flag can get "stuck", so it's cross-checked
        # against height above ground and corrected if it clearly disagrees with reality.
        on_ground_raw = int(get_var("Aircraft.OnGround", 0))
        if on_ground_raw == 1 and height_ft > 50:
            on_ground = 0
        elif on_ground_raw == 0 and height_ft < 2 and abs(vs_fpm) < 50:
            on_ground = 1
        else:
            on_ground = on_ground_raw

        # --- Aircraft identity ---
        ac_name_raw = str(get_var("Aircraft.Name", "a320")).lower()
        ac_info = self.AIRCRAFT_DB.get(ac_name_raw, {"icao": ac_name_raw.upper(), "type": "UNKNOWN", "title": ac_name_raw.capitalize()})
        ac_icao, ac_type, ac_title = ac_info["icao"], ac_info["type"], ac_info["title"]

        # --- Radios / transponder ---
        raw_com1 = get_var("Communication.COM1Frequency")
        com1_mhz = raw_com1 / 1000000.0 if raw_com1 > 1000000 else (raw_com1 / 1000.0 if raw_com1 > 1000 else raw_com1)
        raw_com2 = get_var("Communication.COM2Frequency")
        com2_mhz = raw_com2 / 1000000.0 if raw_com2 > 1000000 else (raw_com2 / 1000.0 if raw_com2 > 1000 else raw_com2)
        try:
            squawk_int = int(get_var("Communication.TransponderAltitude"))
        except Exception:
            squawk_int = 1200

        # --- Fields required by SayIntentions that Aerofly doesn't expose directly ---
        magvar = ((hdg_true - hdg_mag + 180) % 360) - 180
        engine_type, total_weight = self.AIRCRAFT_PERF.get(ac_icao, self.DEFAULT_PERF)
        agl_ft = 0 if on_ground == 1 else height_ft
        wheel_rpm = int(gs_kts * 15) if on_ground == 1 else 0

        telemetry = {
            'lat_deg': lat_deg, 'lon_deg': lon_deg, 'alt_ft': alt_ft,
            'pitch_deg': pitch_deg, 'roll_deg': roll_deg,
            'hdg_true': hdg_true, 'hdg_mag': hdg_mag, 'magvar': magvar,
            'spd_kts': spd_kts, 'gs_kts': gs_kts, 'vs_fpm': vs_fpm,
            'com1_mhz': com1_mhz, 'com2_mhz': com2_mhz,
            'squawk': squawk_int, 'on_ground': on_ground,
            'ac_icao': ac_icao, 'ac_type': ac_type, 'ac_title': ac_title,
            'engine_type': engine_type, 'total_weight': total_weight,
            'agl_ft': agl_ft, 'wheel_rpm': wheel_rpm,
            'wind_dir': self.ambient_wind_dir, 'wind_kts': self.ambient_wind_kts,
        }
        self.write_simapi_file(telemetry)

        self.root.after(0, self.update_ui, "latitude", f"{lat_deg:.5f}°")
        self.root.after(0, self.update_ui, "longitude", f"{lon_deg:.5f}°")
        self.root.after(0, self.update_ui, "altitude", f"{alt_ft:.0f} ft")
        self.root.after(0, self.update_ui, "heading", f"{hdg_mag:.1f}°")
        self.root.after(0, self.update_ui, "ias", f"{spd_kts:.1f} kts")
        self.root.after(0, self.update_ui, "gs", f"{gs_kts:.1f} kts")
        self.root.after(0, self.update_ui, "ac_type", f"{ac_type} / {ac_icao}")
        self.root.after(0, self.update_ui, "flight_status", "ON GROUND" if on_ground == 1 else "AIRBORNE")
        self.root.after(0, self.update_ui, "nearest_airport", nearest_airport or "---")
        self.root.after(0, self.update_ui, "com1_active", f"{com1_mhz:.3f} MHz")
        self.root.after(0, self.update_ui, "com2_active", f"{com2_mhz:.3f} MHz")
        self.root.after(0, self.update_ui, "squawk", f"{squawk_int:04d}")

    def on_close(self):
        self.running = False
        if self.ws:
            self.ws.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AeroflyToSayIntentionsUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()