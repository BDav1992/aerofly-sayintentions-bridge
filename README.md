# Aerofly FS4 → SayIntentions.AI Bridge

A Python desktop app that connects **Aerofly FS4** to **[SayIntentions.AI](https://sayintentions.ai)**'s
AI-powered ATC, so you can fly Aerofly with a voice-driven First Officer/ATC experience — something
neither product supports out of the box.

It streams live Aerofly telemetry into SayIntentions' file-based SimAPI, relays the radio/squawk
commands SayIntentions sends back, and helps you prepare a flight (weather, real time, aircraft,
route, runways) before launching Aerofly.

> **Not affiliated with IPACS (Aerofly) or SayIntentions.AI.** This is an independent, community
> bridge built on top of publicly documented interfaces.

## Features

- **Live telemetry → SayIntentions**: position, altitude, heading, speed, aircraft type, on-ground
  status, transponder code, ambient wind — written continuously to SayIntentions' SimAPI input file.
- **Radio Panel**: COM1/COM2 active + standby frequencies laid out like a real radio (active on the
  left, standby on the right, SWAP in the middle). Both sides mirror Aerofly's actual live
  frequencies continuously - typing a new standby value and hitting Send (or an ATC command from
  SayIntentions) overrides it as expected, and the live sync just resumes once you're done editing.
- **Log tab**: everything that would otherwise only go to a console (websocket payloads, radio/
  squawk commands relayed from SayIntentions, runway-lookup errors) is shown in a scrollable Log tab
  instead, so you don't need to keep a terminal window open to see what the app is doing.
- **SimBrief integration**: pull your OFP (route, cruise altitude, fuel, pax, cargo, ZFW) by
  username, auto-match the aircraft type to an installed Aerofly aircraft, and stage the fetched
  origin/destination + cruise altitude + departure/arrival runway for your next flight.
- **Aircraft list always matches what's installed**: the "Aircraft" dropdown (SimBrief tab) is
  scanned live from your actual Aerofly install (user add-ons + base game), so it never falls out
  of sync with what you actually have - no hand-maintained list to fall behind new installs.
- **Runway-aware route staging**: looks up the planned departure/arrival runway ends in a locally
  cached copy of [OurAirports' `runways.csv`](https://davidmegginson.github.io/ourairports-data/runways.csv)
  (re-downloaded automatically every 30 days) and writes proper runway threshold position/heading
  into `main.mcf`. In Full load mode, empty SID/STAR/Approach placeholder nodes are also added (an
  experimental attempt at triggering Aerofly's own runway-list population).
- **Flight plan mode**: a dropdown controlling how much of a fetched SimBrief OFP gets applied at
  Launch - Full load (every navlog waypoint), Pre-load (origin/destination + runways only), or Empty
  (clears the route from `main.mcf` entirely). Weather and real time are staged either way, and
  switching modes takes effect on the very next Launch with no need to re-fetch.
- **Official UID generation**: every navdata `Uid` written to `main.mcf` (airports, runways,
  waypoints) is computed with Aerofly's own world-grid formula — reverse-engineered and confirmed
  directly against IPACS developer Jan's C++ source, validated to exact/bit-perfect matches on the
  large majority of real captured UIDs tested.
- **Weather staging**: fetch a real METAR for any airport and stage wind/visibility/clouds into
  `main.mcf` for your next launch (temperature and barometric pressure can't be applied — see
  [Known Limitations](#known-limitations)).
- **Livery auto-detection**: scans your installed aircraft folders for available liveries as soon
  as an aircraft is picked/matched (no manual button needed). Detection is content-based - it only
  counts a folder as a livery if it actually contains texture files, since Aerofly aircraft
  folders also contain non-livery config/variant folders (engine choice, wingtip choice, etc.) at
  the same level (see [Known Limitations](#known-limitations)).
- **Callsign-based livery matching**: when SimBrief provides a callsign (e.g. `AFR1234`), its ICAO
  airline prefix is matched against your installed liveries for that aircraft. If a match is found
  it's staged automatically; if not, the first installed livery is staged instead with a status
  message explaining why (see [Known Limitations](#known-limitations)).
- **Airline logo display**: shown as a small image right next to the Livery dropdown, fetched from
  Kiwi.com's public, key-free logo endpoint using the callsign's IATA airline code. Best-effort and
  non-blocking - a failed/slow fetch just leaves it blank, it never holds up flight prep (see
  [Known Limitations](#known-limitations)).
- **One-click launch**: writes the current real-world UTC time plus any staged weather/aircraft/
  route/runways, then launches Aerofly via Steam — or, if `aerofly_fs_4.exe` was found automatically
  (the usual case - Steam's own install path/library folders are read directly), launches VR mode
  *directly* with the `-openvr` flag. Confirmed working reliably in testing, unlike Steam's own
  `rungameid` launch, which silently ignores `main.mcf`'s `vr_use_openvr` flag and just uses
  whichever VR/Desktop choice was last made in Steam itself.
- **Dark, glass-cockpit UI**: a custom dark theme (cyan/amber accents, monospace data readouts)
  instead of the stock light Tk look.

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

```
git clone https://github.com/BDav1992/aerofly-ai-atc-bridge.git
cd aerofly-ai-atc-bridge
pip install -r requirements.txt
python aerofly_sayintentions_bridge.py
```

## Usage

1. Start Aerofly FS4 and the [Aerofly-FS4-Bridge](https://github.com/jlgabriel/Aerofly-FS4-Bridge) DLL.
2. Start SayIntentions.AI.
3. Run this app. The **Base Systems** tab should turn green ("FS4 Bridge: Connected") and
   "SayIntentions SimAPI: ACTIVE" once both are talking to it.
4. Optional, before your *next* flight: use the **SimBrief** tab to fetch your OFP (aircraft, route,
   cruise altitude, runway, and livery get matched) and set **Flight plan mode** to control how much
   of it gets applied - Full load (every navlog waypoint), Pre-load (origin/destination + runways
   only), or Empty (clears the route entirely - weather and real time still apply either way).
   Also use the **Weather** tab to fetch a METAR (wind/visibility/clouds get staged), then hit
   **Launch Normal** / **Launch VR** to apply everything and start Aerofly.

The first time you run it, if it can't auto-detect your `main.mcf` (used for weather/time/aircraft/
route staging), use **Browse main.mcf...** in the bar at the bottom of the window (visible under
every tab, right above the Launch buttons) to point it at `Documents\Aerofly FS 4\main.mcf` - it's
remembered in `bridge_config.json`. Your `aerofly_fs_4.exe` path (needed for VR launch) is detected
automatically via Steam's own registry entry and library folders - no action needed unless that
lookup fails, in which case it's shown next to a warning in the same bar. The OurAirports runway
data is cached to `runways_cache.csv` next to the script on first use.

## Known Limitations

These aren't necessarily bugs in this project — most are limits of what Aerofly currently exposes
externally, found through hands-on testing. One open item below is still under investigation and
may turn out to be either side.

- **CRZ FL sometimes doesn't match the intended cruise altitude in-sim.** Reports of the aircraft's
  own FMC (tested on both a Boeing and an Airbus CEO add-on) showing/settling on a lower cruise
  level than what was staged are still being investigated. The value written to `main.mcf`'s
  `CruiseAltitude` field has been directly confirmed correct in at least one such case, so the
  discrepancy shows up between that file and what the aircraft's FMC ultimately does with it. If
  you hit this, a useful data point is comparing the exact `CruiseAltitude` value in `main.mcf` at
  the time of the flight against what SimBrief planned. Reported on the Aerofly forum; not yet
  resolved.
- **Fuel and payload cannot be set externally.** Externally-written `fuel_mass`/`payload_mass` values
  in `main.mcf` are silently ignored/reset by Aerofly on load, regardless of which tool writes them
  (confirmed with this project, with the [Aerofly Startgerät](https://github.com/fboes/aerofly-startgeraet),
  and even manually with the C172). Set fuel/payload manually in Aerofly's own Fuel & Load screen.
- **Flaps, gear, and autopilot cannot be commanded by SayIntentions.** SayIntentions' documented
  file-based SimAPI (`output_variables.txt`) only ever sends radio frequency/swap, squawk, and
  volume commands. Its richer aircraft-system control (e.g. FlyByWire A32NX LVARs) is a native
  MSFS-only integration and has no file-based equivalent for third-party sims like Aerofly.
- **Radio/audio volume cannot be applied.** SayIntentions can send `COM1_VOLUME_SET` /
  `COM2_VOLUME_SET` / `AUDIO_PANEL_VOLUME_SET`, but Aerofly's external Bridge DLL doesn't expose a
  writable volume variable, so these are received and silently ignored.
- **No barometric pressure / QNH simulation.** Aerofly always runs on standard pressure (1013 hPa) —
  confirmed by inspecting `main.mcf`'s weather block, which only contains wind, clouds, and
  visibility. `SEA LEVEL PRESSURE` is always sent as 1013.
- **No temperature simulation**, for the same reason — only wind/visibility/clouds are staged from
  a fetched METAR.
- **Livery auto-detection can still include non-airline paint options.** It's based on whether a
  folder contains texture files, which correctly excludes pure config folders (engine choice,
  wingtip choice, etc.) but can't distinguish a genuine airline livery from another paint-bearing
  variant folder (e.g. a base/default livery, which is a legitimate but non-airline option). If the
  wrong one gets picked, use the dropdown to correct it manually.
- **Callsign-based livery matching only covers airlines in a small built-in table**
  (`ICAO_AIRLINE_INFO`), matched fuzzily against your installed livery folder names. Airlines not
  in that table, or livery folders named very differently than the airline's common name, won't
  match - the first installed livery is used instead, with a status message saying so. Extend the
  table freely; it's a plain dict at the top of the script.
- **Airline logos depend on an external, third-party endpoint** (Kiwi.com) and require internet
  access at the moment you fetch a SimBrief OFP; if it's unreachable or the airline isn't in
  Kiwi's database, the logo is just left blank rather than erroring. No aircraft/livery *photo* is
  shown (as opposed to the airline logo) - Aerofly's own preview images (`preview.ttx` /
  `preview_small.ttx`, one per livery) are stored in a proprietary, undocumented compressed format
  with no public decoder, so reading them wasn't attempted. Historical, aerobatic, and military
  aircraft are included in the aircraft dropdown (since that's a live scan of what's installed) but
  aren't realistically going to come from a SimBrief OFP, so they have no meaningful ICAO/weight
  data - pick those manually rather than expecting an auto-match.
- **Empty SID/STAR/Approach placeholder nodes are experimental, and only added in Full load mode.**
  They're written alongside real runway data as a test of whether their presence (even empty) helps
  Aerofly populate its own runway list — this hasn't been conclusively confirmed either way. Pre-load
  writes the runway data without them.
- **Runway data depends on OurAirports' dataset.** If a specific runway isn't in `runways.csv` (or
  has no coordinates listed), it's skipped and you'll need to pick it in Aerofly manually — the app
  tells you when this happens via the route-staging status line.
- **Cost Index has no equivalent field** in `main.mcf` and can't be set this way.
- **SimBrief route/weight data is reference-only.** It is not sent to SayIntentions (that requires a
  Virtual Airline API key from SayIntentions support) — only aircraft/origin/destination/cruise
  altitude/runways are actually staged into Aerofly.

## How it works

- **Telemetry in**: connects to the Aerofly-FS4-Bridge WebSocket, reads Aerofly's native
  variables (radians, meters, m/s), converts them to the units and field names SayIntentions'
  SimAPI expects, and writes `%LOCALAPPDATA%\SayIntentionsAI\simAPI_input.json` roughly twice a second.
- **Commands out**: tails `%LOCALAPPDATA%\SayIntentionsAI\simAPI_output.jsonl` for the handful of
  `setvar` commands SayIntentions actually sends, and relays the relevant ones back to Aerofly over
  the same WebSocket.
- **Flight prep**: directly edits Aerofly's own `main.mcf` settings file for weather, real time,
  aircraft/livery, and route (origin/destination/runways/cruise altitude/optional waypoints) —
  since none of this is exposed over the live telemetry WebSocket, only through this settings file,
  and only *before* Aerofly starts.
- **Navdata UIDs**: computed on the fly from coordinates using Aerofly's own official world-grid
  formula, rather than relying on a lookup table of previously-captured values.
- **Squawk variable naming**: reads/writes `Communication.TransponderAltitude`, confirmed working
  in-sim over this WebSocket bridge. The official Aerofly Bridge offsets reference instead lists
  this as `Communication.TransponderCode` - the offsets list and the live WebSocket variable names
  apparently don't always match, so this was deliberately kept as-is rather than "corrected".

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
- Runway data from [OurAirports](https://ourairports.com/data/).

## License

MIT — see [LICENSE](LICENSE).
