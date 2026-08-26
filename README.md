# HBC-Protocol

**Ham Binary Cursor on Target (HBC) Protocol** — a compact, bit-oriented binary encoding of [Cursor on Target (CoT)](https://www.mitre.org/publications/technical-papers/cursor-on-target-message-router-users-guide) messages designed for transmission over amateur radio links.

This repository defines the **data format** and provides a Python **encoder** and **decoder**. It is transport-agnostic — the binary output from the encoder is handed off to any RF transport layer. See [HBC-Audio-Modem](https://github.com/ke8tqb/HBC-Audio-Modem) for the companion OFDM transport implementation.

> **Try it:** run `python hbc_translator_gui.py` for a copy/paste GUI that
> translates in both directions — paste a CoT XML event to get the HBC bytes,
> or paste HBC hex / a bit string to get the reconstructed CoT XML.
> tkinter only, no extra dependencies. See [Files](#files).

---

## Why HBC?

Standard CoT XML used by TAK software (ATAK, WinTAK, iTAK) is 500–1000+ bytes per message. Amateur radio links (LoRa, HF packet, DMR, etc.) have very limited bandwidth. HBC compresses CoT into a minimal binary frame:

| Message type | CoT XML | HBC binary |
|---|---|---|
| PLI (4-char callsign + name) | ~600 B | **14 bytes** |
| Spot marker (7-char name) | ~800 B | **17 bytes** |
| 911 Alert | ~700 B | **22 bytes** |
| Alert cancel | ~400 B | **19 bytes** |
| GeoChat (13-char message) | ~900 B | **15 bytes** |
| Drawing circle | ~1,300 B | **22 bytes** |
| Drawing rectangle (4 corners) | ~1,200 B | **31 bytes** |
| CASEVAC (9-line) | ~900 B | **26 bytes** |
| Extended marker (2525 symbol + tint) | ~420 B | **24 bytes** |
| Extended marker (custom iconset icon) | ~500 B | **49 bytes** |

The header always contains the transmitting station's callsign in ITA2 encoding, satisfying **FCC Part 97** identification requirements.

---

## Protocol Version

**Version 1.6** — Modes 0 through 6 defined.

v1.6 adds delivery/read receipts for Direct Messages:
- Mode 3 DMs now carry a 16-bit **message tag** (CRC-16/CCITT-FALSE of the
  sender's ATAK `messageId`) after the recipient callsign (+2 bytes).
- New **Mode 0 — Ack**, carried on the previously reserved wire mode bits
  `111`: recipient callsign (ITA2, CR-terminated) + ack kind (2 bits:
  `00` delivered / `01` read) + the echoed 16-bit message tag (~12 bytes
  total). The receiving station's plugin converts ATAK's automatic
  `b-t-f-d`/`b-t-f-r` receipt events into Mode 0 acks; the original sender
  maps the tag back to its `messageId` and reconstructs the receipt so
  ATAK shows the delivered/read checkmark, matching same-IP-network
  behavior. Wire-incompatible with v1.5 Mode 3 DM frames.

v1.5 adds a 2-bit **Affiliation** field to Mode 1 (`00` Friendly `a-f-G`,
`01` Hostile `a-h-G`, `10` Neutral `a-n-G`, `11` Unknown `a-u-G`). v1.4 and
earlier decoders ignored affiliation entirely: PLI always reconstructed as
Friendly and Spot always as Unknown, regardless of what was actually sent.
This silently mislabeled hostile/neutral PLI units as friendly, and
relabeled any spot/marker that fell back to Mode 1 (because its full type
or icon was not Mode 6-encodable, e.g. a CoT type with a multi-character
dash-token such as `b-m-p-c-cp` Command Post) as a generic "Unknown Ground
Unit" no matter what it actually was. The wire header and PLI/Spot bit are
unchanged; the Affiliation field is inserted immediately after that bit, so
v1.5 Mode 1 bit streams are NOT compatible with v1.4 and earlier Mode 1
frames.

v1.4 updates Mode 3 (GeoChat) to carry an addressed destination instead of
always broadcasting to All Chat Rooms. A new 2-bit destination-kind field
is inserted immediately after the mode header, followed by a room name or
recipient callsign when applicable: `00` All Chat Rooms (unchanged
behavior, no extra field), `01` Named Room (ITA2 room name, CR-terminated),
`10` Direct Message (ITA2 recipient callsign, CR-terminated, same alphabet
as the header callsign), `11` reserved. Direct-message recipients are
addressed by callsign and resolve to the same deterministic `HBC-{CALLSIGN}`
UID used elsewhere, so a DM automatically correlates with that station's
PLI contact. This is **not** a new mode number — Mode 3's bits (`010`) are
unchanged — but the payload layout changed, so v1.4 Mode 3 bit streams are
NOT compatible with v1.3 and earlier Mode 3 frames.

v1.3 adds Mode 6 (Extended Marker): placed markers now transmit their full
CoT type string plus an icon reference (MIL-STD-2525 mapping, spot-map
color, or custom iconset UUID + path) and optional color tint, so receivers
render the correct symbol instead of a generic unknown marker. Encoders
prefer Mode 6 for all non-PLI point events and fall back to Mode 1 when a
type/icon is not Mode 6-encodable. The wire header is unchanged; v1.2
decoders reject Mode 6 frames as an unknown mode.

v1.2 merges the former Alert (Mode 2) and Alert Cancel (Mode 3) into a single
Mode 2 with a 1-bit alert status, and renumbers GeoChat/Shape/CASEVAC down to
Modes 3/4/5 so the mode sequence has no gaps. The wire header is unchanged
(same 3-bit version code `000`); decoders without a given mode simply reject
unknown mode codes. Note: v1.2 mode numbers and the Mode 2 payload are NOT
compatible with v1.1 bit streams.

---

## Supported Modes

| Mode | Bits | Description | CoT type |
|---|---|---|---|
| Mode 0 | `111` | Ack — DM delivery/read receipt (v1.6) | `b-t-f-d`, `b-t-f-r` |
| Mode 1 | `000` | Minimum PLI or Spot Message | `a-f-G-*`, `a-u-G`, etc. |
| Mode 2 | `001` | Alert Message — active or cancelled (1-bit status) | `b-a-o-tbl`, `b-a-o-can` |
| Mode 3 | `010` | GeoChat Text Message | `b-t-f` |
| Mode 4 | `011` | Shape (circle / rectangle / freeform) | `u-d-c-c`, `u-d-r`, `u-d-f` |
| Mode 5 | `100` | CASEVAC / MEDEVAC | `b-r-f-h-c` |
| Mode 6 | `101` | Extended Marker (type + icon + tint) | any non-PLI point event |

Modes 7 (`110`) and 8 (`111`) are reserved for future versions (e.g. Expanded PLI).

---

## Packet Structure

```
HEADER (variable length)
  Transmitter Callsign  ITA2-encoded, CR-terminated  (5 bits/char + 5-bit terminator)
  HBC Version           3 bits  (000 = v1)
  Data Mode             3 bits  (000 = Mode 1, 001 = Mode 2, ...)

PAYLOAD (mode-dependent)

  Mode 1 — PLI / Spot (v1.5)
    PLI or Spot ID      1 bit   (0 = PLI moving unit, 1 = Spot/Marker)
    Affiliation         2 bits  (00 = Friendly a-f-G, 01 = Hostile a-h-G,
                                 10 = Neutral a-n-G, 11 = Unknown a-u-G or
                                 any type with no atom affiliation prefix)
    Name Length         3 bits  (000 = no name, 001-111 = 1-7 chars)
    Name                0-56 bits  (ASCII, max 7 chars)
    Latitude            21 bits (two's complement x10,000, ~11 m precision)
    Longitude           22 bits (two's complement x10,000, ~11 m precision)

  Mode 2 — Alert (active or cancelled)
    Alert Status        1 bit   (1 = active, show on map; 0 = cancelled, remove)
    Alert Name Length   3 bits  (000 = no name, 001-111 = 1-7 chars)
    Alert Name          0-56 bits  (ASCII, max 7 chars, from contact/@callsign;
                                    empty for cancels)
    Originator Length   3 bits  (000 = no name, 001-111 = 1-7 chars)
    Originator Name     0-56 bits  (ASCII, max 7 chars — whose HBC-{CS}-911
                                    marker this alert or cancel targets)
    Latitude            21 bits (two's complement x10,000, ~11 m precision)
    Longitude           22 bits (two's complement x10,000, ~11 m precision)

  Mode 3 — GeoChat (v1.4, DM message tag added in v1.6)
    Destination Kind    2 bits  (00 = All Chat Rooms, 01 = Named Room,
                                 10 = Direct Message, 11 = reserved)
    Named Room:
      Room Name         ITA2-encoded, CR-terminated  (free text)
    Direct Message:
      Recipient         ITA2-encoded, CR-terminated  (max 8 chars, same
                        alphabet as the header callsign)
      Message Tag       16 bits (CRC-16/CCITT-FALSE of the sender's ATAK
                        messageId; echoed back in Mode 0 acks)
    Message             ITA2-encoded, CR-terminated  (5 bits/char + shifts)
                        Uppercase only; non-ITA2 characters become '?'.
                        No coordinates are transmitted.

  Mode 0 — Ack (v1.6, wire mode bits 111)
    Recipient           ITA2-encoded, CR-terminated  (the original DM sender)
    Ack Kind            2 bits  (00 = delivered b-t-f-d, 01 = read b-t-f-r,
                                 10-11 = reserved)
    Message Tag         16 bits (echoed from the acknowledged DM)

  Mode 4 — Shape
    Shape Kind          2 bits  (00 = circle, 01 = closed polygon,
                                 10 = open polyline, 11 = reserved)
    Name Length         3 bits  (000 = no name, 001-111 = 1-7 chars)
    Name                0-56 bits  (ASCII, max 7 chars)
    Circle:
      Center Latitude   21 bits (two's complement x10,000)
      Center Longitude  22 bits (two's complement x10,000)
      Radius            16 bits (unsigned whole meters, 0-65,535)
    Polygon / Polyline:
      Point Count       4 bits  (2-15 points)
      First Latitude    21 bits (two's complement x10,000)
      First Longitude   22 bits (two's complement x10,000)
      Per extra point:
        Delta Latitude  14 bits (signed x10,000 from previous point, max ±0.8191°)
        Delta Longitude 14 bits (signed x10,000 from previous point, max ±0.8191°)

  Mode 5 — CASEVAC / MEDEVAC (9-line)
    Title Length        3 bits  (000 = no title, 001-111 = 1-7 chars)
    Title               0-56 bits  (ASCII, max 7 chars)
    Frequency           16 bits (10 kHz steps, 0 = unknown, 0-655.35 MHz)   [line 2]
    Urgent              4 bits  (patient count by precedence, 0-15)         [line 3]
    Urgent Surgical     4 bits
    Priority            4 bits
    Routine             4 bits
    Convenience         4 bits
    Litter              4 bits  (patient count, 0-15)                       [line 5]
    Ambulatory          4 bits
    Flags               4 bits  (bit3 = casevac, bit2 = equipment_none,
                                 bit1 = terrain_none, bit0 = reserved)      [lines 4/9]
    Security            2 bits  (0-3)                                       [line 6]
    HLZ Marking         3 bits  (0-7)                                       [line 7]
    Zone Protection     2 bits  (0-3)
    Latitude            21 bits (two's complement x10,000)                  [line 1]
    Longitude           22 bits (two's complement x10,000)

  Mode 6 — Extended Marker (v1.3)
    Name Length         3 bits  (000 = no name, 001-111 = 1-7 chars)
    Name                0-56 bits  (ASCII, max 7 chars)
    Latitude            21 bits (two's complement x10,000)
    Longitude           22 bits (two's complement x10,000)
    Type Token Count    4 bits  (1-15)
    Type Tokens         6 bits each — index into charset 0-9 (0-9),
                        A-Z (10-35), a-z (36-61). One token per dash-separated
                        element of the CoT type ("a-h-G-U-C-I" = 6 tokens).
                        Multi-character tokens are not Mode 6-encodable and
                        force a Mode 1 fallback.
    Icon Kind           2 bits
                        00 = none      (receiver derives symbol from type)
                        01 = 2525C     (receiver rebuilds
                                        COT_MAPPING_2525C/<a-x>/<full type>)
                        10 = spot map  + 4-bit palette index (see below);
                                       index 15 = raw 32-bit ARGB follows
                        11 = custom    + 128-bit iconset UUID (binary)
                                       + icon subpath, ITA2-encoded,
                                         CR-terminated
    Tint Present        1 bit   (1 = 32-bit ARGB <color> follows; always 0
                                 for spot map, whose color is carried above)

    Spot palette: 0 white, 1 yellow, 2 red, 3 green, 4 blue, 5 orange,
    6 magenta, 7 cyan, 8 black, 9 gray, 10 brown, 11 purple, 15 = raw ARGB.
```

---

## Files

| File | Description |
|---|---|
| `hbc_encoder.py` | Encodes CoT XML or TAK Protocol (takproto) binary to HBC bytes |
| `hbc_decoder.py` | Decodes HBC bytes to `HBCDecodedMessage` with `.to_xml()` |
| `hbc_translator_gui.py` | Copy/paste GUI translator: CoT XML ⇄ HBC (hex or bit string). Run with `python hbc_translator_gui.py`; `--selftest` checks the translation logic without opening a window |
| `crosscheck_mode6.py` | Mode 6 interoperability vectors — verifies this implementation is byte-for-byte identical to the companion ATAK plugin's Java port |
| `requirements.txt` | Python dependencies |

---

## Requirements

- Python 3.8+
- `takproto` — only required when the encoder input is takproto binary.
  takproto cannot be pip installed from PyPI; it must be taken directly from
  the GitHub URL:

```
pip install git+https://github.com/snstac/takproto.git
```

or simply:

```
pip install -r requirements.txt
```

---

## Usage

### Encoding (CoT -> HBC bytes)

```python
from hbc_encoder import encode

# From CoT XML string
msg = encode(xml_string)

# From raw takproto bytes (received over a TAK network connection)
msg = encode(proto_bytes)

print(msg)             # human-readable field-by-field summary
raw = msg.to_bytes()   # packed bytes  <-- hand these to your transport layer
```

### Decoding (HBC bytes -> CoT)

```python
from hbc_decoder import decode

# raw_bytes received from transport layer (e.g. OFDM audio demodulator)
msg = decode(raw_bytes)

print(msg)             # decoded field summary
print(msg.to_xml())    # reconstructed CoT XML ready for injection into TAK
```

### Full round-trip

```python
from hbc_encoder import encode
from hbc_decoder import decode

xml = open('position.xml').read()

# Transmit side
hbc_bytes = encode(xml).to_bytes()   # -> hand to RF/audio transport

# Receive side  
decoded  = decode(hbc_bytes)         # <- receive from RF/audio transport
cot_xml  = decoded.to_xml()          # -> inject into TAK via UDP/multicast
```

---

## Deterministic UID Derivation Rule

The full device UID (e.g. `ANDROID-8f2a5d78d919931a`) is **not transmitted** over the
RF link — it would cost 18+ bytes per message and varies per device. Instead, every
HBC decoder reconstructs a stable, globally unique UID from the callsign already
present in the header, using a fixed formula:

| Message type | Formula | Example |
|---|---|---|
| Mode 1 PLI (PLI bit = 0) | `"HBC-" + CALLSIGN` | `HBC-KE8TQB` |
| Mode 1 Spot (PLI bit = 1) | Random UUID4 | `f1907ab4-7402-...` (new each decode) |
| Mode 2 Alert (active or cancelled) | `"HBC-" + ORIGINATOR + "-911"` | `HBC-KE8TQB-911` (a cancel reuses the alert's UID so TAK removes it) |
| Mode 3 GeoChat — All Chat Rooms | `"GeoChat.HBC-" + CALLSIGN + ".All Chat Rooms." + UUID4`; `uid1="All Chat Rooms"` | `GeoChat.HBC-KE8TQB.All Chat Rooms.f1907ab4-...` |
| Mode 3 GeoChat — Named Room | `"GeoChat.HBC-" + CALLSIGN + "." + ROOM + "." + UUID4`; `uid1=ROOM` (the literal room name, same convention as All Chat Rooms) | `GeoChat.HBC-KE8TQB.RECON TEAM.f1907ab4-...` |
| Mode 3 GeoChat — Direct Message | `"GeoChat.HBC-" + CALLSIGN + ".HBC-" + RECIPIENT + "." + UUID4`; `uid1="HBC-" + RECIPIENT` | `GeoChat.HBC-KE8TQB.HBC-ONYX.f1907ab4-...` |
| Mode 4 Shape | Random UUID4 | placed objects, like Spots |
| Mode 5 CASEVAC | Random UUID4 | placed objects, like Spots |
| Mode 6 Extended Marker | Random UUID4 | placed objects, like Spots |
| Future modes | `"HBC-" + CALLSIGN + "-M" + mode` | `HBC-KE8TQB-M7` |

**Why callsign-based UIDs work:**
- Ham radio callsigns are **globally unique by ITU/FCC regulation** and stable for the
  lifetime of a licence — no pre-coordination or lookup table is required.
- Every HBC decoder applying this rule independently produces the **same UID for the
  same callsign**, so TAK clients across the entire receiving network track each station
  under one consistent identifier.
- The `HBC-` prefix ensures derived UIDs **never collide** with UIDs generated by native
  ATAK devices (`ANDROID-`, `WinTAK-`, etc.).

**Spot markers use a random UUID** because a Spot is a one-time map placement with no
persistent entity to track. A fresh UUID prevents accidental merging of new spots with old ones.

**Mode 2 Alerts append `-911`** to distinguish the alert event from the originating
station's PLI — both may exist simultaneously as separate TAK contacts.

```
Example decoded CoT event attributes for KE8TQB PLI:
  uid="HBC-KE8TQB"   type="a-f-G-U-C"   (stable across all receivers)

Example decoded CoT event attributes for KE8TQB Alert:
  uid="HBC-KE8TQB-911"   type="b-a-o-tbl"
```

---

## Worked Examples — XML to HBC, Mode by Mode

This section traces one real message of every mode through the full
conversion: CoT XML → field-by-field HBC encoding → packed bytes. For every
field, the allowed values (options) are listed alongside the value chosen for
that example. The Mode 2-5 examples are messages captured live from WinTAK
(all coordinates throughout have been shifted away from their true positions
for operator privacy), except the v1.4 Mode 3 Named Room and Direct Message
examples, which are synthetic (illustrating the new destination fields);
every bit stream and hex dump below is actual encoder output for the XML shown.

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
Mode                   3 bits, value = mode number - 1.  Options:
                       000 = PLI/Spot   001 = Alert    010 = GeoChat
                       011 = Shape      100 = CASEVAC  101 = Extended Marker
                       110-111 reserved
```

### Mode 1 — PLI / Spot (`a-f-G-*`, `a-u-G`, ...)

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

### Mode 2 — Alert, active or cancelled (`b-a-o-tbl` / `b-a-o-can`)

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

### Mode 3 — GeoChat (`b-t-f`)

Since v1.4, Mode 3 carries a 2-bit **Destination Kind** immediately after
the header, before the message text: `00` All Chat Rooms (broadcast,
default), `01` Named Room, `10` Direct Message, `11` reserved. The encoder
classifies incoming CoT by inspecting `<__chat>`/`<chatgrp>`: no chatroom or
chatroom = "All Chat Rooms" → broadcast; a `<chatgrp>` with 3 or more
`uidN` members → Named Room (the chatroom name is transmitted); otherwise
(exactly `uid0` + `uid1`) → Direct Message (the chatroom name — which ATAK
sets to the recipient's callsign for a 1:1 conversation — is transmitted as
the recipient). This section walks all three destinations through the same
"RECEIVER" station used elsewhere in this document.

#### All Chat Rooms (default) — "test message"

```xml
<event version="2.0" uid="GeoChat.S-1-5-21....All Chat Rooms.3f8d87e7" type="b-t-f"
       time="2026-08-19T01:15:28.470Z" start="2026-08-19T01:15:28.470Z"
       stale="2026-08-20T01:15:28.470Z" how="h-g-i-g-o">
  <point lat="0" lon="0" hae="9999999.0" ce="9999999.0" le="9999999.0" />
  <detail>
    <__chat id="All Chat Rooms" chatroom="All Chat Rooms" senderCallsign="RECEIVER"
            groupOwner="false" messageId="3f8d87e7-...">
      <chatgrp id="All Chat Rooms" uid0="S-1-5-21..." uid1="All Chat Rooms" />
    </__chat>
    <link uid="S-1-5-21..." type="a-f-G-U" relation="p-p" />
    <remarks source="BAO.F.WinTAK.S-1-5-21..." to="All Chat Rooms"
             time="2026-08-19T01:15:28.47Z">test message</remarks>
  </detail>
</event>
```

```
Header
  Callsign 'RECEIVER' (from __chat/@senderCallsign)               [45 bits]
  Version   → 000
  Mode 3    → 010

Payload
  Destination Kind [2 bits]  chatroom = "All Chat Rooms"  →  00
  Message  ITA2, 5 bits/char, CR-terminated (01000). Options per character:
  A-Z + space (letters table); 0-9 and punctuation (figures table,
  FIGS/LTRS shifts inserted automatically); lowercase folds to UPPERCASE;
  characters with no ITA2 code become '?'. Length unlimited (bounded only
  by the transport frame). No coordinate fields exist in this mode —
  WinTAK chat carries lat=0 lon=0, so nothing real is lost.

  'test message' folds to 'TEST MESSAGE':
  T=10000 E=00001 S=00101 T=10000 SP=00100 M=11100
  E=00001 S=00101 S=00101 A=00011 G=11010 E=00001 + CR=01000      [65 bits]

Total      : 118 bits → 15 bytes   (captured XML was 997 B → 98% smaller)
Packed hex : 50 5C 13 78 2A 40 44 02 58 13 81 29 47 A0 A0
```

Decoded: a `b-t-f` event addressed to "All Chat Rooms" with
`senderCallsign="RECEIVER"`, text `TEST MESSAGE`, point 0/0, and
`uid="GeoChat.HBC-RECEIVER.All Chat Rooms.{fresh-UUID4}"`.

#### Named Room — RECEIVER → "Recon Team": "status check"

```xml
<event version="2.0" uid="GeoChat.S-1-5-21.9f8e7d6c.a1b2c3d4" type="b-t-f"
       time="2026-08-25T14:02:11.00Z" start="2026-08-25T14:02:11.00Z"
       stale="2026-08-26T14:02:11.00Z" how="h-g-i-g-o">
  <point lat="0" lon="0" hae="9999999.0" ce="9999999.0" le="9999999.0" />
  <detail>
    <__chat id="9f8e7d6c-..." chatroom="Recon Team" senderCallsign="RECEIVER"
            groupOwner="false" messageId="a1b2c3d4-...">
      <chatgrp id="9f8e7d6c-..." uid0="S-1-5-21" uid1="ANDROID-aaaa" uid2="ANDROID-bbbb" />
    </__chat>
    <link uid="S-1-5-21" type="a-f-G-U" relation="p-p" />
    <remarks source="BAO.F.WinTAK.S-1-5-21" to="Recon Team"
             time="2026-08-25T14:02:11.00Z">status check</remarks>
  </detail>
</event>
```

```
Header
  Callsign 'RECEIVER'                                              [45 bits]
  Version → 000    Mode 3 → 010

Payload
  Destination Kind [2 bits]  <chatgrp> has 3 uidN members (uid0/1/2)  →  01
  Room Name  ITA2, CR-terminated, same rules as Message. 'Recon Team'
  folds to 'RECON TEAM':
  R=01010 E=00001 C=01110 O=11000 N=01100 SP=00100
  T=10000 E=00001 A=00011 M=11100 + CR=01000                      [55 bits]
  Message  'status check' folds to 'STATUS CHECK':
  S=00101 T=10000 A=00011 T=10000 U=00111 S=00101 SP=00100
  C=01110 H=10100 E=00001 C=01110 K=01111 + CR=01000               [65 bits]

Total      : 173 bits → 22 bytes
Packed hex : 50 5C 13 78 2A 40 4A 82 EC 30 90 08 F8 82 C0 70 39 48 EA 05 CF 40
```

Decoded: a `b-t-f` event with `chatroom="RECON TEAM"`, `id="RECON TEAM"`,
`chatgrp uid1="RECON TEAM"` (the literal room name is used as its own UID,
the same convention "All Chat Rooms" already uses), text `STATUS CHECK`,
and `uid="GeoChat.HBC-RECEIVER.RECON TEAM.{fresh-UUID4}"`.

#### Direct Message — RECEIVER → ONYX: "helo landing zone"

```xml
<event version="2.0" uid="GeoChat.S-1-5-21.c07f979e.e0295a69" type="b-t-f"
       time="2026-08-25T14:05:00.00Z" start="2026-08-25T14:05:00.00Z"
       stale="2026-08-26T14:05:00.00Z" how="h-g-i-g-o">
  <point lat="0" lon="0" hae="9999999.0" ce="9999999.0" le="9999999.0" />
  <detail>
    <__chat id="c07f979e-..." chatroom="ONYX" senderCallsign="RECEIVER"
            groupOwner="false" messageId="e0295a69-...">
      <chatgrp id="c07f979e-..." uid0="S-1-5-21" uid1="ANDROID-onyxuid" />
    </__chat>
    <link uid="S-1-5-21" type="a-f-G-U" relation="p-p" />
    <remarks source="BAO.F.WinTAK.S-1-5-21" to="ONYX"
             time="2026-08-25T14:05:00.00Z">helo landing zone</remarks>
  </detail>
</event>
```

```
Header
  Callsign 'RECEIVER'                                              [45 bits]
  Version → 000    Mode 3 → 010

Payload
  Destination Kind [2 bits]  <chatgrp> has exactly uid0+uid1  →  10
  Recipient  ITA2, CR-terminated, same alphabet/8-char limit as the header
  callsign. Taken from chatroom="ONYX":
  O=11000 N=01100 Y=10101 X=11101 + CR=01000                       [25 bits]
  Message  'helo landing zone' folds to 'HELO LANDING ZONE'
  (H E L O SP L A N D I N G SP Z O N E), 17 chars + CR              [90 bits]

Total      : 168 bits → 21 bytes
Packed hex : 50 5C 13 78 2A 40 56 19 5E A2 81 96 09 21 B1 26 66 89 1C 30 28
```

Decoded: a `b-t-f` event with `chatroom="ONYX"`, `id="ONYX"`, `chatgrp
uid1="HBC-ONYX"` (the deterministic PLI UID rule, so the message
correlates with ONYX's existing HBC contact if one exists), `remarks
to="HBC-ONYX"`, text `HELO LANDING ZONE`, and
`uid="GeoChat.HBC-RECEIVER.ONYX.{fresh-UUID4}"`.

### Mode 4 — Shape (`u-d-c-c` / `u-d-r` / `u-d-f`)

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

### Mode 5 — CASEVAC / MEDEVAC (`b-r-f-h-c`)

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

### Mode 6 — Extended Marker (`a-u-G` + 2525C icon + tint)

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

---

## Coordinate Encoding

Latitude and longitude are scaled integers stored as two's complement:

```
encoded = round(coordinate_degrees x 10,000)
decoded = encoded_integer / 10,000.0
```

| Field | Bits | Valid range | Max encoded | Precision |
|---|---|---|---|---|
| Latitude  | 21 | -90 to +90 deg   | +/-900,000 of +/-1,048,575 | 0.0001 deg ~11 m |
| Longitude | 22 | -180 to +180 deg | +/-1,800,000 of +/-2,097,151 | 0.0001 deg ~11 m |

---

## Input Format Auto-Detection

The encoder accepts CoT XML and TAK Protocol (takproto) protobuf binary:

| Input type | Detection | Source |
|---|---|---|
| `str` | Always XML | Any TAK client or server |
| `bytes` starting with `b'<'` | XML bytes | |
| Other `bytes` | takproto binary | TAK Server, ATAK over TCP/UDP |

> **Note:** proto3 omits fields equal to their default value. A lat/lon of exactly 0.0 in a takproto packet is indistinguishable from a missing coordinate — the encoder raises a `UserWarning` in this case.

---

## Adding a New Mode

Both files contain `# ADDING A NEW MODE` comment markers at every extension point, and use dispatch tables (`_BUILDERS` in the encoder, `_DECODERS` in the decoder). To add Mode 7:

1. **Encoder** — add a CoT type entry in `_MODE_BY_COT_TYPE`, parser blocks in `_parse_xml` and `_parse_takproto`, a `_build_mode7()` function, and register it in `_BUILDERS`.
2. **Decoder** — add a `_decode_mode7()` function, register it in `_DECODERS`, and add an XML reconstruction branch in `HBCDecodedMessage.to_xml()`.

---

## Credits & Acknowledgements

All code in this repository is original. The protocol builds on, and the
wider HBC system interoperates with, the following work:

- **Cursor on Target (CoT)** — event schema and type hierarchy by **The
  MITRE Corporation** (CoT Base-Event Schema and sub-schemas, public
  release, MITRE Case #11-3895). CoT is a U.S. Government/MITRE-defined
  message standard; this project implements an independent binary encoding
  of it and is not affiliated with or endorsed by MITRE or the TAK Product
  Center.
- **[takproto](https://github.com/snstac/takproto)** by Sensors & Signals
  LLC (Apache-2.0) — optional dependency used only to parse TAK Protocol
  protobuf input; installed from upstream, not bundled here.
- **ITA2 / Baudot code** — the callsign/text alphabet is the public-domain
  International Telegraph Alphabet No. 2 (CCITT, 1932).
- **ATAK / TAK** — the Android Team Awareness Kit is developed by the TAK
  Product Center; the companion HBC ATAK plugin is built against the
  publicly released ATAK-CIV SDK under its own terms.

Companion transport implementations (separate projects, not part of this
repository) additionally use and credit:

- **[javAX25](https://github.com/sivantoledo/javAX25)** by Sivan Toledo,
  with CRC code adapted from **soundmodem** by Thomas Sailer — AFSK1200
  AX.25 modem (GPL v2 or later; distributions bundling it are provided
  under GPL-compatible terms).
- **[aicodix / rattlegram](https://github.com/aicodix/rattlegram)** COFDMTV
  OFDM modem by Ahmet Inan (permissive ISC-style license).
- **[APRSdroid](https://github.com/ge0rg/aprsdroid)** by Georg Lukas and
  **jsoundmodem** by Bastian Mueller — studied as reference implementations
  for Android audio-modem behavior.

"ATAK", "TAK", and "MIL-STD-2525" are identifiers of their respective
owners; use here is nominative only.

---

## License

MIT

---

*Callsign: KE8TQB*
