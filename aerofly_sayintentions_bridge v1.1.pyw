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
from tkinter import font as tkfont
from tkinter import scrolledtext
import json
import threading
import math
import time
import os
import re
import csv
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
    RUNWAYS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
    RUNWAYS_CACHE_MAX_AGE_DAYS = 30

    # --- Aerofly aircraft folder name -> ICAO / display type / SimAPI title ---
    # NOTE: this is NOT the source of the "Override aircraft" dropdown any more -
    # that's populated live by scan_installed_aircraft() from your actual install,
    # so it can never go stale. This table only does two things: (1) lets SimBrief's
    # ICAO code get matched to the right Aerofly folder, and (2) feeds AIRCRAFT_PERF
    # below for SayIntentions' required engine-type/weight fields. Airliner entries
    # are the ones that matter most, since those are what SimBrief actually plans for -
    # historical/aerobatic/military types are included for telemetry reporting but
    # won't realistically get an OFP match.
    AIRCRAFT_DB = {
        "a319": {"icao": "A319", "type": "AIRBUS", "title": "Airbus A319"},
        "a320": {"icao": "A320", "type": "AIRBUS", "title": "FenixA320"},
        "a320_neo": {"icao": "A20N", "type": "AIRBUS", "title": "Airbus A320neo Asobo"},
        "a321": {"icao": "A321", "type": "AIRBUS", "title": "Airbus A321"},
        "a321_xlr": {"icao": "A21N", "type": "AIRBUS", "title": "Airbus A321XLR"},
        "a350_1000": {"icao": "A35K", "type": "AIRBUS", "title": "Airbus A350-1000"},
        "a380": {"icao": "A388", "type": "AIRBUS", "title": "FlyByWire A380-800"},
        "b737": {"icao": "B737", "type": "BOEING", "title": "Boeing 737"},
        "b737_800": {"icao": "B738", "type": "BOEING", "title": "PMDG 737-800"},
        "b737_900": {"icao": "B739", "type": "BOEING", "title": "PMDG 737-900"},
        "b737_max9": {"icao": "B39M", "type": "BOEING", "title": "Boeing 737 MAX 9"},
        "b747": {"icao": "B744", "type": "BOEING", "title": "Boeing 747-8i Asobo"},
        "b777_300er": {"icao": "B77W", "type": "BOEING", "title": "PMDG 777-300ER"},
        "b777f": {"icao": "B77L", "type": "BOEING", "title": "Boeing 777F"},
        "b787": {"icao": "B788", "type": "BOEING", "title": "Boeing 787-8"},
        "b787_9": {"icao": "B789", "type": "BOEING", "title": "Boeing 787-9"},
        "crj900": {"icao": "CRJ9", "type": "BOMBARDIER", "title": "Bombardier CRJ900"},
        "q400": {"icao": "DH8D", "type": "BOMBARDIER", "title": "Majestic Q400"},
        "concorde": {"icao": "CONC", "type": "AEROSPATIALE", "title": "DC Designs Concorde"},
        "c172": {"icao": "C172", "type": "CESSNA", "title": "Cessna Skyhawk G1000 Asobo"},
        "c90gtx": {"icao": "BE9L", "type": "BEECHCRAFT", "title": "Beechcraft King Air C90GTx"},
        "b58": {"icao": "BE58", "type": "BEECHCRAFT", "title": "Beechcraft Baron G58 Asobo"},
        "lj45": {"icao": "LJ45", "type": "LEARJET", "title": "Learjet 45"},
        "dr400": {"icao": "DR40", "type": "ROBIN", "title": "Robin DR400"},
        "ec135": {"icao": "EC35", "type": "AIRBUS HELICOPTERS", "title": "Airbus EC135"},
        "r22": {"icao": "R22", "type": "ROBINSON", "title": "Robinson R22"},
        "uh60": {"icao": "H60", "type": "SIKORSKY", "title": "UH-60 Black Hawk"},
        "f18": {"icao": "F18", "type": "BOEING", "title": "F/A-18E Super Hornet Asobo"},
        "f15e": {"icao": "F15", "type": "MCDONNELL DOUGLAS", "title": "F-15E Strike Eagle"},
        "extra330": {"icao": "E330", "type": "EXTRA", "title": "Extra 330LT Asobo"},
        "mb339": {"icao": "M339", "type": "AERMACCHI", "title": "Aermacchi MB-339"},
        # Gliders - no real ICAO type designator most SimAPI consumers recognize;
        # "GLID" is the closest ICAO uses for unpowered gliders in general.
        "antares": {"icao": "GLID", "type": "GLIDER", "title": "Lange Antares"},
        "asg29": {"icao": "GLID", "type": "GLIDER", "title": "Schleicher ASG 29"},
        "ask21": {"icao": "GLID", "type": "GLIDER", "title": "Schleicher ASK 21"},
        "swift": {"icao": "GLID", "type": "GLIDER", "title": "Swift S1"},
        # Historical/aerobatic - included for accurate telemetry reporting only.
        "bf109e": {"icao": "ME09", "type": "MESSERSCHMITT", "title": "Messerschmitt Bf 109E"},
        "camel": {"icao": "CAML", "type": "SOPWITH", "title": "Sopwith Camel"},
        "dr1": {"icao": "DR1", "type": "FOKKER", "title": "Fokker Dr.1"},
        "f4u": {"icao": "F4U", "type": "VOUGHT", "title": "Vought F4U Corsair"},
        "ju52": {"icao": "JU52", "type": "JUNKERS", "title": "Junkers Ju 52"},
        "jungmeister": {"icao": "BU133", "type": "BUCKER", "title": "Bucker Bu 133 Jungmeister"},
        "me262": {"icao": "ME26", "type": "MESSERSCHMITT", "title": "Messerschmitt Me 262"},
        "p38": {"icao": "P38", "type": "LOCKHEED", "title": "Lockheed P-38 Lightning"},
        "pitts": {"icao": "PITS", "type": "PITTS", "title": "Pitts Special"},
    }

    # --- ICAO -> (ENGINE TYPE, typical weight lbs), for SayIntentions' required fields ---
    # ENGINE TYPE: 0=Piston, 1=Jet, 2=None, 3=Helo(Bell), 4=Unsupported, 5=Turboprop
    AIRCRAFT_PERF = {
        "A319": (1, 142200), "A320": (1, 150000), "A20N": (1, 170000), "A321": (1, 206000),
        "A21N": (1, 206000), "A35K": (1, 340000), "A388": (1, 1235000),
        "B737": (1, 130000), "B738": (1, 174200), "B739": (1, 187700), "B39M": (1, 194700),
        "B744": (1, 875000), "B77W": (1, 775000), "B77L": (1, 766000),
        "B788": (1, 502500), "B789": (1, 560000),
        "CRJ9": (1, 84500), "DH8D": (5, 64500), "CONC": (1, 408000),
        "C172": (0, 2450), "BE9L": (5, 10100), "BE58": (0, 5500), "LJ45": (1, 21500),
        "DR40": (0, 2645), "EC35": (3, 6415), "R22": (3, 1370), "H60": (3, 22000),
        "F18": (1, 66000), "F15": (1, 68000), "M339": (1, 13000), "E330": (0, 1808),
        "GLID": (2, 1200),
    }
    DEFAULT_PERF = (1, 150000)  # unknown aircraft: assume jet, ~150000 lbs

    # --- ICAO airline code (from the SimBrief callsign) -> (IATA code, livery folder
    # name fragment). IATA feeds the free Kiwi.com logo endpoint (images.kiwi.com/
    # airlines/64/<IATA>.png, no API key needed); the slug is fuzzy-matched against
    # installed livery folder names in _match_livery_by_callsign(). Best-effort and
    # inherently add-on-dependent for the slug half - extend freely, it only ever
    # improves the guess and never breaks the manual-pick fallback.
    ICAO_AIRLINE_INFO = {
        "AFR": ("AF", "airfrance"), "BAW": ("BA", "britishairways"), "DLH": ("LH", "lufthansa"),
        "SWR": ("LX", "swiss"), "KLM": ("KL", "klm"), "IBE": ("IB", "iberia"),
        "AZA": ("AZ", "alitalia"), "ITY": ("AZ", "itaairways"), "SAS": ("SK", "sas"),
        "FIN": ("AY", "finnair"), "EIN": ("EI", "aerlingus"), "EZY": ("U2", "easyjet"),
        "RYR": ("FR", "ryanair"), "VLG": ("VY", "vueling"), "GWI": ("4U", "germanwings"),
        "EWG": ("EW", "eurowings"), "TAP": ("TP", "tap"), "BEL": ("SN", "brussels"),
        "AUA": ("OS", "austrian"), "LOT": ("LO", "lot"), "CSA": ("OK", "czech"),
        "WZZ": ("W6", "wizzair"), "VOE": ("V7", "volotea"), "PGT": ("PC", "pegasus"),
        "THY": ("TK", "turkish"), "AHY": ("J2", "azerbaijan"), "UAL": ("UA", "united"),
        "DAL": ("DL", "delta"), "AAL": ("AA", "american"), "SWA": ("WN", "southwest"),
        "NKS": ("NK", "spirit"), "AAY": ("G4", "allegiant"), "JBU": ("B6", "jetblue"),
        "ASA": ("AS", "alaska"), "FFT": ("F9", "frontier"), "ACA": ("AC", "aircanada"),
        "AVA": ("AV", "avianca"), "LAN": ("LA", "latam"), "TAM": ("JJ", "tam"),
        "VOI": ("Y4", "volaris"), "GLO": ("G3", "gol"), "AZU": ("AD", "azul"),
        "CCA": ("CA", "airchina"), "CES": ("MU", "chinaeastern"), "CSN": ("CZ", "chinasouthern"),
        "CPA": ("CX", "cathaypacific"), "SIA": ("SQ", "singapore"), "ANA": ("NH", "ana"),
        "JAL": ("JL", "jal"), "QFA": ("QF", "qantas"), "UAE": ("EK", "emirates"),
        "QTR": ("QR", "qatar"), "ETD": ("EY", "etihad"), "SVA": ("SV", "saudia"),
        "RJA": ("RJ", "royaljordanian"), "MSR": ("MS", "egyptair"), "ETH": ("ET", "ethiopian"),
        "KQA": ("KQ", "kenyaairways"), "SAA": ("SA", "southafrican"), "RAM": ("AT", "royalair"),
        "TUN": ("TU", "tunisair"), "PAL": ("PR", "philippine"), "CEB": ("5J", "cebupacific"),
        "BKP": ("PG", "bangkokair"), "DRK": ("KB", "drukair"), "MAU": ("MK", "airmauritius"),
        "CYP": ("CY", "cyprus"),
    }



    # --- EFB "glass cockpit" color palette ---
    COL_BG = "#12161c"          # app background - near-black navy
    COL_PANEL = "#1a2029"       # card/tab background, one step up from COL_BG
    COL_PANEL_ALT = "#212836"   # slightly lighter panel (entries, list rows)
    COL_BORDER = "#2c3543"
    COL_TEXT = "#e7ecf3"
    COL_TEXT_DIM = "#8894a6"
    COL_ACCENT = "#4fd1ff"      # cyan - primary accent, like an MFD readout
    COL_ACCENT_2 = "#ffb545"    # amber - warnings / secondary accent
    COL_GOOD = "#5ee88a"
    COL_BAD = "#ff6b6b"
    FONT_UI = ("Segoe UI", 10)
    FONT_UI_BOLD = ("Segoe UI", 10, "bold")
    FONT_DATA = ("Consolas", 10)
    FONT_DATA_FREQ = ("Consolas", 14, "bold")
    FONT_HEADER = ("Segoe UI", 12, "bold")

    def __init__(self, root):
        self.root = root
        self.root.title("Aerofly FS4  \u2708  SayIntentions.AI Bridge")
        self.root.geometry("780x840")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=self.COL_BG)

        self._init_state()
        self._apply_glass_cockpit_theme()
        self._build_ui()
        self._start_background_tasks()

    def _apply_glass_cockpit_theme(self):
        """Dark, EFB-style ttk theme: near-black panels, cyan/amber accents,
        monospace data readouts. Built on the 'clam' base theme since it's the
        only stock ttk theme that reliably accepts custom colors on Windows."""
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Radio-panel frequency font: prefer an actual 7-segment/LCD-style font if the
        # user happens to have one installed (common in flight-sim circles), otherwise
        # fall back to Consolas - tkinter would silently substitute a default font for
        # an unavailable family anyway, but checking first keeps the intent explicit.
        try:
            installed_fonts = set(tkfont.families(self.root))
        except Exception:
            installed_fonts = set()
        seven_segment_family = next(
            (name for name in ("DSEG7 Classic", "DSEG7-Classic", "DSEG7 Modern", "Digital-7", "Segment7Standard")
             if name in installed_fonts),
            "Consolas"
        )
        self.FONT_DATA_FREQ = (seven_segment_family, 16, "bold")

        style.configure(".", background=self.COL_BG, foreground=self.COL_TEXT, font=self.FONT_UI)
        style.configure("TFrame", background=self.COL_PANEL)
        style.configure("TLabel", background=self.COL_PANEL, foreground=self.COL_TEXT, font=self.FONT_UI)
        style.configure("Dim.TLabel", background=self.COL_PANEL, foreground=self.COL_TEXT_DIM, font=("Segoe UI", 8, "italic"))
        style.configure("Data.TLabel", background=self.COL_PANEL, foreground=self.COL_ACCENT, font=self.FONT_DATA)
        style.configure("Header.TLabel", background=self.COL_BG, foreground=self.COL_ACCENT, font=self.FONT_HEADER)

        style.configure("TNotebook", background=self.COL_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.COL_PANEL_ALT, foreground=self.COL_TEXT_DIM,
                         padding=(14, 8), font=self.FONT_UI_BOLD, borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", self.COL_PANEL)],
                  foreground=[("selected", self.COL_ACCENT)])

        style.configure("TSeparator", background=self.COL_BORDER)

        style.configure("TCombobox", fieldbackground=self.COL_PANEL_ALT, background=self.COL_PANEL_ALT,
                         foreground=self.COL_TEXT, arrowcolor=self.COL_ACCENT, borderwidth=0)
        style.map("TCombobox", fieldbackground=[("readonly", self.COL_PANEL_ALT)])

        # ttk.Button intentionally not restyled here - the app still uses tk.Button
        # throughout (for per-button bg colors); _theme_walk() below remaps those.

    # Old pastel bg -> new glass-cockpit accent, keeps each button's original
    # semantic color-coding (green=go, amber=caution, blue=info, purple=file).
    BUTTON_COLOR_MAP = {
        "#d9ead3": "#1f6f4a",  # Send (radio) - green
        "#fff2cc": "#8a6d1f",  # SWAP - amber
        "#cfe2f3": "#1f6f8f",  # Fetch OFP / Fetch METAR - blue
        "#d9d2e9": "#4a3f70",  # Browse main.mcf - purple
        "#b6d7a8": "#1f8a52",  # Launch Normal - bright green
        "#a4c2f4": "#1f6fbf",  # Launch VR - bright blue
    }

    def _theme_walk(self, widget):
        """Recursively re-colors every plain tk (non-ttk) widget under `widget` to match
        the glass-cockpit theme, inheriting each parent's background so nested frames
        stay consistent. Run once after the UI tree is fully built."""
        for child in widget.winfo_children():
            cls = child.winfo_class()
            try:
                parent_bg = widget.cget("bg")
            except tk.TclError:
                parent_bg = self.COL_PANEL

            if cls == "Frame":
                child.configure(bg=parent_bg)
            elif cls == "Label":
                child.configure(bg=parent_bg)
            elif cls == "Entry":
                child.configure(bg=self.COL_PANEL_ALT, fg=self.COL_TEXT, insertbackground=self.COL_ACCENT,
                                 readonlybackground=self.COL_PANEL_ALT,
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=self.COL_BORDER, highlightcolor=self.COL_ACCENT)
            elif cls == "Text":
                child.configure(bg=self.COL_PANEL_ALT, fg=self.COL_TEXT, insertbackground=self.COL_ACCENT,
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=self.COL_BORDER, highlightcolor=self.COL_ACCENT)
            elif cls == "Checkbutton":
                child.configure(bg=parent_bg, fg=self.COL_TEXT, selectcolor=self.COL_PANEL_ALT,
                                 activebackground=parent_bg, activeforeground=self.COL_TEXT)
            elif cls == "Button":
                cur_bg = child.cget("bg")
                new_bg = self.BUTTON_COLOR_MAP.get(cur_bg, self.COL_PANEL_ALT)
                child.configure(bg=new_bg, fg="#ffffff" if new_bg != self.COL_PANEL_ALT else self.COL_TEXT,
                                 activebackground=self.COL_ACCENT, activeforeground=self.COL_BG,
                                 relief="flat", bd=0, cursor="hand2")

            self._theme_walk(child)

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
        self.custom_exe_path = self._load_exe_path_config()
        self.runways_cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runways_cache.csv')
        self._uid_gen_context = {}
        self._installed_liveries_cache = {}   # aerofly aircraft name -> [livery folder names]
        self._airline_logo_image = None       # keeps the tk.PhotoImage alive (tkinter GCs it otherwise)

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
        self.tab_log = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_simbrief, text="SimBrief")
        self.notebook.add(self.tab_weather, text="Weather")
        self.notebook.add(self.tab_basic, text="Base Systems")
        self.notebook.add(self.tab_fo, text="Radio Panel")
        self.notebook.add(self.tab_log, text="Log")

        self._build_tab_basic()
        self._build_tab_fo()
        self._build_tab_simbrief()
        self._build_tab_weather()
        self._build_tab_log()
        self._build_bottom_bar()

        self._populate_aircraft_combo()

        # Re-colors every plain tk widget (Entry/Text/Button/etc.) to match the
        # ttk theme above - must run after every tab/widget exists.
        self._theme_walk(self.root)

    def _add_label_row(self, parent, row, label_text, key, width=30, columnspan=1):
        """Helper: add a bold caption + a value label, and register the value label in self.values."""
        ttk.Label(parent, text=label_text, font=self.FONT_UI_BOLD).grid(row=row, column=0, sticky="w", padx=10, pady=5)
        val_label = ttk.Label(parent, text="---", style="Data.TLabel", width=width, anchor="w")
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
        """Radio Panel: laid out like a real COM radio - Active / SWAP / Standby / Send."""
        row = 0

        ttk.Label(self.tab_fo, text="", width=8).grid(row=row, column=0, padx=10, pady=2)
        ttk.Label(self.tab_fo, text="ACTIVE", font=("Arial", 9, "bold")).grid(row=row, column=1, pady=2)
        ttk.Label(self.tab_fo, text="STBY", font=("Arial", 9, "bold")).grid(row=row, column=3, pady=2)
        row += 1

        def radio_row(label, active_key, stby_entry_attr, send_cmd, swap_cmd):
            nonlocal row
            ttk.Label(self.tab_fo, text=label, font=("Arial", 11, "bold")).grid(row=row, column=0, sticky="e", padx=10, pady=8)

            # Active is a real (readonly) Entry, not a Label - so _theme_walk() styles it
            # with the exact same bg/border/font as the STBY Entry below, guaranteeing they
            # look identical rather than two different widgets approximating each other.
            active_entry = tk.Entry(self.tab_fo, width=9, font=self.FONT_DATA_FREQ, justify="center", state="readonly")
            active_entry.grid(row=row, column=1, padx=5, pady=8)
            self.values[active_key] = active_entry

            tk.Button(self.tab_fo, text="\u21c4 SWAP", font=("Arial", 9, "bold"), bg="#fff2cc", command=swap_cmd).grid(row=row, column=2, padx=8, pady=8)

            stby_entry = tk.Entry(self.tab_fo, width=9, font=self.FONT_DATA_FREQ, justify="center")
            stby_entry.grid(row=row, column=3, padx=5, pady=8)
            setattr(self, stby_entry_attr, stby_entry)

            tk.Button(self.tab_fo, text="Send", font=("Arial", 8), bg="#d9ead3", command=send_cmd).grid(row=row, column=4, padx=5, pady=8)

            row += 1

        radio_row("COM1", "com1_active", "com1_stby_entry", self.send_com1_stby, self.swap_com1)
        radio_row("COM2", "com2_active", "com2_stby_entry", self.send_com2_stby, self.swap_com2)

        ttk.Separator(self.tab_fo, orient="horizontal").grid(row=row, column=0, columnspan=5, sticky="ew", padx=10, pady=10)
        row += 1

        ttk.Label(self.tab_fo, text="Squawk", font=("Arial", 11, "bold")).grid(row=row, column=0, sticky="e", padx=10, pady=8)
        squawk_entry = tk.Entry(self.tab_fo, width=9, font=self.FONT_DATA_FREQ, justify="center", state="readonly")
        squawk_entry.grid(row=row, column=1, padx=5, pady=8)
        self.values["squawk"] = squawk_entry

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

        ttk.Label(self.tab_simbrief, text="Flight plan mode:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="w", padx=10, pady=5)
        self.flight_plan_mode_var = tk.StringVar(value="Pre-load")
        flight_plan_mode_combo = ttk.Combobox(
            self.tab_simbrief, textvariable=self.flight_plan_mode_var,
            values=["Full load", "Pre-load", "Empty"], width=12, state="readonly"
        )
        flight_plan_mode_combo.grid(row=row, column=1, sticky="w", padx=10, pady=5)
        row += 1

        ttk.Label(
            self.tab_simbrief,
            text="Note: Full load stages every navlog waypoint. Pre-load stages only origin/destination\n"
                 "+ runways. Empty clears the route entirely. Weather and real time are staged either way.",
            font=("Arial", 8, "italic"), foreground="gray"
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=10, pady=5)
        row += 1

        ttk.Label(self.tab_simbrief, text="Aircraft:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="w", padx=10, pady=5)
        self.aircraft_combo = ttk.Combobox(self.tab_simbrief, values=[], width=20, state="readonly")
        self.aircraft_combo.grid(row=row, column=1, sticky="w", padx=10, pady=5)
        self.aircraft_combo.bind("<<ComboboxSelected>>", self._on_aircraft_override)
        row += 1

        ttk.Label(self.tab_simbrief, text="Livery:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="w", padx=10, pady=5)
        self.livery_combo = ttk.Combobox(self.tab_simbrief, values=[], width=30, state="readonly")
        self.livery_combo.grid(row=row, column=1, sticky="w", padx=10, pady=5)
        self.livery_combo.bind("<<ComboboxSelected>>", self._on_livery_override)
        self.airline_logo_label = tk.Label(self.tab_simbrief, text="", font=("Arial", 8, "italic"), fg="gray")
        self.airline_logo_label.grid(row=row, column=2, sticky="w", padx=5, pady=5)
        row += 1

        # Kept as a hidden widget (never grid()ed) so _stage_simbrief_route()'s status
        # updates have somewhere to land - the line itself was flagged as clutter.
        self.values["sb_route_stage"] = ttk.Label(self.tab_simbrief, text="", style="Data.TLabel")
        row += 1

        # Full route gets its own multi-line box - a single-line label was cutting it off
        ttk.Label(self.tab_simbrief, text="Full Route:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="nw", padx=10, pady=5)
        self.sb_route_text = tk.Text(self.tab_simbrief, height=3, width=58, font=("Consolas", 9), wrap="word")
        self.sb_route_text.grid(row=row, column=1, columnspan=2, sticky="w", padx=10, pady=5)
        self.sb_route_text.config(state="disabled")

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
            ("QNH:", "wx_qnh"),
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

        ttk.Separator(self.tab_weather, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", padx=10, pady=10)
        row += 1

        ttk.Label(self.tab_weather, text="Destination METAR (informational only):", font=("Arial", 10, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=10, pady=5)
        row += 1

        self._add_label_row(self.tab_weather, row, "Raw METAR:", "dest_wx_raw", width=45, columnspan=2)
        row += 1

        dest_fields = [
            ("Wind:", "dest_wx_wind"),
            ("Visibility:", "dest_wx_visibility"),
            ("Clouds:", "dest_wx_clouds"),
            ("Temperature:", "dest_wx_temp"),
            ("QNH:", "dest_wx_qnh"),
        ]
        for label, key in dest_fields:
            self._add_label_row(self.tab_weather, row, label, key, width=35, columnspan=2)
            row += 1

        ttk.Label(
            self.tab_weather,
            text="Auto-filled from your SimBrief destination airport on Fetch OFP - reference only,\n"
                 "never written to main.mcf (only the departure weather above is staged).",
            font=("Arial", 8, "italic"), foreground="gray"
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=10, pady=5)
        row += 1

        # Kept as a hidden widget (never grid()ed) so fetch_weather_metar()'s status
        # updates have somewhere to land - the line itself was flagged as clutter.
        self.weather_status = tk.Label(self.tab_weather, text="No weather fetched yet.", font=("Arial", 8, "italic"), fg="gray")

    def _build_tab_log(self):
        """Log: everything the app would otherwise only print to a terminal - so the
        app can be run without keeping a console window open."""
        self.log_text = scrolledtext.ScrolledText(
            self.tab_log, wrap="word", font=("Consolas", 9), state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        tk.Button(self.tab_log, text="Clear Log", font=("Arial", 9), bg="#d9d2e9",
                  command=self.clear_log).pack(anchor="w", padx=10, pady=(0, 10))

    def log(self, message):
        """Thread-safe: appends a timestamped line to the Log tab. Safe to call from
        any thread (websocket, runway lookup, etc.) - schedules the actual widget
        update on the main thread."""
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}"
        self.root.after(0, self._append_log_line, line)

    def _append_log_line(self, line):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")

    def _build_bottom_bar(self):
        """Path config + Status + Launch controls, visible under every tab."""
        control_frame = tk.Frame(self.root)
        control_frame.pack(fill="x", padx=10, pady=5)

        paths_frame = tk.Frame(control_frame)
        paths_frame.pack(fill="x", pady=(0, 5))

        tk.Button(paths_frame, text="Browse main.mcf...", font=("Arial", 9), bg="#d9d2e9", command=self.browse_mcf).grid(row=0, column=0, padx=5, pady=3, sticky="w")
        detected_mcf = self.find_mcf_path()
        self.mcf_path_label = tk.Label(
            paths_frame, text=detected_mcf or "(not found - click Browse to select main.mcf)",
            font=("Arial", 8), fg="green" if detected_mcf else "red"
        )
        self.mcf_path_label.grid(row=0, column=1, sticky="w", padx=5, pady=3)

        ttk.Separator(control_frame, orient="horizontal").pack(fill="x", pady=5)

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
        if key not in self.values:
            return
        widget = self.values[key]
        if isinstance(widget, tk.Entry):
            # Readonly entries (the Active frequency box) can't take a plain .config(text=...) -
            # briefly unlock, replace the content, then relock.
            was_readonly = widget.cget("state") == "readonly"
            if was_readonly:
                widget.config(state="normal")
            widget.delete(0, tk.END)
            widget.insert(0, value)
            if was_readonly:
                widget.config(state="readonly")
        else:
            widget.config(text=value)

    def set_status(self, text, color):
        self.status_label.config(text=text, fg=color)

    # ==========================================================
    # main.mcf: PATH HANDLING + LOW-LEVEL EDITING
    # ==========================================================
    def _load_bridge_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_bridge_config(self, **updates):
        """Merge-and-save so mcf_path/exe_path/etc. don't clobber each other."""
        cfg = self._load_bridge_config()
        cfg.update(updates)
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f)
        except Exception:
            pass

    def _load_mcf_path_config(self):
        path = self._load_bridge_config().get('mcf_path')
        return path if path and os.path.exists(path) else None

    def _load_exe_path_config(self):
        path = self._load_bridge_config().get('exe_path')
        return path if path and os.path.exists(path) else None

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
            self._save_bridge_config(mcf_path=path)
            self.mcf_path_label.config(text=path, fg="green")

    def find_exe_path(self):
        """Locate aerofly_fs_4.exe - needed to launch VR mode reliably (see launch_aerofly).
        No manual override in the UI any more, so this needs to actually find it: reads
        Steam's own install path from the registry, then every library folder the user has
        added (via libraryfolders.vdf), rather than guessing a couple of common paths.
        """
        if self.custom_exe_path and os.path.exists(self.custom_exe_path):
            return self.custom_exe_path

        for library_root in self._steam_library_roots():
            candidate = os.path.join(library_root, 'steamapps', 'common',
                                      'Aerofly FS 4 Flight Simulator', 'bin64_windows', 'aerofly_fs_4.exe')
            if os.path.exists(candidate):
                return candidate

        # Last-resort guesses, in case the registry/vdf lookup above found nothing
        # (e.g. a non-Steam registry state) but Steam is still in its default spot.
        for path in [
            r"C:\Program Files (x86)\Steam\steamapps\common\Aerofly FS 4 Flight Simulator\bin64_windows\aerofly_fs_4.exe",
            r"C:\Program Files\Steam\steamapps\common\Aerofly FS 4 Flight Simulator\bin64_windows\aerofly_fs_4.exe",
        ]:
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def _steam_library_roots():
        """Every Steam library folder on this machine: Steam's own install path from the
        registry, plus every additional library listed in its libraryfolders.vdf - covers
        custom install drives, not just the default C:\\Program Files (x86)\\Steam."""
        roots = []
        try:
            import winreg
            reg_lookups = [
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ]
            for hive, subkey, value_name in reg_lookups:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        steam_path, _ = winreg.QueryValueEx(key, value_name)
                        steam_path = os.path.normpath(steam_path)
                        if steam_path not in roots:
                            roots.append(steam_path)
                except OSError:
                    continue
        except ImportError:
            pass  # not running on Windows (e.g. during development)

        all_roots = list(roots)
        for steam_path in roots:
            vdf_path = os.path.join(steam_path, 'steamapps', 'libraryfolders.vdf')
            try:
                with open(vdf_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                for m in re.finditer(r'"path"\s*"([^"]+)"', content):
                    lib_path = os.path.normpath(m.group(1).replace('\\\\', '\\'))
                    if lib_path not in all_roots:
                        all_roots.append(lib_path)
            except Exception:
                continue

        return all_roots



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
    def heading_to_ecef_direction(lat_deg, lon_deg, heading_deg_true):
        """Convert a true heading (degrees, measured clockwise from North) at a given lat/lon
        into a unit direction vector in the ECEF frame, using the local North/East tangent
        vectors at that point. Unlike lla_to_ecef, this hasn't been empirically cross-checked
        against a known-good Aerofly sample - verify visually in-sim after use."""
        lat = math.radians(lat_deg)
        lon = math.radians(lon_deg)
        hdg = math.radians(heading_deg_true)
        # Local tangent-plane North and East unit vectors, expressed in ECEF:
        north = (-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat))
        east = (-math.sin(lon), math.cos(lon), 0.0)
        dx = math.cos(hdg) * north[0] + math.sin(hdg) * east[0]
        dy = math.cos(hdg) * north[1] + math.sin(hdg) * east[1]
        dz = math.cos(hdg) * north[2] + math.sin(hdg) * east[2]
        return dx, dy, dz

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

    # ==========================================================
    # RUNWAY DATA (OurAirports runways.csv, cached locally)
    # ==========================================================
    def _ensure_runways_cache(self):
        """Downloads OurAirports' public runways.csv the first time it's needed, and re-downloads
        it if the local cache is older than RUNWAYS_CACHE_MAX_AGE_DAYS. Returns True if a usable
        cache file is available afterwards."""
        if os.path.exists(self.runways_cache_path):
            age_days = (time.time() - os.path.getmtime(self.runways_cache_path)) / 86400
            if age_days < self.RUNWAYS_CACHE_MAX_AGE_DAYS:
                return True
        try:
            with urllib.request.urlopen(self.RUNWAYS_CSV_URL, timeout=30) as resp:
                data = resp.read()
            with open(self.runways_cache_path, 'wb') as f:
                f.write(data)
            return True
        except Exception as e:
            self.log(f"Could not download runways.csv: {e}")
            return os.path.exists(self.runways_cache_path)  # fall back to a stale cache, if any

    def find_runway(self, icao, rwy_ident):
        """Look up one runway end for an airport in the cached OurAirports runways.csv.
        Returns a dict with lat/lon/elev_m/heading_deg/length_m, or None if not found."""
        if not rwy_ident or not self._ensure_runways_cache():
            return None
        rwy_ident = rwy_ident.strip().upper()
        try:
            with open(self.runways_cache_path, 'r', encoding='utf-8', newline='') as f:
                for row in csv.DictReader(f):
                    if row.get('airport_ident', '').upper() != icao.upper():
                        continue
                    for prefix in ('le_', 'he_'):
                        if row.get(f'{prefix}ident', '').strip().upper() != rwy_ident:
                            continue
                        try:
                            lat = float(row[f'{prefix}latitude_deg'])
                            lon = float(row[f'{prefix}longitude_deg'])
                        except (ValueError, KeyError):
                            return None  # runway found but has no coordinates in the dataset
                        elev_ft = row.get(f'{prefix}elevation_ft') or row.get('le_elevation_ft') or 0
                        heading = row.get(f'{prefix}heading_degT') or 0
                        length_ft = row.get('length_ft') or 0
                        return {
                            'lat': lat, 'lon': lon,
                            'elev_m': float(elev_ft or 0) * 0.3048,
                            'heading_deg': float(heading or 0),
                            'length_m': float(length_ft or 0) * 0.3048,
                        }
        except Exception as e:
            self.log(f"Runway lookup error for {icao}/{rwy_ident}: {e}")
        return None

    # --- The OFFICIAL Aerofly UID formula, confirmed directly from IPACS developer
    # Jan's own C++ source code (WorldGridFromLonLat / UidFromWorldGrid). Validated
    # to exact, bit-perfect matches on 96/101 real captured UIDs (the other 5 were
    # within 1-4 units, consistent with our own transcription rounding, not a
    # formula error). This constant is Aerofly's own "world grid" latitude scaling
    # factor - the same one also used in their WAD ground-layout coordinate system. ---
    WORLD_GRID_CONSTANT_A = 2.33112237041144

    @classmethod
    def generate_uid(cls, lat_deg, lon_deg, low16):
        """Generates a full 64-bit UID purely from coordinates + a type code, using
        Aerofly's own official world-grid formula:
          - High24 (bits 40-63): x = 0.5 + 0.5*(lon_rad/pi)
          - Mid24  (bits 16-39): y = 0.5 + 0.5*( tan(A * lat_rad/pi) / A )
          - Low16  (bits 0-15):  type code (airport/runway/waypoint/etc.)
        Both x and y are then scaled by 65536*256 = 2^24 and rounded (matching the
        C++ static_cast<uint64>(v + 0.5) truncate-after-add-0.5 rounding)."""
        A = cls.WORLD_GRID_CONSTANT_A
        lon_rad = math.radians(lon_deg)
        lat_rad = math.radians(lat_deg)

        x = lon_rad / math.pi
        if x > 1.0:
            x -= 2.0
        elif x < -1.0:
            x += 2.0
        y = math.tan(A * (lat_rad / math.pi)) / A

        x = 0.5 + 0.5 * x
        y = 0.5 + 0.5 * y

        high24 = int(65536.0 * 256.0 * x + 0.5)
        mid24 = int(65536.0 * 256.0 * y + 0.5)

        return (high24 << 40) | (mid24 << 16) | low16

    def uid_line(self, indent, identifier):
        """Returns a Uid line for this identifier, computed with Aerofly's own
        official world-grid formula (generate_uid), from whatever coordinate we
        have on hand for it (SimBrief/OurAirports). Returns an empty string if we
        don't even have a coordinate for this identifier (e.g. a placeholder
        SID/STAR/Approach with no real position)."""
        info = self._uid_gen_context.get(identifier)
        if info is None:
            return ""
        lat, lon, low16 = info
        uid = self.generate_uid(lat, lon, low16)
        return f"{indent}<[uint64][Uid][{uid}]>\n"

    def build_route_block(self, base_indent, origin, destination, cruise_alt_m,
                           dep_runway=None, dest_runway=None, waypoints=None, include_procedures=False):
        """Builds a replacement 'tmnav_route' block. Origin/Destination are always included;
        departure/destination runway entries are added too when runway data was found
        (via OurAirports), matching the structure Aerofly needs to populate its own
        departure/arrival runway selector. If `waypoints` is given (a list of
        {ident, lat, lon} dicts, e.g. from a SimBrief navlog), each is inserted into
        the Ways list as an RNAV waypoint between the departure and arrival ends.
        The empty SID/STAR/Approach placeholder nodes are only added when
        `include_procedures` is true (Flight plan mode 'Full load') - they're an
        experimental, waypoint-list-specific test, not something Pre-load's simpler
        origin/destination/runway staging needs.

        Every Uid is computed with Aerofly's own official world-grid formula
        (generate_uid) from whatever coordinate we have (SimBrief/OurAirports)."""
        ind = " " * base_indent
        i1, i2, i3 = ind + "    ", ind + "        ", ind + "            "
        ox, oy, oz = self.lla_to_ecef(origin['lat'], origin['lon'], origin['elev_m'])
        dx, dy, dz = self.lla_to_ecef(destination['lat'], destination['lon'], destination['elev_m'])

        # Context uid_line() uses to compute a Uid when no captured real value exists.
        self._uid_gen_context = {
            origin['icao']: (origin['lat'], origin['lon'], 0x0500),
            destination['icao']: (destination['lat'], destination['lon'], 0x0500),
        }
        if dep_runway:
            self._uid_gen_context[f"{origin['icao']}/{dep_runway['ident']}"] = (
                dep_runway['lat'], dep_runway['lon'], 0x0800)
        if dest_runway:
            self._uid_gen_context[f"{destination['icao']}/{dest_runway['ident']}"] = (
                dest_runway['lat'], dest_runway['lon'], 0x0800)
        if waypoints:
            for i, wpt in enumerate(waypoints):
                self._uid_gen_context[f"WPT_{i}"] = (wpt['lat'], wpt['lon'], 0xC000)

        lines = [
            f"{ind}<[tmnav_route][Route][]\n",
            f"{i1}<[float64][CruiseAltitude][{cruise_alt_m:.2f}]>\n",
            f"{i1}<[pointer_list_tmnav_route_way][Ways][]\n",
            f"{i2}<[tmnav_route_origin][{origin['icao']}][0]\n",
            f"{i3}<[string8u][Identifier][{origin['icao']}]>\n",
            f"{i3}<[vector3_float64][Position][{ox:.6f} {oy:.6f} {oz:.6f}]>\n",
            self.uid_line(i3, origin['icao']),
            f"{i3}<[float64][Elevation][{origin['elev_m']:.4f}]>\n",
            f"{i2}>\n",
        ]

        way_index = 1
        if dep_runway:
            rx, ry, rz = self.lla_to_ecef(dep_runway['lat'], dep_runway['lon'], dep_runway['elev_m'])
            dirx, diry, dirz = self.heading_to_ecef_direction(dep_runway['lat'], dep_runway['lon'], dep_runway['heading_deg'])
            lines += [
                f"{i2}<[tmnav_route_departure_runway][{dep_runway['ident']}][{way_index}]\n",
                f"{i3}<[string8u][Identifier][{dep_runway['ident']}]>\n",
                f"{i3}<[vector3_float64][Position][{rx:.6f} {ry:.6f} {rz:.6f}]>\n",
                self.uid_line(i3, f"{origin['icao']}/{dep_runway['ident']}"),
                f"{i3}<[vector3_float64][Direction][{dirx:.6f} {diry:.6f} {dirz:.6f}]>\n",
                f"{i3}<[float64][Elevation][{dep_runway['elev_m']:.4f}]>\n",
                f"{i3}<[float64][RunwayLength][{dep_runway['length_m']:.4f}]>\n",
                f"{i2}>\n",
            ]
            way_index += 1

            if include_procedures:
                # Empty SID placeholder, matching the 'tmnav_route_departure' structure seen in a
                # known-working file (experimental: testing whether this connector node - even empty -
                # is what triggers Aerofly's own runway-list lookup, as opposed to real SID data)
                lines += [
                    f"{i2}<[tmnav_route_departure][][{way_index}]\n",
                    f"{i3}<[string8u][Identifier][]>\n",
                    f"{i3}<[vector3_float64][Position][0 0 0]>\n",
                    f"{i3}<[list_tmnav_route_modification][Modifications][]\n",
                    f"{i3}>\n",
                    f"{i3}<[string8u][Airport][{origin['icao']}]>\n",
                    f"{i3}<[vector3_float64][Direction][0 0 0]>\n",
                    f"{i3}<[float64][Elevation][0]>\n",
                    f"{i3}<[string8u][Transition][]>\n",
                    f"{i2}>\n",
                ]
                way_index += 1

        if waypoints:
            for i, wpt in enumerate(waypoints):
                wx, wy, wz = self.lla_to_ecef(wpt['lat'], wpt['lon'], 0)
                lines += [
                    f"{i2}<[tmnav_route_waypoint][{wpt['ident']}][{way_index}]\n",
                    f"{i3}<[string8u][Identifier][{wpt['ident']}]>\n",
                    f"{i3}<[vector3_float64][Position][{wx:.6f} {wy:.6f} {wz:.6f}]>\n",
                    self.uid_line(i3, f"WPT_{i}"),
                    f"{i3}<[float64][NavaidFrequency][0]>\n",
                    f"{i3}<[uint64][NavaidUid][0]>\n",
                    f"{i3}<[vector2_float64][Altitude][-1001 100001]>\n",
                    f"{i3}<[bool][FlyOver][false]>\n",
                    f"{i3}<[bool][ViaPoint][false]>\n",
                    f"{i2}>\n",
                ]
                way_index += 1

        if dest_runway:
            if include_procedures:
                # Empty STAR placeholder ('tmnav_route_arrival'), same experimental rationale as above
                lines += [
                    f"{i2}<[tmnav_route_arrival][][{way_index}]\n",
                    f"{i3}<[string8u][Identifier][]>\n",
                    f"{i3}<[vector3_float64][Position][0 0 0]>\n",
                    f"{i3}<[list_tmnav_route_modification][Modifications][]\n",
                    f"{i3}>\n",
                    f"{i3}<[string8u][Airport][{destination['icao']}]>\n",
                    f"{i3}<[vector3_float64][Direction][0 0 0]>\n",
                    f"{i3}<[float64][Elevation][0]>\n",
                    f"{i2}>\n",
                ]
                way_index += 1

                # Empty Approach placeholder
                lines += [
                    f"{i2}<[tmnav_route_approach][][{way_index}]\n",
                    f"{i3}<[string8u][Identifier][]>\n",
                    f"{i3}<[vector3_float64][Position][0 0 0]>\n",
                    f"{i3}<[list_tmnav_route_modification][Modifications][]\n",
                    f"{i3}>\n",
                    f"{i3}<[string8u][Airport][{destination['icao']}]>\n",
                    f"{i3}<[vector3_float64][Direction][0 0 0]>\n",
                    f"{i3}<[float64][Elevation][0]>\n",
                    f"{i3}<[string8u][Transition][]>\n",
                    f"{i2}>\n",
                ]
                way_index += 1

            rx, ry, rz = self.lla_to_ecef(dest_runway['lat'], dest_runway['lon'], dest_runway['elev_m'])
            dirx, diry, dirz = self.heading_to_ecef_direction(dest_runway['lat'], dest_runway['lon'], dest_runway['heading_deg'])
            lines += [
                f"{i2}<[tmnav_route_destination_runway][{dest_runway['ident']}][{way_index}]\n",
                f"{i3}<[string8u][Identifier][{dest_runway['ident']}]>\n",
                f"{i3}<[vector3_float64][Position][{rx:.6f} {ry:.6f} {rz:.6f}]>\n",
                self.uid_line(i3, f"{destination['icao']}/{dest_runway['ident']}"),
                f"{i3}<[vector3_float64][Direction][{dirx:.6f} {diry:.6f} {dirz:.6f}]>\n",
                f"{i3}<[float64][Elevation][{dest_runway['elev_m']:.4f}]>\n",
                f"{i3}<[float64][RunwayLength][{dest_runway['length_m']:.4f}]>\n",
                f"{i2}>\n",
            ]
            way_index += 1

        lines += [
            f"{i2}<[tmnav_route_destination][{destination['icao']}][{way_index}]\n",
            f"{i3}<[string8u][Identifier][{destination['icao']}]>\n",
            f"{i3}<[vector3_float64][Position][{dx:.6f} {dy:.6f} {dz:.6f}]>\n",
            self.uid_line(i3, destination['icao']),
            f"{i3}<[float64][Elevation][{destination['elev_m']:.4f}]>\n",
            f"{i2}>\n",
            f"{i1}>\n",
            f"{ind}>\n",
        ]
        return lines

    def build_empty_route_block(self, base_indent):
        """A route block with no origin/destination/waypoints at all - used by Flight
        plan mode 'Empty' to actually blank out whatever route Aerofly already has
        loaded, rather than just leaving it untouched."""
        ind = " " * base_indent
        i1 = ind + "    "
        return [
            f"{ind}<[tmnav_route][Route][]\n",
            f"{i1}<[float64][CruiseAltitude][0.00]>\n",
            f"{i1}<[pointer_list_tmnav_route_way][Ways][]\n",
            f"{i1}>\n",
            f"{ind}>\n",
        ]

    def clear_route_from_lines(self, lines):
        """Blanks out main.mcf's route block entirely - used by Flight plan mode 'Empty'."""
        start, end = self.find_block_range(lines, "[tmnav_route][Route]")
        if start is None or end is None:
            return False
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        lines[start:end + 1] = self.build_empty_route_block(base_indent)
        return True

    def apply_route_to_lines(self, lines):
        if not self.pending_route:
            return False
        start, end = self.find_block_range(lines, "[tmnav_route][Route]")
        if start is None or end is None:
            return False
        base_indent = len(lines[start]) - len(lines[start].lstrip())

        # Read the current mode here (not whatever it was when SimBrief was fetched),
        # so switching modes after a fetch takes effect immediately on next Launch.
        full_load = self.flight_plan_mode_var.get() == "Full load"

        new_block = self.build_route_block(
            base_indent,
            self.pending_route['origin'],
            self.pending_route['destination'],
            self.pending_route['cruise_alt_m'],
            self.pending_route.get('dep_runway'),
            self.pending_route.get('dest_runway'),
            self.pending_route.get('waypoints') if full_load else None,
            include_procedures=full_load,
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
    def _fetch_and_parse_metar(self, icao):
        """Fetches and parses one airport's METAR. Returns a dict of parsed fields.
        Raises on failure (no data, network error, etc.) - callers decide how to
        surface that (a messagebox for a direct user click, self.log() for the
        automatic destination fetch)."""
        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data:
            raise ValueError(f"No METAR found for {icao}")
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

        return {
            'raw': raw, 'wind_dir': wind_dir, 'wind_kt': wind_kt,
            'visib_sm': visib_sm, 'visib_m': visib_m, 'temp_c': temp_c,
            'altim_hpa': altim_hpa, 'cloud_base_ft': cloud_base_ft,
            'wind_pct': wind_pct, 'visibility_pct': visibility_pct,
            'cloud_density': cloud_density, 'cloud_height_pct': cloud_height_pct,
        }

    def fetch_weather_metar(self):
        icao = self.weather_icao_entry.get().strip().upper()
        if not icao:
            return
        try:
            w = self._fetch_and_parse_metar(icao)

            self.pending_weather = {
                'wind_pct': w['wind_pct'], 'wind_dir': w['wind_dir'],
                'visibility_pct': w['visibility_pct'],
                'cloud_density': w['cloud_density'], 'cloud_height_pct': w['cloud_height_pct'],
            }

            self.update_ui("wx_raw", w['raw'])
            self.update_ui("wx_wind", f"{w['wind_dir']:.0f}° @ {w['wind_kt']:.0f} kt")
            self.update_ui("wx_visibility", f"{w['visib_sm']:.1f} SM (~{w['visib_m']:.0f} m)")
            self.update_ui("wx_clouds", f"{w['cloud_base_ft']:.0f} ft AGL" if w['cloud_base_ft'] else "Clear / few")
            self.update_ui("wx_temp", f"{w['temp_c']}°C" if w['temp_c'] is not None else "---")
            self.update_ui("wx_qnh", f"{w['altim_hpa']} hPa")
            self.weather_status.config(text=f"Weather for {icao} parsed and staged - applied on your next Launch.", fg="blue")

        except Exception as e:
            messagebox.showerror("Weather fetch error", f"Could not fetch METAR:\n{e}")

    def fetch_destination_metar_async(self, icao):
        """Fetches the destination airport's METAR for informational display only - it's
        never staged into main.mcf (that stays departure-weather-only, unchanged). Runs on
        a background thread since this fires automatically right after a SimBrief fetch,
        not from a direct button click."""
        def worker():
            try:
                w = self._fetch_and_parse_metar(icao)
                self.root.after(0, self._display_destination_metar, w)
            except Exception as e:
                self.log(f"Destination METAR fetch failed for {icao}: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _display_destination_metar(self, w):
        self.update_ui("dest_wx_raw", w['raw'])
        self.update_ui("dest_wx_wind", f"{w['wind_dir']:.0f}° @ {w['wind_kt']:.0f} kt")
        self.update_ui("dest_wx_visibility", f"{w['visib_sm']:.1f} SM (~{w['visib_m']:.0f} m)")
        self.update_ui("dest_wx_clouds", f"{w['cloud_base_ft']:.0f} ft AGL" if w['cloud_base_ft'] else "Clear / few")
        self.update_ui("dest_wx_temp", f"{w['temp_c']}°C" if w['temp_c'] is not None else "---")
        self.update_ui("dest_wx_qnh", f"{w['altim_hpa']} hPa")

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

            flight_plan_mode = self.flight_plan_mode_var.get()

            if flight_plan_mode != "Empty" and self.pending_aircraft:
                name, paintscheme = self.pending_aircraft
                self.replace_mcf_value(lines, "name", name)
                if paintscheme:
                    self.replace_mcf_value(lines, "paintscheme", paintscheme)
                applied_parts.append("aircraft")

            if flight_plan_mode == "Empty":
                if self.clear_route_from_lines(lines):
                    applied_parts.append("route cleared (Empty mode)")
            elif self.pending_route and self.apply_route_to_lines(lines):
                applied_parts.append("route (origin/destination/cruise alt)")

            # Kept in sync for reference/compatibility, but note: Steam's own
            # "rungameid" launch (used below when no .exe path is set) ignores this
            # flag entirely - it always uses whichever VR/Desktop choice was last
            # made in Steam itself. Only launching the .exe directly with -openvr
            # reliably forces VR mode. See the Weather tab note.
            self.replace_mcf_value(lines, "vr_use_openvr", "true" if vr else "false")

            with open(mcf_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            exe_path = self.find_exe_path() if vr else None

            if vr and exe_path:
                subprocess.Popen([exe_path, "-openvr"], cwd=os.path.dirname(exe_path))
                launch_desc = "VR mode (direct launch with -openvr)"
            else:
                os.startfile(f"steam://rungameid/{self.STEAM_APP_ID}")
                launch_desc = "Normal mode via Steam" if not vr else (
                    "VR mode via Steam (unreliable - set aerofly_fs_4.exe on the Weather "
                    "tab for a direct -openvr launch instead)"
                )

            extra = f" + staged {', '.join(applied_parts)}" if applied_parts else ""
            self.launch_status.config(
                text=f"Real time written{extra}. Launching Aerofly in {launch_desc}...",
                fg="green"
            )

        except Exception as e:
            messagebox.showerror("Error", f"Failed to prepare/launch Aerofly:\n{e}")

    # ==========================================================
    # SIMBRIEF
    # ==========================================================
    # File extensions that indicate a folder holds actual paint/texture assets
    # (a livery) rather than a config/variant folder (which holds .tmd/.tsb
    # state files instead - see the "engine_cfm"/"sharklets"/"base_ceo" folders
    # that sit next to real airline liveries in every aircraft's folder).
    LIVERY_TEXTURE_EXTENSIONS = {".tga", ".dds", ".png", ".jpg", ".jpeg", ".ttx", ".bmp"}

    def _folder_looks_like_livery(self, folder_path, max_depth=2):
        """True if `folder_path` contains a texture-like file within `max_depth`
        levels - the signal that it's a paint/livery folder, not a config/variant
        one. Config folders (engine choice, wingtip choice, ...) hold .tmd/.tsb
        files instead and won't match."""
        try:
            base_depth = folder_path.rstrip(os.sep).count(os.sep)
            for root, dirs, files in os.walk(folder_path):
                if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                    dirs[:] = []
                    continue
                for f in files:
                    if os.path.splitext(f)[1].lower() in self.LIVERY_TEXTURE_EXTENSIONS:
                        return True
        except Exception:
            pass
        return False

    def _aircraft_folder_roots(self):
        """The two places Aerofly aircraft folders live: your user add-on
        directory, and (if known) the base Steam install."""
        home_dir = os.path.expanduser('~')
        roots = [os.path.join(home_dir, 'Documents', 'Aerofly FS 4', 'aircraft')]

        exe_path = self.find_exe_path()
        if exe_path:
            # exe lives at <install_root>/bin64_windows/aerofly_fs_4.exe
            install_root = os.path.dirname(os.path.dirname(exe_path))
            roots.append(os.path.join(install_root, 'aircraft'))

        return roots

    def scan_installed_aircraft(self):
        """Lists every installed aircraft folder (user add-ons + base install),
        so the Override dropdown always matches what's actually on disk instead
        of a hand-maintained list that inevitably falls behind new installs."""
        aircraft = set()
        for aircraft_root in self._aircraft_folder_roots():
            try:
                if not os.path.isdir(aircraft_root):
                    continue
                for entry in os.listdir(aircraft_root):
                    if os.path.isdir(os.path.join(aircraft_root, entry)):
                        aircraft.add(entry)
            except Exception:
                continue
        return sorted(aircraft)

    def _populate_aircraft_combo(self):
        aircraft = self.scan_installed_aircraft()
        if not aircraft:
            # Neither folder was found/reachable yet (e.g. exe path not set) -
            # fall back to the known-types table so the dropdown isn't empty.
            aircraft = sorted(self.AIRCRAFT_DB.keys())
        self.aircraft_combo.config(values=aircraft)

    def scan_installed_liveries(self, aerofly_name):
        """Best-effort scan for installed liveries of one aircraft: lists sub-folders
        of that aircraft's folder (user add-ons + base install) that actually contain
        texture files - see _folder_looks_like_livery(). If it comes up empty or
        wrong, use main.mcf's own last-used paintscheme instead, or pick manually.
        """
        if aerofly_name in self._installed_liveries_cache:
            return self._installed_liveries_cache[aerofly_name]

        liveries = set()
        for aircraft_root in self._aircraft_folder_roots():
            root_dir = os.path.join(aircraft_root, aerofly_name)
            try:
                if not os.path.isdir(root_dir):
                    continue
                for entry in os.listdir(root_dir):
                    full = os.path.join(root_dir, entry)
                    if os.path.isdir(full) and self._folder_looks_like_livery(full):
                        liveries.add(entry)
            except Exception:
                continue

        result = sorted(liveries)
        self._installed_liveries_cache[aerofly_name] = result
        return result

    @staticmethod
    def _normalize_livery_name(name):
        """Lowercase, strip anything but letters/digits - so 'Air France', 'air_france',
        and 'AIRFRANCE' all compare equal."""
        return re.sub(r'[^a-z0-9]', '', name.lower())

    @staticmethod
    def _icao_airline_from_callsign(callsign):
        m = re.match(r'^([A-Za-z]{2,4})', callsign or "")
        return m.group(1).upper() if m else None

    def _match_livery_by_callsign(self, callsign, liveries):
        """Best-effort: extract the ICAO airline prefix from the SimBrief callsign
        (e.g. 'AFR1234' -> 'AFR'), look up a guessed livery name fragment, and
        fuzzy-match it against the installed livery folder names. Returns the
        matched folder name, or None if no ICAO_AIRLINE_INFO entry or no installed
        livery matches.
        """
        icao_code = self._icao_airline_from_callsign(callsign)
        if not icao_code or not liveries:
            return None

        info = self.ICAO_AIRLINE_INFO.get(icao_code)
        if not info:
            return None
        _, guess = info

        guess_norm = self._normalize_livery_name(guess)
        for livery in liveries:
            livery_norm = self._normalize_livery_name(livery)
            if guess_norm == livery_norm or guess_norm in livery_norm or livery_norm in guess_norm:
                return livery
        return None

    def _clear_airline_logo(self, message="(none)"):
        self._airline_logo_image = None
        self.airline_logo_label.config(image="", text=message)

    def _display_airline_logo_bytes(self, png_bytes, iata_code):
        try:
            image = tk.PhotoImage(data=png_bytes)
        except tk.TclError:
            self._clear_airline_logo(f"(logo for {iata_code} couldn't be decoded)")
            return
        self._airline_logo_image = image  # keep a reference - see _init_state
        self.airline_logo_label.config(image=image, text="")

    def _fetch_airline_logo_async(self, iata_code):
        """Downloads the airline logo from Kiwi.com's public, key-free endpoint
        (https://images.kiwi.com/airlines/64/<IATA>.png) on a background thread,
        then updates the UI on the main thread. Never raises - a failed/slow fetch
        just leaves the logo blank, since this is cosmetic and must not block or
        crash flight prep.
        """
        self._clear_airline_logo("(loading...)")

        def worker():
            try:
                url = f"https://images.kiwi.com/airlines/64/{iata_code}.png"
                with urllib.request.urlopen(url, timeout=5) as resp:
                    png_bytes = resp.read()
                self.root.after(0, self._display_airline_logo_bytes, png_bytes, iata_code)
            except Exception:
                self.root.after(0, self._clear_airline_logo, f"(no logo found for {iata_code})")

        threading.Thread(target=worker, daemon=True).start()

    def _populate_livery_combo(self, aerofly_name, force=False):
        if not aerofly_name:
            self.livery_combo.config(values=[])
            self.livery_combo.set("")
            return

        if force:
            self._installed_liveries_cache.pop(aerofly_name, None)

        liveries = self.scan_installed_liveries(aerofly_name)

        # Also offer whatever paintscheme main.mcf remembers being used last,
        # even if the folder scan above didn't find/recognize it as a livery.
        current_paintscheme = self.pending_aircraft[1] if self.pending_aircraft else ""
        if current_paintscheme and current_paintscheme not in liveries:
            liveries = sorted(set(liveries) | {current_paintscheme})

        self.livery_combo.config(values=liveries)
        if current_paintscheme:
            self.livery_combo.set(current_paintscheme)
        elif liveries:
            self.livery_combo.set(liveries[0])
        else:
            self.livery_combo.set("(none found - default livery)")

    def _on_livery_override(self, _event):
        name = self.aircraft_combo.get() or (self.pending_aircraft[0] if self.pending_aircraft else "")
        livery = self.livery_combo.get()
        if livery.startswith("(none found"):
            livery = ""
        self.pending_aircraft = (name, livery)

    def _on_aircraft_override(self, _event):
        name = self.aircraft_combo.get()
        self.pending_aircraft = (name, "")
        self._populate_livery_combo(name)

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

            dest = data.get("destination", {}).get("icao_code", "")
            if dest:
                self.fetch_destination_metar_async(dest)  # informational only - never staged

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
        self._populate_livery_combo(aerofly_name)
        self.update_ui("sb_aircraft_match", f"Matched: {aerofly_name} ({icao}) - will be applied on Launch")

        callsign = data.get("atc", {}).get("callsign", "")
        liveries = self.scan_installed_liveries(aerofly_name)
        matched_livery = self._match_livery_by_callsign(callsign, liveries)

        if matched_livery:
            self.livery_combo.set(matched_livery)
            self.pending_aircraft = (aerofly_name, matched_livery)
            self.update_ui("sb_livery_match", f"Matched via callsign {callsign}: {matched_livery}")
        elif liveries:
            self.livery_combo.set(liveries[0])
            self.pending_aircraft = (aerofly_name, liveries[0])
            self.update_ui("sb_livery_match", f"No installed livery matches callsign {callsign} - using default: {liveries[0]}")
        else:
            self.update_ui("sb_livery_match", f"No installed liveries found for {aerofly_name} - using default paint")

        icao_airline = self._icao_airline_from_callsign(callsign)
        info = self.ICAO_AIRLINE_INFO.get(icao_airline) if icao_airline else None
        if info:
            iata_code, _ = info
            self._fetch_airline_logo_async(iata_code)
        else:
            self._clear_airline_logo(f"(unknown airline for callsign {callsign})" if callsign else "(none)")

    def _stage_simbrief_route(self, data):
        try:
            origin = data.get("origin", {})
            destination = data.get("destination", {})
            cruise_ft = float(data.get("general", {}).get("initial_altitude", 0) or 0)
            orig_icao = origin.get("icao_code", "")
            dest_icao = destination.get("icao_code", "")
            orig_rwy_ident = origin.get("plan_rwy", "")
            dest_rwy_ident = destination.get("plan_rwy", "")

            self.pending_route = {
                'origin': {
                    'icao': orig_icao,
                    'lat': float(origin.get("pos_lat", 0)),
                    'lon': float(origin.get("pos_long", 0)),
                    'elev_m': float(origin.get("elevation", 0) or 0) * 0.3048,
                },
                'destination': {
                    'icao': dest_icao,
                    'lat': float(destination.get("pos_lat", 0)),
                    'lon': float(destination.get("pos_long", 0)),
                    'elev_m': float(destination.get("elevation", 0) or 0) * 0.3048,
                },
                'cruise_alt_m': cruise_ft * 0.3048,
                'dep_runway': None,
                'dest_runway': None,
                'waypoints': None,
            }

            o, d = orig_icao, dest_icao
            status = f"Staged: {o} -> {d} @ {cruise_ft:.0f} ft"

            dep_data = self.find_runway(orig_icao, orig_rwy_ident)
            if dep_data:
                self.pending_route['dep_runway'] = {**dep_data, 'ident': orig_rwy_ident.strip().upper()}
                status += f", departure RWY {orig_rwy_ident}"
            elif orig_rwy_ident:
                status += f" (RWY {orig_rwy_ident} not found in runway database - pick manually)"

            dest_data = self.find_runway(dest_icao, dest_rwy_ident)
            if dest_data:
                self.pending_route['dest_runway'] = {**dest_data, 'ident': dest_rwy_ident.strip().upper()}
                status += f", arrival RWY {dest_rwy_ident}"
            elif dest_rwy_ident:
                status += f" (RWY {dest_rwy_ident} not found in runway database - pick manually)"

            # Always compute the full waypoint list here, regardless of the current Flight
            # plan mode - which waypoints (if any) actually get written happens later, in
            # apply_route_to_lines() at Launch time, so switching modes after a fetch takes
            # effect immediately without needing to re-fetch.
            waypoints = []
            for fix in data.get("navlog", {}).get("fix", []):
                ident = (fix.get("ident") or "").strip().upper()
                try:
                    lat = float(fix.get("pos_lat", 0))
                    lon = float(fix.get("pos_long", 0))
                except (TypeError, ValueError):
                    continue
                if not ident or (lat == 0 and lon == 0):
                    continue
                # airports (origin/destination) are already handled separately -
                # skip them here so they don't appear twice in the Ways list.
                if fix.get("type") == "apt":
                    continue
                waypoints.append({'ident': ident, 'lat': lat, 'lon': lon})
            self.pending_route['waypoints'] = waypoints
            status += f", {len(waypoints)} waypoint(s) available"

            status += " - applied on next Launch."
            self.update_ui("sb_route_stage", status)
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
            self.log(f"WS payload sent: {json_str.strip()}")
        except Exception as e:
            self.log(f"Error sending WS payload: {str(e)}")

    @staticmethod
    def _raw_freq_to_mhz(raw):
        """Aerofly's COM frequency vars can come back in a few different raw scales
        depending on build/aircraft - normalize whichever one to a plain MHz float."""
        return raw / 1000000.0 if raw > 1000000 else (raw / 1000.0 if raw > 1000 else raw)

    def _sync_stby_entry(self, entry_widget, mhz_value):
        """Keeps the STBY box mirroring Aerofly's actual standby frequency, the same way
        the ACTIVE box does - but only while the user isn't actively typing in it (i.e. it
        doesn't have keyboard focus), so this live sync never overwrites what they're
        entering. Once they click elsewhere (or hit Send), it resumes following Aerofly."""
        if self.root.focus_get() is entry_widget:
            return
        current = entry_widget.get().strip()
        new_value = f"{mhz_value:.3f}"
        if current == new_value:
            return
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, new_value)

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
                        self.log(f"FO Action: setting COM1 active: {mhz_val}")
                    elif var_name == "COM_STBY_RADIO_SET_HZ":
                        self.update_entry_from_ai(self.com1_stby_entry, mhz_val)
                        self.log(f"FO Action: setting COM1 standby: {mhz_val}")
                    elif var_name == "COM2_RADIO_SET_HZ":
                        self.update_entry_from_ai(self.com2_stby_entry, mhz_val)
                        trigger_com2_swap = True
                    elif var_name == "COM2_STBY_RADIO_SET_HZ":
                        self.update_entry_from_ai(self.com2_stby_entry, mhz_val)
                    elif var_name == "XPNDR_SET":
                        self._send_ws_payload("Communication.TransponderAltitude", int(var_val))
                        self.log(f"FO Action: squawk set to: {var_val}")
                except ValueError:
                    pass

            except json.JSONDecodeError:
                pass
            except Exception as e:
                self.log(f"FO error: {e}")

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
        com1_mhz = self._raw_freq_to_mhz(raw_com1)
        raw_com2 = get_var("Communication.COM2Frequency")
        com2_mhz = self._raw_freq_to_mhz(raw_com2)
        com1_stby_mhz = self._raw_freq_to_mhz(get_var("Communication.COM1StandbyFrequency"))
        com2_stby_mhz = self._raw_freq_to_mhz(get_var("Communication.COM2StandbyFrequency"))
        try:
            # NOTE: the official Bridge offsets list calls this "Communication.TransponderCode",
            # but "Communication.TransponderAltitude" is what's confirmed working over this
            # WebSocket bridge in practice - the offsets list may use a different naming scheme
            # than the live WS variable names. Don't "fix" this back without re-testing in-sim.
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
        self.root.after(0, self.update_ui, "com1_active", f"{com1_mhz:.3f}")
        self.root.after(0, self.update_ui, "com2_active", f"{com2_mhz:.3f}")
        self.root.after(0, self._sync_stby_entry, self.com1_stby_entry, com1_stby_mhz)
        self.root.after(0, self._sync_stby_entry, self.com2_stby_entry, com2_stby_mhz)
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