# Translation Examples — XML to HBC, Mode by Mode

These files trace one real message of every mode through the full
conversion: CoT XML → field-by-field HBC encoding → packed bytes. For every
field, the allowed values (options) are listed alongside the value chosen
for that example. The Mode 2-5 examples are messages captured live from
WinTAK (all coordinates throughout have been shifted away from their true
positions for operator privacy); the Mode 3 Named Room / Direct Message and
Mode 0 examples are synthetic, illustrating the v1.4/v1.6 fields. Every bit
stream and hex dump is actual encoder output for the XML shown.

| File | Mode | Wire bits | Description |
|---|---|---|---|
| [Mode0-Ack.md](Mode0-Ack.md) | 0 | `111` | DM delivery/read receipt (v1.6) |
| [Mode1-PLI-Spot.md](Mode1-PLI-Spot.md) | 1 | `000` | Minimum PLI / Spot marker (v1.5 Affiliation) |
| [Mode2-Alert.md](Mode2-Alert.md) | 2 | `001` | 911 Alert, active + cancel |
| [Mode3-GeoChat.md](Mode3-GeoChat.md) | 3 | `010` | GeoChat: All Chat Rooms / Named Room / Direct Message (v1.6 tag) |
| [Mode4-Shape.md](Mode4-Shape.md) | 4 | `011` | Circle / rectangle / freeform shapes |
| [Mode5-CASEVAC.md](Mode5-CASEVAC.md) | 5 | `100` | CASEVAC / MEDEVAC 9-line |
| [Mode6-Extended-Marker.md](Mode6-Extended-Marker.md) | 6 | `101` | Extended marker: full type + icon + tint |

## Shared header

Every mode shares the same header, which is worked in full detail in the
Mode 1 example and abbreviated afterwards:

```
Transmitter Callsign   ITA2, 5 bits/char, CR-terminated (01000), max 8 chars.
                       Options per char: A-Z and space (letters table), 0-9
                       and punctuation (figures table). FIGS (11011) / LTRS
                       (11111) shift codes are inserted automatically around
                       figures-table characters.
Version                3 bits.  Options: 000 = v1 (only defined value;
                       001-111 reserved).
Mode                   3 bits, value = mode number - 1 for Modes 1-6;
                       Mode 0 (Ack) rides the bit pattern 111.  Options:
                       000 = PLI/Spot   001 = Alert    010 = GeoChat
                       011 = Shape      100 = CASEVAC  101 = Extended Marker
                       110 = reserved   111 = Ack (Mode 0)
```

## Verifying an example

Paste any input XML (or any packed hex string) into the translator GUI to
reproduce these conversions yourself:

```
python hbc_translator_gui.py
```
