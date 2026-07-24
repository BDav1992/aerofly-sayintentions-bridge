# Changelog

## v1.1

**UI**
- New dark "glass-cockpit" theme (near-black panels, cyan/amber accents, monospace data readouts)
  applied across every tab, replacing the stock light Tk look.
- "First Officer" tab renamed to **Radio Panel** and rebuilt to look like a real COM radio: ACTIVE
  and STBY are both real, identically-styled entry boxes (ACTIVE read-only) with SWAP in the middle
  and Send on the right next to STBY. Squawk is styled the same way. A small runtime check
  (`tkinter.font.families()`) uses a real 7-segment/LCD font (DSEG7, Digital-7, Segment7Standard) if
  one happens to be installed, falling back to Consolas otherwise.
- Decluttered several tabs: dropped the "Override aircraft"/"Livery (auto-detected)" wording down to
  plain "Aircraft"/"Livery"; removed the "Aircraft (auto-matched)", "Livery match", "Route Staging",
  and exe-detection status-text rows (the underlying matching/detection still happens, it's just not
  echoed back as text); removed the manual "Rescan" buttons (scanning now happens automatically on
  startup, aircraft selection, and OFP fetch); dropped the "QNH (informational)"/"can't be applied"
  wording and the SimBrief tab's explanatory paragraph; moved the Flight plan mode note under its
  dropdown, matching the Weather tab's note style.
- `main.mcf`/`aerofly_fs_4.exe` path controls moved out of the Weather tab into a bar at the bottom
  of the window, visible under every tab. The `main.mcf` indicator is now green/red (found/not
  found), matching the FS4 Bridge connection status convention, instead of a low-contrast blue.
- **Added a Log tab**: every `print()` call (websocket payloads, FO actions, runway-lookup errors)
  now goes through `self.log()`, which writes to a scrollable Log tab - no terminal window needed.

**Aircraft & liveries**
- The "Aircraft" dropdown is now populated by `scan_installed_aircraft()`, a live scan of the actual
  install (user add-ons + base game), instead of a hand-maintained list that had fallen behind
  reality (only 18 of ~44 installed types, several with wrong folder names). `AIRCRAFT_DB` still
  exists, corrected and expanded, but now only feeds SimBrief ICAO matching and SayIntentions
  perf-data fallback.
- Livery detection switched from keyword exclusion to **content-based detection**: a folder only
  counts as a livery if it actually contains a texture file (`.tga`/`.dds`/`.png`/`.ttx`/etc.),
  which correctly excludes config/variant folders (`engine_cfm`, `sharklets`, `wingtips`, ...) that
  keyword matching couldn't recognize.
- **Callsign-based livery matching**: `_match_livery_by_callsign()` extracts the ICAO airline prefix
  from the SimBrief callsign and fuzzy-matches it (via `ICAO_AIRLINE_INFO`) against the aircraft's
  installed liveries, falling back to the first installed livery (with a status message) when no
  match is found.
- **Airline logo display**: fetched from Kiwi.com's free, key-free logo endpoint on a background
  thread and shown inline next to the Livery dropdown, using `tk.PhotoImage` (no Pillow dependency).

**Flight plan mode**
- The "Stage full flight plan" checkbox is now a **Flight plan mode dropdown**: Full load (every
  navlog waypoint, plus experimental empty SID/STAR/Approach placeholders), Pre-load (origin/
  destination + runways only, no placeholders), or Empty (clears the route from `main.mcf` entirely
  via `clear_route_from_lines()`, leaving aircraft selection untouched). Weather and real time are
  staged regardless of mode.
- **Fixed a bug** where changing the mode after fetching an OFP had no effect until Fetch OFP was
  pressed again: the full waypoint list is now always stored at fetch time, and the mode is read at
  `apply_route_to_lines()` (Launch time) instead of being baked in earlier - switching modes now
  takes effect on the very next Launch.

**VR launch**
- Fixed VR launch being unreliable: `steam://rungameid/...` silently ignores `main.mcf`'s
  `vr_use_openvr` flag and just uses whichever VR/Desktop choice was last made in Steam itself.
  Launch VR now starts `aerofly_fs_4.exe` directly with `-openvr` instead, which reliably forces VR
  mode. The exe path is found automatically via `_steam_library_roots()` (Steam's registry entry +
  every library in `libraryfolders.vdf`) - no manual Browse button needed; falls back to the old
  Steam-launch behavior (with a warning) if that lookup fails.

**Radio panel data**
- Fixed STBY frequencies not reflecting Aerofly: STBY previously only showed what you'd typed or
  what an ATC command had set, never what was actually dialed in. `_sync_stby_entry()` now mirrors
  Aerofly's live standby frequency into the box continuously, except while it has keyboard focus, so
  typing a new value is never interrupted.
- `bridge_config.json` now stores both `mcf_path` and `exe_path` (previously only `mcf_path`).

**Notes for future changes**
- `Communication.TransponderAltitude` is the confirmed-working squawk variable over this WebSocket
  bridge - the official Bridge offsets reference lists it as `Communication.TransponderCode`
  instead, but that name did not work in testing. Don't "fix" this back to match the offsets list
  without re-testing in-sim first.

## v1.0

- **Official UID formula**: navdata `Uid` values (airports, runways, waypoints) are now generated
  from Aerofly's own world-grid formula (`generate_uid` / `WORLD_GRID_CONSTANT_A`), reverse-engineered
  and confirmed directly against IPACS developer Jan's C++ source. Replaces the previous approach of
  either omitting the field or writing `0`.
- **Runway-aware route staging**: added `find_runway()`, backed by a locally cached copy of
  OurAirports' `runways.csv` (auto-refreshed every 30 days), so the planned departure/arrival runway
  end (position, heading, length) is written into `main.mcf` alongside origin/destination.
- **Full flight plan staging (optional)**: added a "Stage full flight plan" checkbox that, when
  enabled, also inserts every SimBrief navlog waypoint into the route's `Ways` list as RNAV
  waypoints, instead of only origin/destination.
- **Empty SID/STAR/Approach placeholder nodes**: added around the runway entries as an experimental
  test of whether their presence helps Aerofly populate its own in-MCDU runway list.
- Removed the previous `KNOWN_UIDS` lookup table and background "harvest UIDs from `main.mcf`"
  system entirely, now that UIDs can be computed directly from coordinates.

## Known open issue

- CRZ FL sometimes doesn't match the staged cruise altitude once in Aerofly's own FMC, seen on more
  than one aircraft add-on. Under investigation — see [README § Known Limitations](README.md#known-limitations).

- **Official UID formula**: navdata `Uid` values (airports, runways, waypoints) are now generated
  from Aerofly's own world-grid formula (`generate_uid` / `WORLD_GRID_CONSTANT_A`), reverse-engineered
  and confirmed directly against IPACS developer Jan's C++ source. Replaces the previous approach of
  either omitting the field or writing `0`.
- **Runway-aware route staging**: added `find_runway()`, backed by a locally cached copy of
  OurAirports' `runways.csv` (auto-refreshed every 30 days), so the planned departure/arrival runway
  end (position, heading, length) is written into `main.mcf` alongside origin/destination.
- **Full flight plan staging (optional)**: added a "Stage full flight plan" checkbox that, when
  enabled, also inserts every SimBrief navlog waypoint into the route's `Ways` list as RNAV
  waypoints, instead of only origin/destination.
- **Empty SID/STAR/Approach placeholder nodes**: added around the runway entries as an experimental
  test of whether their presence helps Aerofly populate its own in-MCDU runway list.
- Removed the previous `KNOWN_UIDS` lookup table and background "harvest UIDs from `main.mcf`"
  system entirely, now that UIDs can be computed directly from coordinates.

## Known open issue

- CRZ FL sometimes doesn't match the staged cruise altitude once in Aerofly's own FMC, seen on more
  than one aircraft add-on. Under investigation — see [README § Known Limitations](README.md#known-limitations).
