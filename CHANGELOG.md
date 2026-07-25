# Changelog

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
