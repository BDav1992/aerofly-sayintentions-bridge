# Changelog

## v1.2

- **New Flight plan mode: "Don't load"** - for resuming a flight already in progress. Leaves
  aircraft and route completely untouched (unlike Empty, which clears the route), and stages the
  destination's weather into `main.mcf` instead of the departure's, since departure conditions are
  no longer relevant. Every other mode still stages departure weather as before. Added
  `pending_dest_weather`, populated whenever the destination METAR is fetched.
- **Turbulence and thermal activity staging**: `main.mcf`'s `[tmsettings_wind][wind]` block has
  `turbulence` and `thermal_activity` fields alongside `strength`/`direction_in_degree`, which
  weren't being written at all. METAR has no direct field for either, so both are estimated:
  turbulence from gust factor (`wgst` vs sustained wind, scaled so a 20kt+ spread maxes out at
  1.0), thermal activity from convective cloud types (CB/TCU in the raw text -> high) or a warm
  temperature with some cloud cover (-> moderate), otherwise low. Sent to the simulator but not
  shown on the Weather tab - the UI stays basic wind/visibility/clouds/temperature/QNH.
- **Fixed a crash fetching METAR when wind is reported as "VRB"** (variable direction, no single
  heading - e.g. light/shifting wind). `wdir` isn't always numeric; a non-numeric value now falls
  back to 0° instead of raising and popping up a "Weather fetch error".

## v1.1

- **Destination METAR (informational)**: the Weather tab now also shows the SimBrief destination
  airport's METAR (raw text, wind, visibility, clouds, temperature, QNH), fetched automatically in
  the background right after a SimBrief OFP fetch. It's reference-only and never written to
  `main.mcf` - only the departure weather (fetched separately, as before) gets staged.
- **Tab order changed**: SimBrief and Weather now come first (before Base Systems and Radio Panel),
  since those are the tabs used most before a flight.

## Known open issue

- CRZ FL sometimes doesn't match the staged cruise altitude once in Aerofly's own FMC, seen on more
  than one aircraft add-on. Under investigation — see [README § Known Limitations](README.md#known-limitations).
