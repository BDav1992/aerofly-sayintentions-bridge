# Aerofly FS4 → SayIntentions.AI Bridge

A Python desktop app that connects **Aerofly FS4** to **[SayIntentions.AI](https://sayintentions.ai)**'s
AI-powered ATC, so you can fly Aerofly with a voice-driven First Officer/ATC experience — something
neither product supports out of the box.

It streams live Aerofly telemetry into SayIntentions' file-based SimAPI, relays the radio/squawk
commands SayIntentions sends back, and helps you prepare a flight (weather, real time, aircraft,
route) before launching Aerofly.

> **Not affiliated with IPACS (Aerofly) or SayIntentions.AI.** This is an independent, community
> bridge built on top of publicly documented interfaces.

## Screenshots

*(add your own screenshots here — Base Systems tab, First Officer tab, SimBrief tab)*

## Features

- **Live telemetry → SayIntentions**: position, altitude, heading, speed, aircraft type, on-ground
  status, transponder code, ambient wind — written continuously to SayIntentions' SimAPI input file.
- **First Officer radio control**: COM1/COM2 active + standby frequencies, frequency swap, and
  squawk code — all settable by SayIntentions' voice ATC and reflected live in Aerofly.
- **SimBrief integration**: pull your OFP (route, cruise altitude, fuel, pax, cargo, ZFW) by
  username, auto-match the aircraft type to an installed Aerofly aircraft, and stage the fetched
  origin/destination + cruise altitude for your next flight.
- **Weather staging**: fetch a real METAR for any airport and stage wind/visibility/clouds into
  Aerofly's `main.mcf` for your next launch (temperature and barometric pressure can't be applied —
  see [Known Limitations](#known-limitations)).
- **One-click launch**: writes the current real-world UTC time plus any staged weather/aircraft/route,
  then launches Aerofly via Steam.

## Requirements

- Windows (uses `os.startfile` and `tasklist` — not cross-platform)
- Python 3.9+
- Aerofly FS 4, installed via Steam
- [jlgabriel/Aerofly-FS4-Bridge](https://github.com/jlgabriel/Aerofly-FS4-Bridge) — the external DLL
  that exposes Aerofly's telemetry over a local WebSocket (`ws://127.0.0.1:8765`). **This must be
  installed and running separately** — this project only consumes that WebSocket, it does not read
  Aerofly's memory directly.
- [SayIntentions.AI](https://sayintentions.ai) desktop app, running
- (Optional) A [SimBrief](https://www.simbrief.com) account, for the SimBrief tab

## Installation

```bash
git clone https://github.com/<your-username>/aerofly-sayintentions-bridge.git
cd aerofly-sayintentions-bridge
pip install -r requirements.txt
python aerofly_sayintentions_bridge.py
```

## Usage

1. Start Aerofly FS4 and the [Aerofly-FS4-Bridge](https://github.com/jlgabriel/Aerofly-FS4-Bridge) DLL.
2. Start SayIntentions.AI.
3. Run this app. The **Base Systems** tab should turn green ("FS4 Bridge: Connected") and
   "SayIntentions SimAPI: ACTIVE" once both are talking to it.
4. Optional, before your *next* flight: use the **SimBrief** tab to fetch your OFP (aircraft +
   route + cruise altitude get staged) and the **Weather** tab to fetch a METAR (wind/visibility/
   clouds get staged), then hit **Launch Normal** / **Launch VR** to apply everything and start Aerofly.

The first time you run it, if it can't auto-detect your `main.mcf` (used for weather/time/aircraft/
route staging), use **Browse main.mcf...** on the Weather tab to point it at
`Documents\Aerofly FS 4\main.mcf`. The chosen path is remembered in `bridge_config.json`.

## Known Limitations

These aren't bugs in this project — they're limits of what Aerofly currently exposes externally,
found through hands-on testing:

- **Fuel and payload cannot be set externally.** Externally-written `fuel_mass`/`payload_mass`
  values in `main.mcf` are silently ignored/reset by Aerofly on load, regardless of which tool
  writes them (confirmed with this project, with the [Aerofly Startgerät](https://github.com/fboes/aerofly-startgeraet),
  and even manually with the C172). Set fuel/payload manually in Aerofly's own Fuel & Load screen.
- **Flaps, gear, and autopilot cannot be commanded by SayIntentions.** SayIntentions' documented
  file-based SimAPI (`output_variables.txt`) only ever sends radio frequency/swap, squawk, and
  volume commands. Its richer aircraft-system control (e.g. FlyByWire A32NX LVARs) is a native
  MSFS-only integration and has no file-based equivalent for third-party sims like Aerofly.
- **Radio/audio volume cannot be applied.** SayIntentions can send `COM1_VOLUME_SET` /
  `COM2_VOLUME_SET` / `AUDIO_PANEL_VOLUME_SET`, but Aerofly's external Bridge DLL doesn't expose a
  writable volume variable, so these are received and silently ignored.
- **No barometric pressure / QNH simulation.** Aerofly always runs on standard pressure
  (1013 hPa) — confirmed by inspecting `main.mcf`'s weather block, which only contains wind,
  clouds, and visibility. `SEA LEVEL PRESSURE` is always sent as 1013.
- **VR launch is unreliable.** The `Launch VR` button writes `vr_use_openvr: true` into `main.mcf`
  before starting Aerofly, but this alone doesn't reliably force VR mode — Aerofly may still start
  in flat-screen mode. If this happens, try starting your VR runtime (e.g. SteamVR) *before*
  clicking Launch, or enable VR manually from Aerofly's own settings after it starts. If you figure
  out the actual trigger, a PR is very welcome.
- **Runways aren't set automatically.** Origin/destination airports and cruise altitude are staged
  from SimBrief, but the specific departure/arrival runway is not — pick it in Aerofly as usual.
- **Cost Index has no equivalent field** in `main.mcf` and can't be set this way.

## How it works

- **Telemetry in**: connects to the Aerofly-FS4-Bridge WebSocket, reads Aerofly's native
  variables (radians, meters, m/s), converts them to the units and field names SayIntentions'
  SimAPI expects, and writes `%LOCALAPPDATA%\SayIntentionsAI\simAPI_input.json` roughly twice a second.
- **Commands out**: tails `%LOCALAPPDATA%\SayIntentionsAI\simAPI_output.jsonl` for the handful of
  `setvar` commands SayIntentions actually sends, and relays the relevant ones back to Aerofly over
  the same WebSocket.
- **Flight prep**: directly edits Aerofly's own `main.mcf` settings file for weather, real time,
  aircraft/livery, and origin/destination/cruise altitude — since none of this is exposed over the
  live telemetry WebSocket, only through this settings file, and only *before* Aerofly starts.

## Credits

- [jlgabriel/Aerofly-FS4-Bridge](https://github.com/jlgabriel/Aerofly-FS4-Bridge) — the external DLL
  this project depends on for live Aerofly telemetry.
- [fboes/aerofly-wettergeraet](https://github.com/fboes/aerofly-wettergeraet) and
  [fboes/aerofly-startgeraet](https://github.com/fboes/aerofly-startgeraet) — prior art on editing
  Aerofly's `main.mcf`; the wind-strength/knots conversion formula used here was empirically
  measured and published by that project.
- [SayIntentions.AI](https://sayintentions.ai) — the AI ATC/FO product this bridges to.
- Weather data from the [NOAA Aviation Weather Center API](https://aviationweather.gov/data/api/).
- Flight plan data from the [SimBrief API](https://www.simbrief.com/api/xml.fetcher.php).

## License

MIT — see [LICENSE](LICENSE).
