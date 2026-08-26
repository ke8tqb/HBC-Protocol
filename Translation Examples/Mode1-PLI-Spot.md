# Mode 1 — PLI / Spot: Worked Examples


This example traces a KE8TQB position report through every step:
CoT XML → HBC binary → reconstructed CoT XML.

#### Step 1 — Input CoT XML

A standard ATAK PLI message with position uncertainty fields already at the `9999999`
sentinel (no GPS altitude or accuracy data), timestamped 2026-07-12T19:00:41Z.

```xml
<event version="2.0"
       uid="ANDROID-KE8TQB-001"
       type="a-f-G-U-C"
       time="2026-07-12T19:00:41.00Z"
       start="2026-07-12T19:00:41.00Z"
       stale="2026-07-12T19:05:41.00Z"
       how="m-g" access="Undefined">
  <point lat="39.871776" lon="-98.324262"
         hae="9999999" ce="9999999" le="9999999" />
  <detail>
    <contact callsign="KE8TQB" />
    <uid Droid="KE8TQB" />
    <track speed="0.0" course="9999999.0" />
  </detail>
</event>
```

#### Step 2 — HBC Mode 1 Encoding (field by field)

##### Header: Callsign (ITA2 + CR terminator)

`KE8TQB` contains the digit `8`, so Figures Shift and Letters Shift codes must
be inserted around it. Each ITA2 character is 5 bits:

```
K        = 01111   (Letters)
E        = 00001   (Letters)
FIGS     = 11011   (shift to Figures mode for the digit)
8        = 00110   (Figures)
LTRS     = 11111   (return to Letters mode)
T        = 10000   (Letters)
Q        = 10111   (Letters)
B        = 11001   (Letters)
CR term  = 01000   (field terminator)

Callsign bits: 01111 00001 11011 00110 11111 10000 10111 11001 01000  [45 bits]
```

##### Header: Version and Mode

Version options: `000` only (v1). Mode options: `000`-`101` = Modes 1-6.
This message is a position report, so Mode 1 is chosen:

```
Version 1  →  000  [3 bits]
Mode 1     →  000  [3 bits]   (Minimum PLI/Spot)
```

##### Payload Field 1 — PLI or Spot ID

Options: `0` = PLI (CoT type begins `a-f-G`, `a-h-G`, or `a-n-G` — a moving
unit, decoded under the stable `HBC-{CALLSIGN}` UID) · `1` = Spot (any other
atom type — a placed marker, decoded under a fresh UUID4). This event is
`a-f-G-U-C` (friendly ground unit), so:

```
PLI (moving unit)  →  0  [1 bit]
```

##### Payload Field 2 — Affiliation (v1.5)

Options: `00` Friendly (`a-f-G`) · `01` Hostile (`a-h-G`) · `10` Neutral
(`a-n-G`) · `11` Unknown (`a-u-G`, or any type with no atom affiliation
prefix). This lets the decoder rebuild the correct type instead of always
assuming Friendly for PLI and Unknown for Spot (see the Hostile/Neutral and
Command Post examples below). This event is `a-f-G-U-C`, which starts with
`a-f-G`:

```
Friendly  →  00  [2 bits]
```

##### Payload Field 3 — Name Length

Options: `000` = no name … `111` = 7 characters. Longer names are truncated
to 7 and the encoder flags the truncation. `KE8TQB` fits at 6:

```
"KE8TQB" = 6 characters  →  110  [3 bits]
```

##### Payload Field 4 — Name (ASCII, 8 bits per character; any 0x00-0xFF byte)

```
'K' (0x4B =  75)  →  01001011
'E' (0x45 =  69)  →  01000101
'8' (0x38 =  56)  →  00111000
'T' (0x54 =  84)  →  01010100
'Q' (0x51 =  81)  →  01010001
'B' (0x42 =  66)  →  01000010

Name bits: 01001011 01000101 00111000 01010100 01010001 01000010  [48 bits]
```

##### Payload Field 5 — Latitude (21-bit two's complement, ×10,000; valid -90° to +90°)

```
Input        :  39.871776°
× 10,000     :  398,717.76
round()      :  398,718
21-bit TC    :  001100001010101111110  [21 bits]
Decode check :  398,718 ÷ 10,000 = 39.871800°  (±2.7 m)
```

##### Payload Field 6 — Longitude (22-bit two's complement, ×10,000; valid -180° to +180°)

```
Input        : -98.324262°
× 10,000     : -983,242.62
round()      : -983,243
22-bit TC    :  1100001111111100110101  [22 bits]
Decode check : -983,243 ÷ 10,000 = -98.324300°  (±4.2 m)
```

##### Complete bit stream (148 bits / 19 bytes)

```
  Callsign (45b)               Ver  Mode P Aff NLen  Name (48b)                       Lat (21b)             Lon (22b)
  011110000111011001101111110000101111100101000 000 000 0 00 110 010010110100010100111000010101000101000101000010 001100001010101111110 1100001111111100110101

  Rows (32 bits per row):
    0–31  :  01111000 01110110 01101111 11000010
   32–63  :  11111001 01000000 00000011 00100101
   64–95  :  10100010 10011100 00101010 00101000
  96–127  :  10100001 00011000 01010101 11111011
  128–147 :  00001111 11110011 0101

  Packed hex (19 bytes):
  78 76 6F C2 F9 40 03 25 A2 9C 2A 28 A1 18 55 FB 0F F3 50
```

#### Step 3 — HBC Decoding (binary → fields)

The receiver reads the bit stream sequentially:

```
Callsign  : read ITA2 until CR (01000)  →  "KE8TQB"
Version   : 000 + 1  →  Version 1
Mode      : 000 + 1  →  Mode 1 (Minimum PLI/Spot)
PLI bit   : 0        →  PLI (moving unit)
Name len  : 110      →  6 characters
Name      : read 6 × 8 bits  →  "KE8TQB"
Latitude  : read 21-bit signed  →  398,718  ÷ 10,000  =  39.871800°
Longitude : read 22-bit signed  → -983,243  ÷ 10,000  = -98.324300°
```

#### Step 4 — Reconstructed CoT XML

Unknown/untransmitted fields are set to standard ATAK sentinel values.
Timestamps reflect the decode time, not the original capture time.

```xml
<event version="2.0" uid="HBC-KE8TQB" type="a-f-G-U-C"
       time="2026-07-12T19:02:00.990Z"
       start="2026-07-12T19:02:00.990Z"
       stale="2026-07-12T19:07:00.990Z"
       how="m-g" access="Undefined">
  <point lat="39.871800" lon="-98.324300"
         hae="9999999" ce="9999999" le="9999999" />
  <detail>
    <contact callsign="KE8TQB" />
    <uid Droid="KE8TQB" />
    <track speed="0.0" course="9999999.0" />
  </detail>
</event>
```

#### Field Fidelity Summary

| Field | Original | Reconstructed | Status |
|---|---|---|---|
| `event/@uid` | `ANDROID-KE8TQB-001` | `HBC-KE8TQB` | ≈ UID derivation rule |
| `event/@type` | `a-f-G-U-C` | `a-f-G-U-C` | ✓ exact |
| `event/@time` | `2026-07-12T19:00:41Z` | decode time | ✗ not transmitted |
| `event/@stale` | +5 min from capture | +5 min from decode | ~ approximated |
| `event/@how` | `m-g` | `m-g` | ~ hardcoded |
| `point/@lat` | `39.871776` | `39.871800` | ~ ±2.7 m |
| `point/@lon` | `-98.324262` | `-98.324300` | ~ ±4.2 m |
| `point/@hae` | `9999999` | `9999999` | ✓ (was already unknown) |
| `point/@ce` | `9999999` | `9999999` | ✓ (was already unknown) |
| `point/@le` | `9999999` | `9999999` | ✓ (was already unknown) |
| `contact/@callsign` | `KE8TQB` | `KE8TQB` | ✓ exact |
| `uid/@Droid` | `KE8TQB` | `KE8TQB` | ✓ exact |
| `track/@speed` | `0.0` | `0.0` | ~ sentinel (unknown) |
| `track/@course` | `9999999.0` | `9999999.0` | ✓ sentinel preserved |

**Result:** 482-byte CoT XML → **19-byte HBC payload** (96% size reduction)

> **TAK note:** `hae`, `ce`, `le`, `track/course` all use `9999999` / `9999999.0`
> as the standard ATAK sentinel for "unknown". When these fields already held
> sentinel values in the original message (no GPS fix), HBC causes **zero data
> loss** for those fields.

#### Spot variant (PLI bit = 1, Affiliation = Unknown)

The same Mode 1 layout carries dropped markers. Since v1.3 the encoder
prefers Mode 6 for placed markers (see below); Mode 1 Spot remains the wire
format receivers must still accept, and the automatic fallback whenever a
marker is not Mode 6-encodable (e.g. multi-character type tokens). For a
captured unknown-ground spot (`a-u-G`) named `U.17.124805` placed by ONYX,
the header callsign comes from `creator/@callsign` and the name from
`contact/@callsign`:

```
Callsign 'ONYX' : O=11000 N=01100 Y=10101 X=11101 + CR 01000        [25 bits]
Version / Mode  : 000 / 000
PLI/Spot bit    : 1     (a-u-G is not an a-f-G / a-h-G / a-n-G type)
Affiliation     : 11    (Unknown — a-u-G has no other affiliation match)
Name            : 111 + 'U.17.12'  ('U.17.124805' truncated to 7)   [3+56 bits]
Latitude        :  39.871743  →  398717   →  001100001010101111101
Longitude       : -100.324462 → -1003245  →  1100001011000100010011

Total      : 136 bits → 17 bytes
Packed hex : C3 2B D4 01 FA A9 71 89 B9 71 89 91 85 5F 70 B1 13
```

On decode the spot is rebuilt as `a-u-G` with `how="h-g-i-g-o"`, a fresh
UUID4 uid, a 1-year stale, and `<creator callsign="ONYX"/>`.

#### Hostile and Neutral PLI (v1.5 — correct labeling)

Before v1.5, Mode 1 decode **always** rebuilt PLI as Friendly (`a-f-G`)
regardless of what was actually transmitted — a hostile or neutral track
would silently show up on every receiver's map as friendly. The
Affiliation field fixes this. Two otherwise-identical PLI reports, differing
only in CoT type and callsign:

```xml
<event version="2.0" uid="ANDROID-hostile001" type="a-h-G-U-C" how="m-g">
  <point lat="39.871776" lon="-98.324262" hae="9999999" ce="9999999" le="9999999" />
  <detail><contact callsign="BANDIT1" /><uid Droid="BANDIT1" /></detail>
</event>
```

```
Callsign 'BANDIT1'                                                  [50 bits]
Version / Mode  : 000 / 000
PLI/Spot bit    : 0       (a-h-G-U-C starts with a-h-G → PLI)
Affiliation     : 01      (Hostile)
Name            : 111 + 'BANDIT1'                                [3+56 bits]
Latitude/Longitude: same encoding as the KE8TQB example above

Total      : 161 bits → 21 bytes
Packed hex : C8 D8 93 43 77 FA 00 3D 09 05 39 11 25 50 C4 C2 AF D8 7F 9A 80
```

Decoded: `type="a-h-G"`, `uid="HBC-BANDIT1"` — correctly hostile, not friendly.

```xml
<event version="2.0" uid="ANDROID-neutral001" type="a-n-G-U-C" how="m-g">
  <point lat="39.871776" lon="-98.324262" hae="9999999" ce="9999999" le="9999999" />
  <detail><contact callsign="CIVIC1" /><uid Droid="CIVIC1" /></detail>
</event>
```

```
Callsign 'CIVIC1'                                                   [45 bits]
PLI/Spot bit    : 0       (a-n-G-U-C starts with a-n-G → PLI)
Affiliation     : 10      (Neutral)
Name            : 110 + 'CIVIC1'                                 [3+48 bits]

Total      : 148 bits → 19 bytes
Packed hex : 71 BC 67 6E FF 40 0B 21 A4 AB 24 A1 98 98 55 FB 0F F3 50
```

Decoded: `type="a-n-G"`, `uid="HBC-CIVIC1"` — correctly neutral, not friendly.

#### Known remaining gap: non-atom types still fall back to Unknown

Affiliation only applies to `a-`-prefixed atom types (Friendly/Hostile/
Neutral/Unknown ground). CoT "bits" types with no affiliation prefix — e.g.
`b-m-p-c-cp` (Command Post), captured live from ATAK — still fall back to
Mode 1 Unknown whenever Mode 6 can't encode them (here, because `cp` is a
2-character dash-token and Mode 6's type-token field only supports single
characters). v1.5 makes that fallback *honest* (Unknown is genuinely the
best available label) instead of it being a side effect of a hardcoded
constant, but it does not recover the Command Post icon itself:

```xml
<event version="2.0" uid="246b95d0-ba26-4577-a1c8-918276dff506" type="b-m-p-c-cp" how="h-g-i-g-o">
  <point lat="39.6227396" lon="-84.2035144" hae="9999999" ce="9999999" le="9999999" />
  <detail>
    <creator uid="ANDROID-60a23e2d48e13de0" callsign="FAF" type="a-f-G-U-C" />
    <contact callsign="FAF.25.194409" />
  </detail>
</event>
```

```
Callsign 'FAF'  : F=01101 A=00011 F=01101 + CR 01000                [20 bits]
PLI/Spot bit    : 1       (b-m-p-c-cp is not a PLI atom type → Spot)
Affiliation     : 11      (Unknown — not an a-*-G atom type at all)
Name            : 111 + 'FAF.25.'  ('FAF.25.194409' truncated to 7) [3+56 bits]

Total      : 131 bits → 17 bytes
Packed hex : 68 DA 80 3F 46 41 46 2E 32 35 2E 30 5E 1E 64 D9 A0
```

Recovering the exact Command Post icon would require widening Mode 6's
type-token encoding to support multi-character tokens — tracked as a
follow-up, not part of this change.

