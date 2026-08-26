# Mode 2 — Alert: Worked Examples


This is the 911 alert WinTAK broadcast during the 8-18-26 capture, followed
by the cancel the operator sent five seconds later. Both ride the same mode;
a single status bit tells the receiver whether to draw or remove the marker.

#### Input CoT XML (active alert)

```xml
<event version="2.0" uid="S-1-5-21-...-9-1-1" type="b-a-o-tbl"
       time="2026-08-19T01:15:46.390Z" start="2026-08-19T01:15:46.390Z"
       stale="2026-08-19T01:25:46.390Z" how="h-e">
  <point lat="38.87296942" lon="-99.32532409" hae="0.0" ce="93.0" le="9999999.0" />
  <detail>
    <link type="a-f-G-U" uid="S-1-5-21-..." relation="p-p" />
    <emergency type="Alert">RECEIVER</emergency>
    <contact callsign="RECEIVER-Alert" />
  </detail>
</event>
```

#### Field-by-field encoding

```
Header
  Callsign 'RECEIVER'  (all letters — no FIGS/LTRS shifts needed)
    R=01010 E=00001 C=01110 E=00001 I=00110 V=11110 E=00001 R=01010
    + CR 01000                                                      [45 bits]
  Version   → 000
  Mode 2    → 001

Payload
  Alert Status   [1 bit]   options: 1 = active    (b-a-o-tbl, draw marker)
                                    0 = cancelled (b-a-o-can, remove marker)
                 type is b-a-o-tbl  →  1
  Alert Name Len [3 bits]  options 000-111 = 0-7 chars; taken from
                 contact/@callsign. 'RECEIVER-Alert' (14 chars)
                 truncates to 7  →  111
  Alert Name     [56 bits] 8-bit ASCII 'RECEIVE'
  Originator Len [3 bits]  originator = callsign segment before '-'
                 = 'RECEIVER' (8 chars), truncates to 7  →  111
  Originator     [56 bits] 8-bit ASCII 'RECEIVE'
  Latitude       [21 bits]  38.87296942 ×10,000 →  388730 → 001011110111001111010
  Longitude      [22 bits] -99.32532409 ×10,000 → -993253 → 1100001101100000011011

Total      : 213 bits → 27 bytes   (captured XML was 541 B → 95% smaller)
Packed hex : 50 5C 13 78 2A 40 3E A4 8A 86 8A 92 AC 8B D4 91 50 D1 52 55
             91 4B DC F5 86 C0 D8
```

Decoded, this rebuilds `b-a-o-tbl` with `uid="HBC-RECEIVE-911"`,
`<emergency type="911 Alert"/>`, `<contact callsign="RECEIVE"/>` and
`<creator callsign="RECEIVE"/>` (the 7-char truncation is permanent).

#### Cancel variant (Alert Status = 0)

The cancel flips the status bit and sends **no alert name** — the originator
(taken from the `<emergency cancel="true">RECEIVER</emergency>` text) is all
the decoder needs to rebuild the same `HBC-{ORIGINATOR}-911` UID, which makes
TAK remove the marker:

```
Alert Status    → 0           (type is b-a-o-can)
Alert Name Len  → 000         (no name transmitted on cancels)
Originator      → 111 + 'RECEIVE'
Lat / Lon       → same encodings as the active alert above

Total      : 157 bits → 20 bytes   (captured XML was 394 B → 95% smaller)
Packed hex : 50 5C 13 78 2A 40 21 D4 91 50 D1 52 55 91 4B DC F5 86 C0 D8
```

