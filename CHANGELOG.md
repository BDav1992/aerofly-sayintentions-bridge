# Changelog

## 1.7.0
- SimBrief tab: fetch OFP, auto-match aircraft to an installed Aerofly aircraft/livery, stage
  origin/destination/cruise altitude for the next launch.
- Weather tab: fetch a real METAR and stage wind/visibility/clouds into `main.mcf`.
- Ambient wind read from `main.mcf` and fed to SayIntentions (`AMBIENT WIND DIRECTION/VELOCITY`).
- Launch Normal / Launch VR: writes real UTC time + staged weather/aircraft/route, then starts
  Aerofly via Steam.
- Removed fuel/payload writing from Launch — confirmed unreliable across multiple tools (see
  Known Limitations in the README).
- Removed non-functional First Officer controls (flaps/gear/autopilot set-commands, aircraft
  system LVARs) — SayIntentions' file-based SimAPI doesn't send these.
- On-ground detection cross-checked against height AGL, since Aerofly's raw flag can get stuck.
- AP1/AP2/A-THR status detection made more robust using Aerofly's FMA-style active-mode strings
  in addition to the plain engaged/throttle-engaged flags.
- All required + several optional SayIntentions SimAPI fields implemented (engine type, total
  weight, wheel RPM, AGL, magvar, indicated altitude, sea level pressure, ambient wind).
- Full English UI/code, reorganized into Base Systems / First Officer / SimBrief / Weather tabs.

## Earlier
- Initial bridge: WebSocket telemetry in, COM radio + squawk commands out.
