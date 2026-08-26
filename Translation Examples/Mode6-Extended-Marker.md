# Mode 6 — Extended Marker: Worked Example


The same yellow-spot event used in the Mode 1 Spot example, but with its
`<usericon>` and `<color>` details — since v1.3 the encoder upgrades placed
markers to Mode 6 so the receiver rebuilds the exact symbol instead of a
generic unknown marker.

#### Input CoT XML

```xml
<event version="2.0" uid="f1907ab4" type="a-u-G" how="h-g-i-g-o">
  <point lat="40.621743" lon="-85.204462" hae="219.631" ce="9999999" le="9999999" />
  <detail>
    <creator callsign="ONYX" type="a-f-G-U-C" uid="x" />
    <usericon iconsetpath="COT_MAPPING_2525C/a-u/a-u-G" />
    <color argb="-1" />
    <contact callsign="U.17.124805" />
  </detail>
</event>
```

#### Field-by-field encoding

```
Header
  Callsign 'ONYX' (from creator/@callsign)
    O=11000 N=01100 Y=10101 X=11101 + CR 01000                     [25 bits]
  Version   → 000
  Mode 6    → 101

Payload
  Name        [3+56 bits]  'U.17.124805' (11 chars) truncates → 111 + 'U.17.12'
  Latitude    [21 bits]   40.621743 ×10,000 →  406217 → 001100011001011001001
  Longitude   [22 bits]  -85.204462 ×10,000 → -852045 → 1100101111111110110011
  Token Count [4 bits]   type 'a-u-G' = 3 dash-separated tokens → 0011
  Type Tokens [6 bits each, charset index: 0-9→0-9, A-Z→10-35, a-z→36-61]
    'a' = 36 → 100100
    'u' = 56 → 111000
    'G' = 16 → 010000
  Icon Kind   [2 bits]   iconsetpath starts COT_MAPPING_2525C → 01
                         (nothing more to send — the receiver derives
                          COT_MAPPING_2525C/a-u/a-u-G from the type)
  Tint        [1 bit]    <color argb="-1"> present → 1
  Tint ARGB   [32 bits]  -1 → 11111111111111111111111111111111

Total      : 190 bits → 24 bytes   (input XML was ~420 B → 94% smaller)
Packed hex : C3 2B D4 0B D5 4B 8C 4D CB 8C 4C 8C 65 93 97 FD 99 C9 C2 0F
             FF FF FF FC
```

Compare with Mode 1, which would need only 17 bytes for this event but
forgets the icon: 7 extra bytes buy back the full CoT type, the 2525C icon
path and the tint. A spot-map marker instead sends Icon Kind `10` plus a
4-bit palette index (white/yellow/red/green/blue/orange/magenta/cyan/black/
gray/brown/purple; index 15 = raw 32-bit ARGB). A custom-iconset marker
sends Icon Kind `11` plus the 128-bit iconset UUID in binary and the icon
file subpath in ITA2 — e.g.
`6d781afb-89a6-4c07-b2b9-a89748b6a38f/AIR/EMS.PNG` costs 49 bytes total.

#### Reconstructed CoT XML

```xml
<event version="2.0" uid="d3e5f732-6828-40ca-a4b8-49aec6a378ce" type="a-u-G"
       time="2026-08-25T03:02:36.980Z" start="2026-08-25T03:02:36.980Z"
       stale="2027-08-25T03:02:36.980Z" how="h-g-i-g-o" access="Undefined">
  <point lat="40.621700" lon="-85.204500" hae="9999999" ce="9999999" le="9999999" />
  <detail>
    <contact callsign="U.17.12" />
    <creator callsign="ONYX" />
    <archive />
    <usericon iconsetpath="COT_MAPPING_2525C/a-u/a-u-G" />
    <color argb="-1" />
  </detail>
</event>
```

The marker UID is a fresh UUID4 (placed objects, like Mode 1 spots), the
stale is +1 year, and the full type, icon path and tint survive the trip —
the receiver renders the identical map symbol.
