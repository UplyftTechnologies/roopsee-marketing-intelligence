# Place data for the Map page

Built by `tools/build_geo_data.py`. Read as data only; nothing from these files is executed.

| File | What | Source |
|---|---|---|
| `states.geojson` | State and union territory outlines, simplified to about 70 KB. For orientation only, not a legal map. | Indian state outlines (GeoJSON) from https://gist.github.com/jbrobst/56c13bbbf9d97d187fea01ca62ea5112 (licence not stated there: replace it if you need to publish the map) |
| `pincodes.csv.gz` | One centre point per Indian pincode: pincode, lat, lon, state | GeoNames postal codes, https://download.geonames.org/export/zip/IN.zip |
| `places.csv.gz` | Place-name centres: name, lat, lon, state, population | GeoNames postal place names and cities of 15,000+ (https://download.geonames.org/export/dump/cities15000.zip) |

GeoNames data is licensed CC BY 4.0: https://www.geonames.org/. The background map tiles are OpenStreetMap (c) OpenStreetMap contributors and are loaded from the internet.
