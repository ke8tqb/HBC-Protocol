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
| GeoChat direct message (17-char message + receipt tag) | ~900 B | **23 bytes** |
| DM delivered/read ack | ~350 B | **12 bytes** |
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

Mode 7 (`110`) is reserved for future versions (e.g. Expanded PLI); bit
pattern `111` is used by Mode 0 as of v1.6.

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
| `Translation Examples/` | Field-by-field worked examples for every mode (CoT XML → bits → hex), one file per mode |
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
| Mode 3 GeoChat — Direct Message | `"GeoChat.HBC-" + CALLSIGN + ".HBC-" + RECIPIENT + "." + UUID4`; `uid1` = `"HBC-" + RECIPIENT` (conversation id = the recipient UID, matching ATAK's native 1:1 wire format) | `GeoChat.HBC-KE8TQB.HBC-ONYX.f1907ab4-...` |
| Mode 0 Ack | Receipt UID = the acknowledged DM's original `messageId` (resolved from the 16-bit tag by the sender; offline fallback `"HBC-ACK-" + TAG`) | `e0295a69-...` / `HBC-ACK-4583` |
| Mode 4 Shape | Random UUID4 | placed objects, like Spots |
| Mode 5 CASEVAC | Random UUID4 | placed objects, like Spots |
| Mode 6 Extended Marker | Random UUID4 | placed objects, like Spots |
| Future modes | `"HBC-" + CALLSIGN + "-M" + mode` | `HBC-KE8TQB-M7` |

**Receiver-side substitution (Direct Messages):** ATAK's chat service files
a 1:1 message into the chat window only when `chatgrp/uid1` equals the
receiving device's *real* UID (e.g. `ANDROID-…`). A receiving
implementation that knows its own device UID must substitute it for the
derived `HBC-{RECIPIENT}` UID before injection (the reference decoder
exposes `chat_recipient_uid_override` for this; the companion ATAK plugin
does it automatically and ignores DMs addressed to other stations). The
derived UID remains the offline/derivation fallback.

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

## Worked Examples

Field-by-field XML-to-HBC conversion walkthroughs for every mode - real
captured messages, exact bit streams, and packed hex verified against the
encoder - live in the [Translation Examples](<Translation Examples/>)
folder, one file per mode:

| Mode | Example file |
|---|---|
| Mode 0 - Ack (DM receipts) | [Mode0-Ack.md](<Translation Examples/Mode0-Ack.md>) |
| Mode 1 - PLI / Spot | [Mode1-PLI-Spot.md](<Translation Examples/Mode1-PLI-Spot.md>) |
| Mode 2 - Alert | [Mode2-Alert.md](<Translation Examples/Mode2-Alert.md>) |
| Mode 3 - GeoChat | [Mode3-GeoChat.md](<Translation Examples/Mode3-GeoChat.md>) |
| Mode 4 - Shape | [Mode4-Shape.md](<Translation Examples/Mode4-Shape.md>) |
| Mode 5 - CASEVAC | [Mode5-CASEVAC.md](<Translation Examples/Mode5-CASEVAC.md>) |
| Mode 6 - Extended Marker | [Mode6-Extended-Marker.md](<Translation Examples/Mode6-Extended-Marker.md>) |


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
