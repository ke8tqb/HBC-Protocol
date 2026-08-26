# Mode 4 — Shape: Worked Examples


The first payload field selects the geometry, so this mode gets two
walkthroughs: the captured circle and the captured rectangle.

Shape Kind options [2 bits]:

```
00 = circle          chosen for u-d-c-c
01 = closed polygon  chosen for u-d-r, and for u-d-f whose first point
                     repeats as its last (a closed freeform ring)
10 = open polyline   chosen for any other u-d-f
11 = reserved
```

#### Circle (`u-d-c-c`, "Circle 1", 346 m)

```xml
<event version="2.0" uid="858caa5a-..." type="u-d-c-c" how="h-g-i-g-o" ...>
  <point lat="38.91531734" lon="-99.17975988" hae="9999999.0" ... />
  <detail>
    <creator uid="S-1-5-21..." type="a-f-G-U" callsign="RECEIVER" ... />
    <shape>
      <ellipse minor="346.236470751501" angle="360" major="346.236470751501" />
    </shape>
    <contact callsign="Circle 1" />
  </detail>
</event>
```

```
Header
  Callsign 'RECEIVER' (from creator/@callsign)                    [45 bits]
  Version → 000    Mode 4 → 011

Payload
  Shape Kind [2 bits]   type is u-d-c-c  →  00 (circle)
  Name Len   [3 bits]   options 0-7; 'Circle 1' (8 chars) truncates
             to 'Circle ' → 111
  Name       [56 bits]  8-bit ASCII 'Circle '
  Center Lat [21 bits]   38.91531734 ×10,000 →  389153 → 001011111000000100001
  Center Lon [22 bits]  -99.17975988 ×10,000 → -991798 → 1100001101110111001010
  Radius     [16 bits]  options 0-65,535 whole meters (0 = unknown);
             taken from shape/ellipse/@major = 346.236... → rounds to 346
             → 0000000101011010

Total      : 171 bits → 22 bytes   (captured XML was 1,436 B → 98% smaller)
Packed hex : 50 5C 13 78 2A 40 67 43 69 72 63 6C 65 20 2F 81 0E 1B B9 40 2B 40
```

#### Rectangle (`u-d-r`, "Rectangle 2", delta-encoded corners)

```xml
<event version="2.0" uid="7e6ed0be-..." type="u-d-r" how="h-e" ...>
  <point lat="38.90963393" lon="-99.20234887" hae="9999999.0" ... />
  <detail>
    <creator uid="S-1-5-21..." type="a-f-G-U" callsign="RECEIVER" ... />
    <link point="38.91933019,-99.18464613" />
    <link point="38.91933019,-99.22005161" />
    <link point="38.89993498,-99.22004666" />
    <link point="38.89993498,-99.18465108" />
    <contact callsign="Rectangle 2" />
  </detail>
</event>
```

```
Header
  Callsign 'RECEIVER'  [45 bits]    Version → 000    Mode 4 → 011

Payload
  Shape Kind  [2 bits]   type is u-d-r  →  01 (closed polygon)
  Name        [3+56 bits] 'Rectangle 2' (11) truncates → 111 + 'Rectang'
  Point Count [4 bits]   options 2-15 points  →  4  →  0100
  First corner (absolute, same 21/22-bit coordinate format):
    lat  38.91933019 →  389193 → 001011111000001001001
    lon -99.18464613 → -991846 → 1100001101110110011010
  Each further corner: dlat [14 bits] + dlon [14 bits], signed ×10,000
  units relative to the PREVIOUS corner. Options ±8,191 units = ±0.8191°
  (≈91 km) per step — the encoder rejects longer segments:
    corner 2: dlat    0 → 00000000000000   dlon -355 → 11111010011101
    corner 3: dlat -194 → 11111100111110   dlon   +1 → 00000000000001
    corner 4: dlat    0 → 00000000000000   dlon +353 → 00000101100001

Total      : 243 bits → 31 bytes   (captured XML was 1,007 B → 97% smaller)
Packed hex : 50 5C 13 78 2A 40 6F 52 65 63 74 61 6E 67 42 F8 24 E1 BB 34
             00 07 D3 BF 9F 00 02 00 00 2C 20
```

Decoded: a closed 4-point polygon becomes `u-d-r` with four `<link point>`
corners and an event point at the centroid; a closed polygon with any other
count becomes `u-d-f`; kind `10` becomes an open `u-d-f` polyline. Colors and
stroke styles are not transmitted — WinTAK defaults are applied on decode.

