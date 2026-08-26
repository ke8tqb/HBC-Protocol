# Mode 5 — CASEVAC / MEDEVAC: Worked Example


The captured CASEVAC form `MED.19.011941` (1 urgent, 2 urgent-surgical,
4 priority, 3 routine, 5 convenience; 1 ambulatory; no equipment; no
terrain obstacles).

#### Input CoT XML

```xml
<event version="2.0" uid="ed60672a-..." type="b-r-f-h-c" how="h-g-i-g-o" ...>
  <point lat="38.92363824" lon="-99.29583102" hae="9999999.0" ... />
  <detail>
    <link type="a-f-G-U" uid="S-1-5-21..." parent_callsign="RECEIVER"
          relation="p-p" production_time="2026-08-19T01:19:41Z" />
    <archive />
    <_medevac_ casevac="False" title="MED.19.011941" freq="0.0" urgent="1"
               routine="3" priority="4" urgent_surgical="2" convenience="5"
               equipment_none="true" ambulatory="1" security="0"
               hlz_marking="3" terrain_none="true" obstacles="None"
               zone_prot_selection="0" />
    <contact callsign="RECEIVER.1" />
  </detail>
</event>
```

#### Field-by-field encoding

```
Header
  Callsign 'RECEIVER' (from link/@parent_callsign)                [45 bits]
  Version → 000    Mode 5 → 100

Payload
  Title      [3+56 bits] options 0-7 chars; 'MED.19.011941' (13 chars)
             truncates → 111 + 'MED.19.'
  Frequency  [16 bits]  options 0-65,535 in 10 kHz steps = 0.00-655.35 MHz,
             0 = unknown/not set (146.52 MHz would encode as 14652).
             Captured freq="0.0" → 0000000000000000                 [line 2]
  Patients by precedence [4 bits each, options 0-15, clamped]      [line 3]
             urgent          = 1 → 0001
             urgent_surgical = 2 → 0010
             priority        = 4 → 0100
             routine         = 3 → 0011
             convenience     = 5 → 0101
  Litter     [4 bits]  options 0-15;  captured 0 → 0000             [line 5]
  Ambulatory [4 bits]  options 0-15;  captured 1 → 0001
  Flags      [4 bits]                                            [lines 4/9]
             bit3 casevac         1 = ground CASEVAC, 0 = MEDEVAC request;
                                  captured "False" → 0
             bit2 equipment_none  captured "true"  → 1
             bit1 terrain_none    captured "true"  → 1
             bit0 reserved                         → 0
             → 0110
  Security   [2 bits]  options 0-3 — WinTAK's line-6 index, transmitted
             verbatim (conventional 9-line meaning: 0 = no enemy troops,
             1 = possible enemy, 2 = enemy in area / approach with caution,
             3 = enemy in area / armed escort required).
             Captured 0 → 00                                        [line 6]
  HLZ Marking [3 bits] options 0-7 — WinTAK's line-7 marking index,
             transmitted verbatim.  Captured 3 → 011                [line 7]
  Zone Prot  [2 bits]  options 0-3 — WinTAK zone_prot_selection index,
             transmitted verbatim.  Captured 0 → 00
  Latitude   [21 bits]  38.92363824 ×10,000 →  389236 → 001011111000001110100
  Longitude  [22 bits] -99.29583102 ×10,000 → -992958 → 1100001101100101000010

Total      : 208 bits → 26 bytes   (captured XML was 839 B → 97% smaller)
Packed hex : 50 5C 13 78 2A 40 9D 35 15 10 B8 C4 E4 B8 00 00 49 0D 40 58
             61 7C 1D 30 D9 42
```

The free-text `obstacles` attribute is never transmitted; on decode
`obstacles="None"` is re-added whenever `terrain_none` is set.

Decoded: rebuilds `b-r-f-h-c` with a `<_medevac_>` element carrying the
counts and enumeration indices, `equipment_none`/`terrain_none` re-expanded
to `"true"`, `contact/@callsign` = the title, a `<link>` back to
`HBC-RECEIVER` with `parent_callsign="RECEIVER"`, and a fresh UUID4 uid.

