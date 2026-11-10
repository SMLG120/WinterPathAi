# Attribution — pilot_mini fixture

Real data, not simulated (`"simulated": false` in metadata.json).

- **OpenStreetMap**: © OpenStreetMap contributors — https://www.openstreetmap.org/copyright.
  Data available under the Open Database Licence (ODbL 1.0). This fixture is a derived
  database extract and is itself distributed under the ODbL.
- Downloaded via the Overpass API (overpass-api.de, FOSSGIS); single cached query.

Caveats: OSM tags describe mapped infrastructure, not current winter conditions. Nothing in this
fixture states that a sidewalk is cleared, ice-free, safe or wheelchair accessible.
`step_free=true` only reflects an OSM `wheelchair=yes` tag without a contradicting raised kerb;
`null` means unknown and must not be read as accessible.
