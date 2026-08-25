"""
hbc_encoder.py  —  Ham Binary Cursor on Target (HBC) Encoder
=============================================================
Converts CoT messages into the HBC binary protocol.

Supported input formats
-----------------------
  CoT XML  : str, or bytes beginning with b'<'
  takproto : bytes (TAK Protocol protobuf binary, begins with 0xBF)

Supported HBC modes
-------------------
  Mode 1 (000) : Minimum PLI or Spot Message
  Mode 2 (001) : Alert Message — active or cancelled (1-bit alert status)
  Mode 3 (010) : GeoChat Text Message  (b-t-f — addressed to All Chat Rooms,
                 a named room, or a single station via direct message)
  Mode 4 (011) : Shape  (u-d-c-c circle, u-d-r rectangle, u-d-f freeform)
  Mode 5 (100) : CASEVAC / MEDEVAC  (b-r-f-h-c — 9-line numeric fields)

Transport boundary
------------------
  encode() returns an HBCMessage whose .to_bytes() method produces the raw
  binary payload.  At this point the bytes are ready to be handed off to a
  transport layer (e.g. OFDM audio modulator) for transmission.
  This file does NOT implement any transport; it only converts data formats.

Usage
-----
  from hbc_encoder import encode

  msg = encode(cot_xml_string)      # from XML
  msg = encode(proto_bytes)         # from takproto

  msg.bits          # str  — complete HBC bit stream
  msg.to_bytes()    # bytes — packed, right-zero-padded to byte boundary
  str(msg)          # human-readable field summary
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# =============================================================================
# PROTOCOL CONSTANTS
# (Update here when the spec version changes.)
# =============================================================================
HBC_VERSION       = 1          # Current protocol version (encoded as 000)
MAX_NAME_CHARS    = 7          # Maximum ASCII characters in any name field
MAX_CS_CHARS      = 8          # Maximum ITA2 characters in the header callsign
MAX_SHAPE_POINTS  = 15         # Maximum polygon/polyline points in Mode 4 (4-bit count)

# CoT type → HBC mode mapping
# Add entries here when new modes are defined.
_MODE_BY_COT_TYPE = {
    'b-a-o-tbl': 2,            # Mode 2 — 911 / emergency alert (status bit = 1)
    'b-a-o-can': 2,            # Mode 2 — alert cancel (status bit = 0)
    'b-t-f':     3,            # Mode 3 — GeoChat text message
    'u-d-c-c':   4,            # Mode 4 — shape: circle
    'u-d-r':     4,            # Mode 4 — shape: rectangle
    'u-d-f':     4,            # Mode 4 — shape: freeform polygon/polyline
    'b-r-f-h-c': 5,            # Mode 5 — CASEVAC / MEDEVAC
}
_DEFAULT_MODE     = 1          # Mode 1 for all unrecognised types

# CoT type prefixes that produce a PLI bit of 0 (moving unit)
_PLI_PREFIXES     = ('a-f-G', 'a-h-G', 'a-n-G')

# =============================================================================
# MODE 3 (v1.4) — GeoChat destination kinds
# =============================================================================
# 2-bit field selecting who a GeoChat message is addressed to. All Chat Rooms
# remains the default/broadcast destination; Named Room and Direct Message
# were added in v1.4 without introducing a new mode number.
CHAT_DEST_ALL  = 0   # 00 — All Chat Rooms (broadcast, default)
CHAT_DEST_ROOM = 1   # 01 — Named/custom chat room
CHAT_DEST_DM   = 2   # 10 — Direct message to a single station callsign
#                       11 — reserved

# =============================================================================
# MODE 6 (v1.3) — Extended Marker constants
# =============================================================================
# Type-token charset: index into 0-9 (0-9), A-Z (10-35), a-z (36-61); 6 bits.
TOKEN_CHARSET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

# Spot-map standard color palette (index 0-14; 15 = raw 32-bit ARGB follows).
SPOT_COLORS = [
    0xFFFFFFFF,  # 0 white   (-1)
    0xFFFFFF00,  # 1 yellow  (-256)
    0xFFFF0000,  # 2 red     (-65536)
    0xFF00FF00,  # 3 green   (-16711936)
    0xFF0000FF,  # 4 blue    (-16776961)
    0xFFFFA500,  # 5 orange
    0xFFFF00FF,  # 6 magenta (-65281)
    0xFF00FFFF,  # 7 cyan    (-16711681)
    0xFF000000,  # 8 black   (-16777216)
    0xFF808080,  # 9 gray
    0xFFA52A2A,  # 10 brown
    0xFF800080,  # 11 purple
]


# =============================================================================
# ITA2 ENCODING TABLES  (HBC Protocol Spec — Table 1)
# =============================================================================
_ITA2_LETTERS = {
    'E':'00001', 'A':'00011', ' ':'00100', 'S':'00101',
    'I':'00110', 'U':'00111',
    'D':'01001', 'R':'01010', 'J':'01011', 'N':'01100',
    'F':'01101', 'C':'01110', 'K':'01111', 'T':'10000',
    'Z':'10001', 'L':'10010', 'W':'10011', 'H':'10100',
    'Y':'10101', 'P':'10110', 'Q':'10111', 'O':'11000',
    'B':'11001', 'G':'11010', 'M':'11100', 'X':'11101',
    'V':'11110',
    # Control codes
    'CR_TERM': '01000',   # Carriage Return — callsign field terminator
    'FIGS':    '11011',   # Figures Shift
    'LTRS':    '11111',   # Letters Shift
}

_ITA2_FIGURES = {
    '3':'00001', '-':'00011', "'": '00101', '8':'00110',
    '7':'00111', '$':'01001', '4':'01010', ',':'01100',
    '!':'01101', ':':'01110', '(':'01111', '5':'10000',
    '"':'10001', ')':'10010', '2':'10011', '#':'10100',
    '6':'10101', '0':'10110', '1':'10111', '9':'11000',
    '?':'11001', '&':'11010', '.':'11100', '/':'11101',
    ';':'11110',
}


# =============================================================================
# OUTPUT DATACLASS
# =============================================================================
@dataclass
class HBCMessage:
    """
    Encoded HBC message returned by encode().

    Attributes common to all modes
    --------------------------------
    mode            HBC mode number (1, 2, …)
    source_format   'xml' or 'takproto'
    cot_type        Original CoT type string
    callsign        ITA2 header callsign (transmitter)
    lat, lon        Coordinate floats

    Mode-1-specific attributes
    --------------------------
    is_spot         False = PLI, True = Spot/Marker
    name            Display name (≤ MAX_NAME_CHARS)
    name_truncated  True if name was shortened

    Mode-2-specific attributes
    --------------------------
    alert_active          True = active alert (show on map), False = cancelled
    alert_name            Alert callsign (≤ MAX_NAME_CHARS; empty for cancels)
    alert_name_truncated  True if alert_name was shortened
    orig_name             Originator name (≤ MAX_NAME_CHARS)
    """
    mode:           int
    source_format:  str
    cot_type:       str
    callsign:       str
    lat:            float
    lon:            float
    lat_int:        int   = field(repr=False)
    lon_int:        int   = field(repr=False)
    callsign_bits:  str   = field(repr=False)
    lat_bits:       str   = field(repr=False)
    lon_bits:       str   = field(repr=False)

    # Mode 1
    is_spot:          bool = False
    name:             str  = ''
    name_truncated:   bool = False
    pli_bit:          str  = field(default='', repr=False)
    name_len_bits:    str  = field(default='', repr=False)
    name_ascii_bits:  str  = field(default='', repr=False)

    # Mode 2 — Alert (active or cancelled)
    alert_active:         bool = True
    alert_name:           str  = ''
    alert_name_truncated: bool = False
    orig_name:            str  = ''
    alert_len_bits:       str  = field(default='', repr=False)
    alert_name_bits:      str  = field(default='', repr=False)
    orig_len_bits:        str  = field(default='', repr=False)
    orig_name_bits:       str  = field(default='', repr=False)

    # Mode 3 — GeoChat
    chat_text:      str  = ''
    chat_bits:      str  = field(default='', repr=False)
    chat_dest_kind: int  = CHAT_DEST_ALL   # 0 all, 1 named room, 2 direct message
    chat_room:      str  = ''              # room name (dest kind 1)
    chat_recipient: str  = ''              # recipient callsign (dest kind 2)
    chat_dest_bits: str  = field(default='', repr=False)

    # Mode 4 — Shape (name/name_len_bits/name_ascii_bits above are reused for the label)
    shape_kind:   int  = 0     # 0 = circle, 1 = closed polygon, 2 = open polyline
    radius_m:     int  = 0     # circle radius in whole meters
    shape_points: list = field(default_factory=list)   # [(lat, lon), ...]
    shape_bits:   str  = field(default='', repr=False) # post-name payload bits

    # Mode 5 — CASEVAC (name fields above are reused for the title)
    medevac:  dict = field(default_factory=dict)
    med_bits: str  = field(default='', repr=False)

    # Mode 6 — Extended Marker (v1.3); complete payload prebuilt by the builder
    icon_kind:  int = 0     # 0 none, 1 2525C, 2 spotmap, 3 custom iconset
    mode6_bits: str = field(default='', repr=False)

    # -------------------------------------------------------------------------
    # Derived properties
    # -------------------------------------------------------------------------
    @property
    def version_bits(self) -> str:
        return format(HBC_VERSION - 1, '03b')

    @property
    def mode_bits(self) -> str:
        return format(self.mode - 1, '03b')

    @property
    def payload_bits(self) -> str:
        if self.mode == 1:
            return (self.pli_bit + self.name_len_bits + self.name_ascii_bits
                    + self.lat_bits + self.lon_bits)
        if self.mode == 2:
            # Alert status bit + alert name + originator + position
            return (('1' if self.alert_active else '0')
                    + self.alert_len_bits + self.alert_name_bits
                    + self.orig_len_bits  + self.orig_name_bits
                    + self.lat_bits + self.lon_bits)
        if self.mode == 3:
            # Destination kind (2 bits) + optional room/recipient +
            # ITA2 message text, CR-terminated (no coordinates)
            return self.chat_dest_bits + self.chat_bits
        if self.mode == 4:
            # Shape kind + name + kind-specific body (coords live in shape_bits)
            return (format(self.shape_kind, '02b')
                    + self.name_len_bits + self.name_ascii_bits
                    + self.shape_bits)
        if self.mode == 5:
            # Title + 9-line numeric fields + position
            return (self.name_len_bits + self.name_ascii_bits
                    + self.med_bits + self.lat_bits + self.lon_bits)
        if self.mode == 6:
            # Extended marker: name + position + type tokens + icon + tint
            return self.mode6_bits
        raise ValueError(f'Unsupported mode: {self.mode}')

    @property
    def bits(self) -> str:
        """Complete HBC bit stream (header + payload)."""
        return self.callsign_bits + self.version_bits + self.mode_bits + self.payload_bits

    @property
    def bit_count(self) -> int:
        return len(self.bits)

    @property
    def byte_count(self) -> int:
        return -(-self.bit_count // 8)   # ceiling division

    def to_bytes(self) -> bytes:
        """
        Pack bit stream into bytes, right-zero-padded to a byte boundary.
        *** TRANSPORT BOUNDARY — hand these bytes to the audio/RF layer. ***
        """
        padded = self.bits.ljust(self.byte_count * 8, '0')
        return bytes(int(padded[i:i+8], 2) for i in range(0, len(padded), 8))

    def __str__(self) -> str:
        lines = [
            f'=== HBC Mode {self.mode} Encoded Message ===',
            f'  source_format : {self.source_format}',
            f'  cot_type      : {self.cot_type}',
            f'  callsign      : {self.callsign!r}  ->  {self.callsign_bits}  [{len(self.callsign_bits)}b]',
            f'  version       : {HBC_VERSION}  ->  {self.version_bits}',
            f'  mode          : {self.mode}  ->  {self.mode_bits}',
        ]
        if self.mode == 1:
            trunc = '  (TRUNCATED)' if self.name_truncated else ''
            lines += [
                f'  PLI/Spot      : {"Spot(1)" if self.is_spot else "PLI(0)"}  ->  {self.pli_bit}',
                f'  name_len      : {len(self.name)} chars{trunc}  ->  {self.name_len_bits}',
                f'  name          : {self.name!r}  ->  {self.name_ascii_bits}  [{len(self.name_ascii_bits)}b]',
            ]
        elif self.mode == 2:
            trunc = '  (TRUNCATED)' if self.alert_name_truncated else ''
            lines += [
                f'  alert_status  : {"ACTIVE" if self.alert_active else "CANCELLED"}  ->  {"1" if self.alert_active else "0"}',
                f'  alert_name_len: {len(self.alert_name)} chars{trunc}  ->  {self.alert_len_bits}',
                f'  alert_name    : {self.alert_name!r}  ->  {self.alert_name_bits}  [{len(self.alert_name_bits)}b]',
                f'  orig_name_len : {len(self.orig_name)} chars  ->  {self.orig_len_bits}',
                f'  orig_name     : {self.orig_name!r}  ->  {self.orig_name_bits}  [{len(self.orig_name_bits)}b]',
            ]
        elif self.mode == 3:
            kind_name = {0: 'All Chat Rooms', 1: 'Named Room', 2: 'Direct Message'}.get(
                self.chat_dest_kind, '?')
            lines += [
                f'  dest_kind     : {kind_name}({self.chat_dest_kind})  ->  {format(self.chat_dest_kind, "02b")}',
            ]
            if self.chat_dest_kind == CHAT_DEST_ROOM:
                lines += [f'  room          : {self.chat_room!r}']
            elif self.chat_dest_kind == CHAT_DEST_DM:
                lines += [f'  recipient     : {self.chat_recipient!r}']
            lines += [
                f'  chat_text     : {self.chat_text!r}  ->  {self.chat_bits}  [{len(self.chat_bits)}b]',
            ]
        elif self.mode == 4:
            kind_name = {0: 'circle', 1: 'closed-polygon', 2: 'polyline'}.get(self.shape_kind, '?')
            trunc = '  (TRUNCATED)' if self.name_truncated else ''
            lines += [
                f'  shape_kind    : {kind_name}({self.shape_kind})  ->  {format(self.shape_kind, "02b")}',
                f'  name_len      : {len(self.name)} chars{trunc}  ->  {self.name_len_bits}',
                f'  name          : {self.name!r}  ->  {self.name_ascii_bits}  [{len(self.name_ascii_bits)}b]',
            ]
            if self.shape_kind == 0:
                lines += [f'  radius        : {self.radius_m} m  ->  {format(self.radius_m, "016b")}']
            else:
                lines += [f'  points        : {len(self.shape_points)}  (first abs + {len(self.shape_points) - 1} deltas)']
        elif self.mode == 5:
            trunc = '  (TRUNCATED)' if self.name_truncated else ''
            m = self.medevac
            lines += [
                f'  title_len     : {len(self.name)} chars{trunc}  ->  {self.name_len_bits}',
                f'  title         : {self.name!r}  ->  {self.name_ascii_bits}  [{len(self.name_ascii_bits)}b]',
                f'  freq          : {m.get("freq_mhz", 0.0)} MHz',
                f'  patients      : urgent={m.get("urgent", 0)} urgent_surgical={m.get("urgent_surgical", 0)} '
                f'priority={m.get("priority", 0)} routine={m.get("routine", 0)} convenience={m.get("convenience", 0)}',
                f'  litter/amb    : {m.get("litter", 0)}/{m.get("ambulatory", 0)}',
                f'  flags         : casevac={m.get("casevac", False)} equipment_none={m.get("equipment_none", False)} '
                f'terrain_none={m.get("terrain_none", False)}',
                f'  sec/hlz/zone  : {m.get("security", 0)}/{m.get("hlz_marking", 0)}/{m.get("zone_prot", 0)}',
            ]
        if self.mode != 3:
            lines += [
                f'  lat           : {self.lat}  ->  {self.lat_int}  ->  {self.lat_bits}  [21b]',
                f'  lon           : {self.lon}  ->  {self.lon_int}  ->  {self.lon_bits}  [22b]',
            ]
        lines += [
            f'  total_bits    : {self.bit_count}  ({self.byte_count} bytes)',
            f'  full_stream   : {self.bits}',
        ]
        return '\n'.join(lines)


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _ita2_encode_callsign(callsign: str) -> str:
    """Encode header callsign to ITA2 bits with shift handling + CR terminator."""
    callsign = callsign.upper()[:MAX_CS_CHARS]
    bits = ''
    in_figures = False
    for ch in callsign:
        if ch in _ITA2_LETTERS:
            if in_figures:
                bits += _ITA2_LETTERS['LTRS']
                in_figures = False
            bits += _ITA2_LETTERS[ch]
        elif ch in _ITA2_FIGURES:
            if not in_figures:
                bits += _ITA2_LETTERS['FIGS']
                in_figures = True
            bits += _ITA2_FIGURES[ch]
        else:
            raise ValueError(f'Character {ch!r} is not ITA2-encodable')
    if in_figures:
        bits += _ITA2_LETTERS['LTRS']
    bits += _ITA2_LETTERS['CR_TERM']
    return bits


def _ita2_encode_text(text: str) -> str:
    """
    ITA2-encode free text (Mode 4 chat body), CR-terminated.

    Same wire format as the header callsign: 5 bits/char with FIGS/LTRS
    shift handling.  Text is uppercased (ITA2 has no lowercase); characters
    with no ITA2 code are replaced with '?' instead of raising.
    """
    bits = ''
    in_figures = False
    for ch in text.upper():
        if ch not in _ITA2_LETTERS and ch not in _ITA2_FIGURES:
            ch = '?'
        if ch in _ITA2_LETTERS:
            if in_figures:
                bits += _ITA2_LETTERS['LTRS']
                in_figures = False
            bits += _ITA2_LETTERS[ch]
        else:
            if not in_figures:
                bits += _ITA2_LETTERS['FIGS']
                in_figures = True
            bits += _ITA2_FIGURES[ch]
    if in_figures:
        bits += _ITA2_LETTERS['LTRS']
    bits += _ITA2_LETTERS['CR_TERM']
    return bits


def _encode_name(name: str):
    """Return (encoded_name, was_truncated, len_bits_3, ascii_bits)."""
    truncated = len(name) > MAX_NAME_CHARS
    enc = name[:MAX_NAME_CHARS]
    len_bits  = format(len(enc), '03b')
    ascii_bits = ''.join(format(ord(c), '08b') for c in enc)
    return enc, truncated, len_bits, ascii_bits


def _encode_coords(lat: float, lon: float):
    """Return (lat_int, lat_21b, lon_int, lon_22b). Scale ×10,000."""
    lat_int = round(lat * 10000)
    lon_int = round(lon * 10000)
    if not (-900000 <= lat_int <= 900000):
        raise ValueError(f'Latitude {lat} out of range (−90 to +90)')
    if not (-1800000 <= lon_int <= 1800000):
        raise ValueError(f'Longitude {lon} out of range (−180 to +180)')
    lat_bits = format(lat_int & 0x1FFFFF, '021b')
    lon_bits = format(lon_int & 0x3FFFFF, '022b')
    return lat_int, lat_bits, lon_int, lon_bits


def _detect_format(data) -> str:
    if isinstance(data, str):
        return 'xml'
    if isinstance(data, (bytes, bytearray)):
        return 'xml' if data.lstrip().startswith(b'<') else 'takproto'
    raise TypeError(f'Expected str or bytes, got {type(data)}')


def _detect_mode(cot_type: str) -> int:
    return _MODE_BY_COT_TYPE.get(cot_type, _DEFAULT_MODE)


def _is_spot(cot_type: str) -> bool:
    return not any(cot_type.startswith(p) for p in _PLI_PREFIXES)


def _int_attr(attrs: dict, key: str, default: int = 0) -> int:
    """Read an integer attribute tolerant of '3', '3.0', missing, or junk."""
    try:
        return int(float(attrs.get(key, default)))
    except (TypeError, ValueError):
        return default


def _bool_attr(attrs: dict, key: str) -> bool:
    """Read a boolean attribute ('true'/'True' → True)."""
    return str(attrs.get(key, '')).strip().lower() == 'true'


# =============================================================================
# FORMAT PARSERS
# Each parser returns a dict consumed by the appropriate mode builder.
# =============================================================================

def _parse_xml(data) -> dict:
    if isinstance(data, bytes):
        data = data.decode('utf-8', errors='replace')
    root = ET.fromstring(data)
    cot_type = root.get('type', '')
    point = root.find('point')
    if point is None:
        raise ValueError('CoT XML has no <point> element')
    lat = float(point.get('lat', 0))
    lon = float(point.get('lon', 0))
    detail  = root.find('detail')
    hbc_mode = _detect_mode(cot_type)

    # ------------------------------------------------------------------
    # Mode 1 — PLI / Spot
    # ------------------------------------------------------------------
    if hbc_mode == 1:
        callsign = name = ''
        iconpath = ''
        tint = None
        if detail is not None:
            uid_el = detail.find('uid')
            if uid_el is not None:
                callsign = uid_el.get('Droid', '')
            contact = detail.find('contact')
            if contact is not None:
                cs = contact.get('callsign', '')
                name = cs
                if not callsign:
                    callsign = cs
            creator = detail.find('creator')
            if creator is not None:
                callsign = creator.get('callsign', callsign)
            usericon = detail.find('usericon')
            if usericon is not None:
                iconpath = usericon.get('iconsetpath', '')
            color = detail.find('color')
            if color is not None and color.get('argb'):
                try:
                    tint = int(color.get('argb'))
                except ValueError:
                    tint = None
        if not name:
            name = callsign
        if _is_spot(cot_type):
            # v1.3: spots/markers prefer Mode 6 (extended marker);
            # encode() falls back to Mode 1 if unencodable.
            return dict(hbc_mode=6, cot_type=cot_type,
                        callsign=callsign, name=name, lat=lat, lon=lon,
                        iconpath=iconpath, tint=tint)
        return dict(hbc_mode=1, cot_type=cot_type,
                    callsign=callsign, name=name, lat=lat, lon=lon)

    # ------------------------------------------------------------------
    # Mode 2 — Alert (active or cancelled)
    # Active (b-a-o-tbl): alert callsign from <contact>; originator from
    # the segment before '-' in that callsign.
    # Cancel (b-a-o-can): originator is the TEXT CONTENT of
    # <emergency cancel="true">CALLSIGN</emergency>; no alert name.
    # ------------------------------------------------------------------
    if hbc_mode == 2:
        if cot_type == 'b-a-o-can':
            originator = ''
            if detail is not None:
                emergency = detail.find('emergency')
                if emergency is not None and emergency.text:
                    originator = emergency.text.strip()
            # Header callsign = originator (self-cancel; sender owns the alert)
            return dict(hbc_mode=2, cot_type=cot_type, callsign=originator,
                        alert_callsign='', active=False, lat=lat, lon=lon)
        alert_callsign = ''
        if detail is not None:
            contact = detail.find('contact')
            if contact is not None:
                alert_callsign = contact.get('callsign', '')
        orig_name = alert_callsign.split('-')[0] if alert_callsign else ''
        return dict(hbc_mode=2, cot_type=cot_type,
                    callsign=orig_name, alert_callsign=alert_callsign,
                    active=True, lat=lat, lon=lon)

    # ------------------------------------------------------------------
    # Mode 3 — GeoChat
    # Sender callsign from __chat/@senderCallsign; text from <remarks>.
    #
    # Destination classification (v1.4):
    #   chatroom missing or "All Chat Rooms"  -> CHAT_DEST_ALL (broadcast)
    #   <chatgrp> has 3+ uidN members          -> CHAT_DEST_ROOM (named room)
    #   otherwise (exactly uid0 + uid1)        -> CHAT_DEST_DM (direct message;
    #                                              chatroom carries the
    #                                              recipient's callsign, as
    #                                              ATAK labels a 1:1 chat tab)
    # ------------------------------------------------------------------
    if hbc_mode == 3:
        sender = message = chatroom = ''
        dest_kind = CHAT_DEST_ALL
        chat_room = chat_recipient = ''
        if detail is not None:
            chat = detail.find('__chat')
            if chat is not None:
                sender = chat.get('senderCallsign', '')
                chatroom = chat.get('chatroom', '') or chat.get('id', '')
                chatgrp = chat.find('chatgrp')
                member_count = 0
                if chatgrp is not None:
                    member_count = sum(
                        1 for k in chatgrp.keys()
                        if k.startswith('uid') and k[3:].isdigit())
                if not chatroom or chatroom.strip().lower() == 'all chat rooms':
                    dest_kind = CHAT_DEST_ALL
                elif member_count >= 3:
                    dest_kind = CHAT_DEST_ROOM
                    chat_room = chatroom
                else:
                    dest_kind = CHAT_DEST_DM
                    chat_recipient = chatroom
            remarks = detail.find('remarks')
            if remarks is not None and remarks.text:
                message = remarks.text.strip()
        return dict(hbc_mode=3, cot_type=cot_type,
                    callsign=sender, message=message,
                    dest_kind=dest_kind, chat_room=chat_room,
                    chat_recipient=chat_recipient)

    # ------------------------------------------------------------------
    # Mode 4 — Shape (circle / rectangle / freeform)
    # Circle radius from shape/ellipse/@major; polygon corners from
    # <link point="lat,lon"/> entries.  Header callsign from <creator>.
    # ------------------------------------------------------------------
    if hbc_mode == 4:
        name = creator_cs = ''
        if detail is not None:
            contact = detail.find('contact')
            if contact is not None:
                name = contact.get('callsign', '')
            creator = detail.find('creator')
            if creator is not None:
                creator_cs = creator.get('callsign', '')
        if cot_type == 'u-d-c-c':
            radius = 0.0
            shape_el = detail.find('shape') if detail is not None else None
            if shape_el is not None:
                ellipse = shape_el.find('ellipse')
                if ellipse is not None:
                    radius = float(ellipse.get('major', 0))
            return dict(hbc_mode=4, cot_type=cot_type,
                        callsign=creator_cs or name, name=name,
                        kind=0, points=[(lat, lon)], radius_m=radius)
        pts = []
        if detail is not None:
            for link in detail.findall('link'):
                pt = link.get('point')
                if pt:
                    try:
                        la, lo = pt.split(',')[:2]
                        pts.append((float(la), float(lo)))
                    except ValueError:
                        pass
        if len(pts) < 2:
            raise ValueError(f'{cot_type} has fewer than 2 link points')
        kind = 1                                   # closed polygon
        if cot_type == 'u-d-f':
            if len(pts) > 2 and pts[0] == pts[-1]:
                pts = pts[:-1]                     # drop duplicate closing point
            else:
                kind = 2                           # open polyline
        return dict(hbc_mode=4, cot_type=cot_type,
                    callsign=creator_cs or name, name=name,
                    kind=kind, points=pts, radius_m=0.0)

    # ------------------------------------------------------------------
    # Mode 5 — CASEVAC / MEDEVAC
    # 9-line numeric fields from the <_medevac_> attributes.
    # Header callsign from link/@parent_callsign (fallback: contact).
    # ------------------------------------------------------------------
    if hbc_mode == 5:
        med = {}
        callsign = ''
        if detail is not None:
            mv = detail.find('_medevac_')
            if mv is not None:
                med = dict(mv.attrib)
            link_el = detail.find('link')
            if link_el is not None:
                callsign = link_el.get('parent_callsign', '')
            if not callsign:
                contact = detail.find('contact')
                if contact is not None:
                    callsign = contact.get('callsign', '')
        return dict(hbc_mode=5, cot_type=cot_type, callsign=callsign,
                    title=med.get('title', ''), med=med, lat=lat, lon=lon)

    # ------------------------------------------------------------------
    # ADDING A NEW MODE — XML path:
    # Add an `if hbc_mode == N:` block here.
    # ------------------------------------------------------------------
    raise ValueError(f'No XML parser for HBC mode {hbc_mode}')


def _parse_takproto(data: bytes) -> dict:
    try:
        from takproto.functions import parse_proto
    except ImportError:
        raise ImportError('takproto library required: pip install takproto')

    msg = parse_proto(data)
    if msg is None:
        raise ValueError('parse_proto() returned None — not a valid takproto packet')

    cot      = msg.cotEvent
    cot_type = cot.type
    lat, lon = cot.lat, cot.lon
    hbc_mode = _detect_mode(cot_type)

    if lat == 0.0 and lon == 0.0 and hbc_mode != 3:   # Mode 3 chat carries no position
        import warnings
        warnings.warn(
            'lat=0.0 and lon=0.0 from takproto — proto3 omits default-value '
            'coordinates. Verify the source packet contains real coordinates.',
            UserWarning
        )

    # ------------------------------------------------------------------
    # Mode 1 — PLI / Spot
    # ------------------------------------------------------------------
    if hbc_mode == 1:
        callsign = cot.detail.contact.callsign
        name = callsign
        if cot.detail.xmlDetail:
            m = re.search(r'<uid\s+Droid=["\']([^"\']+)["\']',
                          cot.detail.xmlDetail)
            if m:
                name = m.group(1)
                if not callsign:
                    callsign = name
        return dict(hbc_mode=1, cot_type=cot_type,
                    callsign=callsign, name=name, lat=lat, lon=lon)

    # ------------------------------------------------------------------
    # Mode 2 — Alert, active or cancelled (takproto path)
    # Originator: prefer <emergency>text</emergency> in xmlDetail, then
    # fall back to splitting contact.callsign on '-'.
    # ------------------------------------------------------------------
    if hbc_mode == 2:
        xd = cot.detail.xmlDetail or ''
        if cot_type == 'b-a-o-can':
            originator = ''
            m = re.search(r'<emergency[^>]*>([^<]+)</emergency>', xd)
            if m:
                originator = m.group(1).strip()
            return dict(hbc_mode=2, cot_type=cot_type, callsign=originator,
                        alert_callsign='', active=False, lat=lat, lon=lon)
        alert_callsign = cot.detail.contact.callsign
        orig_name = alert_callsign.split('-')[0] if alert_callsign else ''
        m = re.search(r'<emergency[^>]*>([^<]+)</emergency>', xd)
        if m:
            orig_name = m.group(1).strip()
        return dict(hbc_mode=2, cot_type=cot_type,
                    callsign=orig_name, alert_callsign=alert_callsign,
                    active=True, lat=lat, lon=lon)

    # ------------------------------------------------------------------
    # Mode 3 — GeoChat (takproto path)
    # __chat and <remarks> are non-standard details carried in xmlDetail.
    # Destination classification mirrors the XML path (see _parse_xml).
    # ------------------------------------------------------------------
    if hbc_mode == 3:
        xd = cot.detail.xmlDetail or ''
        sender = message = chatroom = ''
        dest_kind = CHAT_DEST_ALL
        chat_room = chat_recipient = ''
        m = re.search(r'<__chat[^>]*\bsenderCallsign=["\']([^"\']*)["\']', xd)
        if m:
            sender = m.group(1)
        m = re.search(r'<__chat[^>]*\bchatroom=["\']([^"\']*)["\']', xd)
        if m:
            chatroom = m.group(1)
        cg = re.search(r'<chatgrp([^>]*)/?>', xd)
        member_count = len(re.findall(r'\buid\d+=', cg.group(1))) if cg else 0
        if not chatroom or chatroom.strip().lower() == 'all chat rooms':
            dest_kind = CHAT_DEST_ALL
        elif member_count >= 3:
            dest_kind = CHAT_DEST_ROOM
            chat_room = chatroom
        else:
            dest_kind = CHAT_DEST_DM
            chat_recipient = chatroom
        m = re.search(r'<remarks[^>]*>([^<]*)</remarks>', xd)
        if m:
            message = m.group(1).strip()
        return dict(hbc_mode=3, cot_type=cot_type,
                    callsign=sender, message=message,
                    dest_kind=dest_kind, chat_room=chat_room,
                    chat_recipient=chat_recipient)

    # ------------------------------------------------------------------
    # Mode 4 — Shape (takproto path)
    # ------------------------------------------------------------------
    if hbc_mode == 4:
        xd = cot.detail.xmlDetail or ''
        name = cot.detail.contact.callsign
        if not name:
            m = re.search(r'<contact[^>]*\bcallsign=["\']([^"\']*)["\']', xd)
            if m:
                name = m.group(1)
        creator_cs = ''
        m = re.search(r'<creator[^>]*\bcallsign=["\']([^"\']*)["\']', xd)
        if m:
            creator_cs = m.group(1)
        if cot_type == 'u-d-c-c':
            radius = 0.0
            m = re.search(r'<ellipse[^>]*\bmajor=["\']([^"\']*)["\']', xd)
            if m:
                radius = float(m.group(1))
            return dict(hbc_mode=4, cot_type=cot_type,
                        callsign=creator_cs or name, name=name,
                        kind=0, points=[(lat, lon)], radius_m=radius)
        pts = []
        for pt in re.findall(r'<link[^>]*\bpoint=["\']([^"\']*)["\']', xd):
            try:
                la, lo = pt.split(',')[:2]
                pts.append((float(la), float(lo)))
            except ValueError:
                pass
        if len(pts) < 2:
            raise ValueError(f'{cot_type} has fewer than 2 link points')
        kind = 1
        if cot_type == 'u-d-f':
            if len(pts) > 2 and pts[0] == pts[-1]:
                pts = pts[:-1]
            else:
                kind = 2
        return dict(hbc_mode=4, cot_type=cot_type,
                    callsign=creator_cs or name, name=name,
                    kind=kind, points=pts, radius_m=0.0)

    # ------------------------------------------------------------------
    # Mode 5 — CASEVAC / MEDEVAC (takproto path)
    # ------------------------------------------------------------------
    if hbc_mode == 5:
        xd = cot.detail.xmlDetail or ''
        med = {}
        m = re.search(r'<_medevac_([^>]*?)/?>', xd)
        if m:
            med = dict(re.findall(r'(\w+)=["\']([^"\']*)["\']', m.group(1)))
        callsign = ''
        m = re.search(r'<link[^>]*\bparent_callsign=["\']([^"\']*)["\']', xd)
        if m:
            callsign = m.group(1)
        if not callsign:
            callsign = cot.detail.contact.callsign
        return dict(hbc_mode=5, cot_type=cot_type, callsign=callsign,
                    title=med.get('title', ''), med=med, lat=lat, lon=lon)

    # ------------------------------------------------------------------
    # ADDING A NEW MODE — takproto path:
    # Add an `if hbc_mode == N:` block here.
    # ------------------------------------------------------------------
    raise ValueError(f'No takproto parser for HBC mode {hbc_mode}')


# =============================================================================
# MODE BUILDERS
# Each builder assembles an HBCMessage from the parser output.
# =============================================================================

def _build_mode1(*, cot_type, callsign, name, lat, lon, source_format) -> HBCMessage:
    spot = _is_spot(cot_type)
    cs_bits = _ita2_encode_callsign(callsign)
    name_enc, name_trunc, name_len_bits, name_ascii_bits = _encode_name(name)
    lat_int, lat_bits, lon_int, lon_bits = _encode_coords(lat, lon)
    return HBCMessage(
        mode=1, source_format=source_format, cot_type=cot_type,
        callsign=callsign, lat=lat, lon=lon,
        lat_int=lat_int, lon_int=lon_int,
        callsign_bits=cs_bits, lat_bits=lat_bits, lon_bits=lon_bits,
        is_spot=spot, name=name_enc, name_truncated=name_trunc,
        pli_bit='1' if spot else '0',
        name_len_bits=name_len_bits, name_ascii_bits=name_ascii_bits,
    )


def _build_mode2(*, cot_type, callsign, alert_callsign, active, lat, lon, source_format) -> HBCMessage:
    """Mode 2 — Alert (active or cancelled).

    Wire format (payload only; header is standard callsign+version+mode):
      alert_status    [1 bit]    1 = active (show on map), 0 = cancelled (remove)
      alert_name_len  [3 bits] + alert_name ASCII [0–56 b]  (empty for cancels)
      originator_len  [3 bits] + originator ASCII [0–56 b]  whose HBC-{CS}-911
                                                             marker this targets
      latitude        [21 bits]
      longitude       [22 bits]
    """
    cs_bits = _ita2_encode_callsign(callsign)
    alert_enc, alert_trunc, alert_len_bits, alert_name_bits = _encode_name(alert_callsign)
    orig_enc,  _,           orig_len_bits,  orig_name_bits  = _encode_name(callsign)
    lat_int, lat_bits, lon_int, lon_bits = _encode_coords(lat, lon)
    return HBCMessage(
        mode=2, source_format=source_format, cot_type=cot_type,
        callsign=callsign, lat=lat, lon=lon,
        lat_int=lat_int, lon_int=lon_int,
        callsign_bits=cs_bits, lat_bits=lat_bits, lon_bits=lon_bits,
        alert_active=active,
        alert_name=alert_enc, alert_name_truncated=alert_trunc, orig_name=orig_enc,
        alert_len_bits=alert_len_bits, alert_name_bits=alert_name_bits,
        orig_len_bits=orig_len_bits, orig_name_bits=orig_name_bits,
    )


def _build_mode3(*, cot_type, callsign, message, source_format,
                  dest_kind=CHAT_DEST_ALL, chat_room='', chat_recipient='') -> HBCMessage:
    """Mode 3 — GeoChat Text Message (v1.4 adds addressed destinations).

    Wire format (payload only; header is standard callsign+version+mode):
      dest_kind          [2 bits]  00 = All Chat Rooms, 01 = Named Room,
                                   10 = Direct Message, 11 = reserved
      [Named Room]       room name        ITA2, CR-terminated (free text)
      [Direct Message]   recipient        ITA2, CR-terminated (max 8 chars,
                                           same alphabet as the header callsign)
      message            ITA2-encoded, CR-terminated  (5 bits/char + shifts)

    No coordinates are transmitted — TAK chat events carry no meaningful
    position (WinTAK sends lat=0 lon=0).  Text is uppercased by ITA2.
    """
    cs_bits   = _ita2_encode_callsign(callsign)
    chat_bits = _ita2_encode_text(message)

    dest_bits = format(dest_kind, '02b')
    room = recipient = ''
    if dest_kind == CHAT_DEST_ROOM:
        room = chat_room
        dest_bits += _ita2_encode_text(chat_room)
    elif dest_kind == CHAT_DEST_DM:
        recipient = chat_recipient.upper()[:MAX_CS_CHARS]
        dest_bits += _ita2_encode_callsign(chat_recipient)

    return HBCMessage(
        mode=3, source_format=source_format, cot_type=cot_type,
        callsign=callsign, lat=0.0, lon=0.0,
        lat_int=0, lon_int=0,
        callsign_bits=cs_bits, lat_bits='', lon_bits='',
        chat_text=message, chat_bits=chat_bits,
        chat_dest_kind=dest_kind, chat_room=room, chat_recipient=recipient,
        chat_dest_bits=dest_bits,
    )


def _build_mode4(*, cot_type, callsign, name, kind, points, radius_m, source_format) -> HBCMessage:
    """Mode 4 — Shape (circle / closed polygon / open polyline).

    Wire format (payload only):
      shape_kind  [2 bits]   00=circle, 01=closed polygon, 10=polyline, 11=reserved
      name_len    [3 bits] + name ASCII [0–56 bits]
      circle    : lat [21] + lon [22] + radius_m [16 bits, unsigned meters]
      polygon   : count [4 bits, 2–15] + first lat [21] + lon [22]
                  + (count-1) × (dlat [14] + dlon [14], signed ×10,000 units)
    """
    cs_bits = _ita2_encode_callsign(callsign)
    name_enc, name_trunc, name_len_bits, name_ascii_bits = _encode_name(name)
    if kind == 0:
        lat, lon = points[0]
        lat_int, lat_bits, lon_int, lon_bits = _encode_coords(lat, lon)
        r = int(round(radius_m))
        if not (0 <= r <= 65535):
            raise ValueError(f'Circle radius {radius_m} m out of range (0-65535)')
        shape_bits = lat_bits + lon_bits + format(r, '016b')
        radius_int = r
    else:
        if not (2 <= len(points) <= MAX_SHAPE_POINTS):
            raise ValueError(f'Polygon needs 2-{MAX_SHAPE_POINTS} points, got {len(points)}')
        lat, lon = points[0]
        lat_int, lat_bits, lon_int, lon_bits = _encode_coords(lat, lon)
        shape_bits = format(len(points), '04b') + lat_bits + lon_bits
        prev_la, prev_lo = round(lat * 10000), round(lon * 10000)
        for la, lo in points[1:]:
            ila, ilo = round(la * 10000), round(lo * 10000)
            dla, dlo = ila - prev_la, ilo - prev_lo
            if not (-8192 <= dla <= 8191 and -8192 <= dlo <= 8191):
                raise ValueError('Polygon segment exceeds the ±0.8191° delta limit')
            shape_bits += format(dla & 0x3FFF, '014b') + format(dlo & 0x3FFF, '014b')
            prev_la, prev_lo = ila, ilo
        radius_int = 0
    return HBCMessage(
        mode=4, source_format=source_format, cot_type=cot_type,
        callsign=callsign, lat=lat, lon=lon,
        lat_int=lat_int, lon_int=lon_int,
        callsign_bits=cs_bits, lat_bits=lat_bits, lon_bits=lon_bits,
        name=name_enc, name_truncated=name_trunc,
        name_len_bits=name_len_bits, name_ascii_bits=name_ascii_bits,
        shape_kind=kind, radius_m=radius_int,
        shape_points=list(points), shape_bits=shape_bits,
    )


def _build_mode5(*, cot_type, callsign, title, med, lat, lon, source_format) -> HBCMessage:
    """Mode 5 — CASEVAC / MEDEVAC (9-line numeric fields).

    Wire format (payload only):
      title_len [3] + title ASCII [0–56]
      freq            [16 bits]  10 kHz steps (0 = unknown; 0–655.35 MHz)  — line 2
      urgent, urgent_surgical, priority, routine, convenience  [4 bits each] — line 3
      litter [4] + ambulatory [4]                                            — line 5
      flags  [4 bits]  bit3=casevac  bit2=equipment_none  bit1=terrain_none  bit0=reserved
      security [2] + hlz_marking [3] + zone_prot [2]                         — lines 6/7
      lat [21] + lon [22]                                                    — line 1
    """
    cs_bits = _ita2_encode_callsign(callsign)
    name_enc, name_trunc, name_len_bits, name_ascii_bits = _encode_name(title)
    lat_int, lat_bits, lon_int, lon_bits = _encode_coords(lat, lon)

    def clamp(v, hi):
        return max(0, min(hi, v))

    try:
        freq_mhz = float(med.get('freq', 0.0))
    except (TypeError, ValueError):
        freq_mhz = 0.0
    freq_units = clamp(int(round(freq_mhz * 100)), 65535)

    count_keys = ('urgent', 'urgent_surgical', 'priority', 'routine',
                  'convenience', 'litter', 'ambulatory')
    counts = {k: clamp(_int_attr(med, k), 15) for k in count_keys}
    flags = ((8 if _bool_attr(med, 'casevac') else 0)
             | (4 if _bool_attr(med, 'equipment_none') else 0)
             | (2 if _bool_attr(med, 'terrain_none') else 0))
    security = clamp(_int_attr(med, 'security'), 3)
    hlz      = clamp(_int_attr(med, 'hlz_marking'), 7)
    zone     = clamp(_int_attr(med, 'zone_prot_selection'), 3)

    med_bits = (format(freq_units, '016b')
                + ''.join(format(counts[k], '04b') for k in
                          ('urgent', 'urgent_surgical', 'priority',
                           'routine', 'convenience'))
                + format(counts['litter'], '04b')
                + format(counts['ambulatory'], '04b')
                + format(flags, '04b')
                + format(security, '02b')
                + format(hlz, '03b')
                + format(zone, '02b'))
    medevac = dict(freq_mhz=freq_units / 100.0,
                   casevac=_bool_attr(med, 'casevac'),
                   equipment_none=_bool_attr(med, 'equipment_none'),
                   terrain_none=_bool_attr(med, 'terrain_none'),
                   security=security, hlz_marking=hlz, zone_prot=zone,
                   **counts)
    return HBCMessage(
        mode=5, source_format=source_format, cot_type=cot_type,
        callsign=callsign, lat=lat, lon=lon,
        lat_int=lat_int, lon_int=lon_int,
        callsign_bits=cs_bits, lat_bits=lat_bits, lon_bits=lon_bits,
        name=name_enc, name_truncated=name_trunc,
        name_len_bits=name_len_bits, name_ascii_bits=name_ascii_bits,
        medevac=medevac, med_bits=med_bits,
    )


def _build_mode6(*, cot_type, callsign, name, lat, lon, iconpath, tint,
                 source_format) -> HBCMessage:
    """Mode 6 — Extended Marker (HBC v1.3).

    Wire format (payload only; header is standard callsign+version+mode 101):
      name_len   [3 bits] + name ASCII [0-56 bits]
      latitude   [21 bits] + longitude [22 bits]
      type       [4-bit token count N] + N x [6-bit charset index]
                 (dash-separated single-char tokens of the CoT type;
                  charset = 0-9, A-Z, a-z)
      icon_kind  [2 bits]
        00 none        derive symbol purely from the CoT type
        01 2525C       receiver rebuilds COT_MAPPING_2525C/<a-x>/<type>
        10 spot map    + palette index [4 bits] (15 = raw ARGB [32 bits])
        11 custom set  + iconset UUID [128 bits] + subpath (ITA2, CR-term)
      tint       [1 bit]  (1 -> 32-bit ARGB <color> follows; suppressed for
                           spot map, whose color is carried above)

    Raises ValueError when unencodable (multi-char type tokens, non-UUID
    custom paths) so encode() can fall back to Mode 1.
    """
    tokens = cot_type.split('-')
    if not (1 <= len(tokens) <= 15):
        raise ValueError(f'Mode 6: token count {len(tokens)}')
    token_idx = []
    for t in tokens:
        if len(t) != 1 or t not in TOKEN_CHARSET:
            raise ValueError(f'Mode 6: bad token {t!r}')
        token_idx.append(TOKEN_CHARSET.index(t))

    # icon kind
    spot_argb = 0
    uuid_bytes = b''
    subpath = ''
    if not iconpath:
        kind = 0
    elif iconpath.startswith('COT_MAPPING_2525'):
        kind = 1
    elif iconpath.startswith('COT_MAPPING_SPOTMAP'):
        kind = 2
        try:
            spot_argb = int(iconpath.split('/')[-1]) & 0xFFFFFFFF
        except ValueError:
            spot_argb = (tint & 0xFFFFFFFF) if tint is not None else 0xFFFFFFFF
    else:
        import uuid as _uuid
        if len(iconpath) < 37 or iconpath[36] != '/':
            raise ValueError('Mode 6: iconsetpath not UUID-prefixed')
        try:
            uuid_bytes = _uuid.UUID(iconpath[:36]).bytes
        except ValueError:
            raise ValueError('Mode 6: bad iconset UUID')
        subpath = iconpath[37:]
        kind = 3

    cs_bits = _ita2_encode_callsign(callsign)
    name_enc, name_trunc, name_len_bits, name_ascii_bits = _encode_name(name)
    lat_int, lat_bits, lon_int, lon_bits = _encode_coords(lat, lon)

    bits = name_len_bits + name_ascii_bits + lat_bits + lon_bits
    bits += format(len(tokens), '04b')
    bits += ''.join(format(i, '06b') for i in token_idx)
    bits += format(kind, '02b')
    if kind == 2:
        if spot_argb in [c & 0xFFFFFFFF for c in SPOT_COLORS]:
            bits += format([c & 0xFFFFFFFF for c in SPOT_COLORS].index(spot_argb), '04b')
        else:
            bits += format(15, '04b') + format(spot_argb, '032b')
    elif kind == 3:
        bits += ''.join(format(b, '08b') for b in uuid_bytes)
        bits += _ita2_encode_text(subpath)
    if kind != 2 and tint is not None:
        bits += '1' + format(tint & 0xFFFFFFFF, '032b')
    else:
        bits += '0'

    return HBCMessage(
        mode=6, source_format=source_format, cot_type=cot_type,
        callsign=callsign, lat=lat, lon=lon,
        lat_int=lat_int, lon_int=lon_int,
        callsign_bits=cs_bits, lat_bits=lat_bits, lon_bits=lon_bits,
        name=name_enc, name_truncated=name_trunc,
        name_len_bits=name_len_bits, name_ascii_bits=name_ascii_bits,
        icon_kind=kind, mode6_bits=bits,
    )


# ADDING A NEW MODE — builder:
# def _build_modeN(*, cot_type, callsign, <mode-specific fields>, lat, lon, source_format) -> HBCMessage:
#     ...


# =============================================================================
# MODE DISPATCH TABLE
# Register new modes here: mode_number -> builder function
# =============================================================================
_BUILDERS = {
    1: _build_mode1,
    2: _build_mode2,
    3: _build_mode3,
    4: _build_mode4,
    5: _build_mode5,
    6: _build_mode6,
}


# =============================================================================
# PUBLIC API
# =============================================================================

def encode(data) -> HBCMessage:
    """
    Encode a CoT message into HBC binary format.

    Parameters
    ----------
    data : str | bytes
        - str   → CoT XML text
        - bytes starting with b'<' → CoT XML bytes
        - other bytes → takproto binary (TAK Protocol protobuf)

    Returns
    -------
    HBCMessage
        Call .to_bytes() to get the binary payload ready for transport.
    """
    fmt    = _detect_format(data)
    fields = _parse_xml(data) if fmt == 'xml' else _parse_takproto(data)
    mode   = fields.pop('hbc_mode')
    builder = _BUILDERS.get(mode)
    if builder is None:
        raise ValueError(f'No builder registered for HBC mode {mode}')
    if mode == 6:
        try:
            return builder(source_format=fmt, **fields)
        except ValueError:
            # unencodable as extended marker -> plain Mode 1 spot
            fields = dict(cot_type=fields['cot_type'],
                          callsign=fields['callsign'], name=fields['name'],
                          lat=fields['lat'], lon=fields['lon'])
            return _build_mode1(source_format=fmt, **fields)
    return builder(source_format=fmt, **fields)


# =============================================================================
# SELF-TEST  (python hbc_encoder.py)
# =============================================================================
if __name__ == '__main__':

    TESTS = [
        # (label, input)
        ('Mode 1 — XML PLI (ONYX)',
         '''<event version="2.0" uid="ANDROID-636688233" type="a-f-G-U-C" how="m-g">
              <point lat="39.871776" lon="-98.324262" hae="245.901" ce="2.5" le="9999999" />
              <detail><contact callsign="ONYX" /><uid Droid="ONYX" /></detail>
            </event>'''),

        ('Mode 1 — XML Spot (U.17.124805)',
         '''<event version="2.0" uid="f1907ab4" type="a-u-G" how="h-g-i-g-o">
              <point lat="39.871743" lon="-100.324462" hae="219.631" ce="9999999" le="9999999" />
              <detail>
                <creator callsign="ONYX" type="a-f-G-U-C" uid="x" />
                <contact callsign="U.17.124805" />
              </detail>
            </event>'''),

        ('Mode 2 — XML Alert Cancel (KEYSTON cancel)',
         '''<event version="2.0" uid="ANDROID-6faa524f341bc5a0-9-1-1" type="b-a-o-can"
              time="2026-07-19T00:35:35.07Z" start="2026-07-19T00:35:35.07Z"
              stale="2026-07-19T00:35:45.07Z" how="m-g" access="Undefined">
           <point lat="38.871749" lon="-99.32417" hae="248.301" ce="2.0" le="9999999" />
           <detail><emergency cancel="true">KEYSTON</emergency></detail>
         </event>'''),

        ('Mode 2 — XML Alert (ONYX-Alert)',
         '''<event version="2.0" uid="14403346965-9-1-1" type="b-a-o-tbl" how="m-g">
              <point lat="39.871743" lon="-100.324462" hae="241.601" ce="4.5" le="9999999" />
              <detail><emergency type="911 Alert" /><contact callsign="ONYX-Alert" /></detail>
            </event>'''),

        ('Mode 2 — takproto Alert (bobby-Alert)',
         b'\xbf\x01\xbf\n\x00\x12\xf3\x01\n\tb-a-o-tbl\x12\tUndefined'
         b'*\x1114403346965-9-1-1'
         b'0\xf3\xbc\xbf\x82\xc23' b'8\xf3\xbc\xbf\x82\xc23'
         b'@\x83\x8b\xc0\x82\xc23' b'J\x03m-g'
         b'Q\x83\xa5\xba\x80\x97oC@' b'Y\x04YO\xad\xbe\xd4X\xc0'
         b'a\xac\x1cZd;Co@' b'i\xcd\xcc\xcc\xcc\xcc\xcc-@'
         b'q\x00\x00\x00\xe0\xcf\x12cA'
         b'z\x80\x01\no<link uid="ANDROID-8f2a5d78d919931a" type="a-f-G" relation="p-p"/>'
         b'<emergency type="911 Alert">bobby</emergency>'
         b'\x12\r\x12\x0bbobby-Alert'),

        # --- Modes 3-5: real WinTAK events from cot_capture.xml (8-18-26) ---
        ('Mode 3 — XML GeoChat, All Chat Rooms (RECEIVER: test message)',
         '''<event version="2.0" uid="GeoChat.S-1-5-21.All Chat Rooms.3f8d87e7" type="b-t-f"
              time="2026-08-19T01:15:28.470Z" start="2026-08-19T01:15:28.470Z"
              stale="2026-08-20T01:15:28.470Z" how="h-g-i-g-o">
            <point lat="0" lon="0" hae="9999999.0" ce="9999999.0" le="9999999.0" />
            <detail>
              <__chat id="All Chat Rooms" chatroom="All Chat Rooms" senderCallsign="RECEIVER"
                      groupOwner="false" messageId="3f8d87e7-360f-4b77-bc4e-41d6ba929705">
                <chatgrp id="All Chat Rooms" uid0="S-1-5-21" uid1="All Chat Rooms" />
              </__chat>
              <link uid="S-1-5-21" type="a-f-G-U" relation="p-p" />
              <remarks source="BAO.F.WinTAK.S-1-5-21" to="All Chat Rooms"
                       time="2026-08-19T01:15:28.47Z">test message</remarks>
            </detail>
          </event>'''),

        ('Mode 3 — XML GeoChat, Named Room (RECEIVER -> Recon Team: status check)',
         '''<event version="2.0" uid="GeoChat.S-1-5-21.9f8e7d6c.a1b2c3d4" type="b-t-f"
              time="2026-08-25T14:02:11.00Z" start="2026-08-25T14:02:11.00Z"
              stale="2026-08-26T14:02:11.00Z" how="h-g-i-g-o">
            <point lat="0" lon="0" hae="9999999.0" ce="9999999.0" le="9999999.0" />
            <detail>
              <__chat id="9f8e7d6c-0000-0000-0000-000000000000" chatroom="Recon Team"
                      senderCallsign="RECEIVER" groupOwner="false"
                      messageId="a1b2c3d4-0000-0000-0000-000000000000">
                <chatgrp id="9f8e7d6c-0000-0000-0000-000000000000" uid0="S-1-5-21"
                         uid1="ANDROID-aaaa" uid2="ANDROID-bbbb" />
              </__chat>
              <link uid="S-1-5-21" type="a-f-G-U" relation="p-p" />
              <remarks source="BAO.F.WinTAK.S-1-5-21" to="Recon Team"
                       time="2026-08-25T14:02:11.00Z">status check</remarks>
            </detail>
          </event>'''),

        ('Mode 3 — XML GeoChat, Direct Message (RECEIVER -> ONYX: helo landing zone)',
         '''<event version="2.0" uid="GeoChat.S-1-5-21.c07f979e.e0295a69" type="b-t-f"
              time="2026-08-25T14:05:00.00Z" start="2026-08-25T14:05:00.00Z"
              stale="2026-08-26T14:05:00.00Z" how="h-g-i-g-o">
            <point lat="0" lon="0" hae="9999999.0" ce="9999999.0" le="9999999.0" />
            <detail>
              <__chat id="c07f979e-0000-0000-0000-000000000000" chatroom="ONYX"
                      senderCallsign="RECEIVER" groupOwner="false"
                      messageId="e0295a69-0000-0000-0000-000000000000">
                <chatgrp id="c07f979e-0000-0000-0000-000000000000" uid0="S-1-5-21"
                         uid1="ANDROID-onyxuid" />
              </__chat>
              <link uid="S-1-5-21" type="a-f-G-U" relation="p-p" />
              <remarks source="BAO.F.WinTAK.S-1-5-21" to="ONYX"
                       time="2026-08-25T14:05:00.00Z">helo landing zone</remarks>
            </detail>
          </event>'''),

        ('Mode 4 — XML Circle (Circle 1, 346 m)',
         '''<event version="2.0" uid="858caa5a-ddca-47b0-889c-5299bfd62698" type="u-d-c-c"
              time="2026-08-19T01:21:02.510Z" start="2026-08-19T01:21:02.510Z"
              stale="2026-08-26T01:21:02.510Z" how="h-g-i-g-o">
            <point lat="38.91531734" lon="-99.17975988" hae="9999999.0" ce="9999999.0" le="9999999.0" />
            <detail>
              <fillColor value="-2130706433" /><strokeColor value="-1" />
              <creator uid="S-1-5-21" type="a-f-G-U" callsign="RECEIVER" time="2026-08-19T01:20:58:669Z" />
              <shape>
                <ellipse minor="346.236470751501" angle="360" major="346.236470751501" />
              </shape>
              <contact callsign="Circle 1" />
            </detail>
          </event>'''),

        ('Mode 4 — XML Rectangle (Rectangle 2, 4 corners)',
         '''<event version="2.0" uid="7e6ed0be-ec8d-4f68-b896-44b4252227f9" type="u-d-r"
              time="2026-08-19T01:20:53.050Z" start="2026-08-19T01:20:53.050Z"
              stale="2026-08-26T01:20:53.050Z" how="h-e">
            <point lat="38.90963393" lon="-99.20234887" hae="9999999.0" ce="9999999.0" le="9999999.0" />
            <detail>
              <creator uid="S-1-5-21" type="a-f-G-U" callsign="RECEIVER" time="2026-08-19T01:20:47:639Z" />
              <link point="38.91933019,-99.18464613" />
              <link point="38.91933019,-99.22005161" />
              <link point="38.89993498,-99.22004666" />
              <link point="38.89993498,-99.18465108" />
              <contact callsign="Rectangle 2" />
            </detail>
          </event>'''),

        ('Mode 5 — XML CASEVAC (MED.19.011941)',
         '''<event version="2.0" uid="ed60672a-a545-4e15-8f2d-9275ccd6e250" type="b-r-f-h-c"
              time="2026-08-19T01:20:26.220Z" start="2026-08-19T01:20:26.220Z"
              stale="2026-08-20T01:20:26.220Z" how="h-g-i-g-o">
            <point lat="38.92363824" lon="-99.29583102" hae="9999999.0" ce="9999999.0" le="9999999.0" />
            <detail>
              <link type="a-f-G-U" uid="S-1-5-21" parent_callsign="RECEIVER" relation="p-p"
                    production_time="2026-08-19T01:19:41Z" />
              <archive />
              <_medevac_ casevac="False" title="MED.19.011941" freq="0.0" urgent="1" routine="3"
                         priority="4" urgent_surgical="2" convenience="5" equipment_none="true"
                         ambulatory="1" security="0" hlz_marking="3" terrain_none="true"
                         obstacles="None" zone_prot_selection="0" />
              <contact callsign="RECEIVER.1" />
            </detail>
          </event>'''),
    ]

    # Optional: exercise the takproto input path for Mode 3.
    # NOTE: takproto's xml2proto() strips non-standard details (__chat,
    # remarks) from xmlDetail, so the TakMessage is built directly, the way
    # real WinTAK/ATAK mesh frames carry chat: inside detail.xmlDetail.
    try:
        from takproto.proto import TakMessage as _TakMessage
        _tm = _TakMessage()
        _ce = _tm.cotEvent
        _ce.type = 'b-t-f'
        _ce.uid  = 'GeoChat.S-1-5-21.All Chat Rooms.3f8d87e7'
        _ce.how  = 'h-g-i-g-o'
        _ce.detail.xmlDetail = (
            '<__chat id="All Chat Rooms" chatroom="All Chat Rooms" '
            'senderCallsign="RECEIVER" groupOwner="false" '
            'messageId="3f8d87e7-360f-4b77-bc4e-41d6ba929705">'
            '<chatgrp id="All Chat Rooms" uid0="S-1-5-21" uid1="All Chat Rooms"/>'
            '</__chat>'
            '<link uid="S-1-5-21" type="a-f-G-U" relation="p-p"/>'
            '<remarks source="BAO.F.WinTAK.S-1-5-21" to="All Chat Rooms" '
            'time="2026-08-19T01:15:28.47Z">test message</remarks>'
        )
        TESTS.append(('Mode 3 — takproto GeoChat (mesh frame, xmlDetail)',
                      b'\xbf\x01\xbf' + _tm.SerializeToString()))
    except Exception as _e:
        print(f'(takproto Mode 3 test skipped: {_e})\n')

    all_passed = True
    for label, data in TESTS:
        print(f'--- {label} ---')
        try:
            msg = encode(data)
            print(msg)
            assert msg.bit_count > 0
            assert len(msg.to_bytes()) == msg.byte_count
            print(f'    PASS  ({msg.bit_count} bits, {msg.byte_count} bytes)\n')
        except Exception as e:
            print(f'    FAIL: {e}\n')
            all_passed = False

    print('All tests passed.' if all_passed else 'SOME TESTS FAILED.')
