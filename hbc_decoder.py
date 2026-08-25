"""
hbc_decoder.py  —  Ham Binary Cursor on Target (HBC) Decoder
=============================================================
Converts an HBC binary payload back into a CoT XML string.

Transport boundary
------------------
  decode() accepts bytes or a bit string.  The bytes are expected to be the
  raw binary payload received from a transport layer (e.g. an OFDM audio
  demodulator).  This file does NOT implement any transport; it only converts
  data formats.

Supported HBC modes
-------------------
  Mode 1 (000) : Minimum PLI or Spot Message
  Mode 2 (001) : Alert Message — active or cancelled (1-bit alert status)
  Mode 3 (010) : GeoChat Text Message  (b-t-f — ITA2 text, CR-terminated)
  Mode 4 (011) : Shape  (u-d-c-c circle, u-d-r rectangle, u-d-f freeform)
  Mode 5 (100) : CASEVAC / MEDEVAC  (b-r-f-h-c — 9-line numeric fields)

Usage
-----
  from hbc_decoder import decode

  msg = decode(raw_bytes)          # from transport layer (bytes)
  msg = decode(bit_string)         # from a bit string (str of '0'/'1')

  msg.to_xml()    # str  — CoT XML ready for injection into TAK
  str(msg)        # human-readable decoded field summary
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET

# =============================================================================
# PROTOCOL CONSTANTS  (must match hbc_encoder.py)
# =============================================================================
HBC_VERSION    = 1
MAX_NAME_CHARS = 7
MAX_CS_CHARS   = 8

# Mode number → CoT type for PLI and Spot reconstruction
_COT_TYPE_PLI      = 'a-f-G'      # Mode 1 PLI  (moving unit, friendly ground track)
_COT_TYPE_SPOT     = 'a-u-G'      # Mode 1 Spot (map marker)
_COT_TYPE_ALERT    = 'b-a-o-tbl'  # Mode 2 Alert (active)
_COT_TYPE_CANCEL   = 'b-a-o-can'  # Mode 2 Alert (cancelled)
_COT_TYPE_CHAT     = 'b-t-f'      # Mode 3 GeoChat
_COT_TYPE_CIRCLE   = 'u-d-c-c'    # Mode 4 shape: circle
_COT_TYPE_RECT     = 'u-d-r'      # Mode 4 shape: rectangle (closed, 4 points)
_COT_TYPE_FREEFORM = 'u-d-f'      # Mode 4 shape: freeform polygon / polyline
_COT_TYPE_CASEVAC  = 'b-r-f-h-c'  # Mode 5 CASEVAC / MEDEVAC

# UID prefix—prepended to every HBC-derived CoT UID
HBC_UID_PREFIX = 'HBC'


def _derive_uid(callsign: str, mode: int, is_spot: bool = False) -> str:
    """
    Deterministic UID Derivation Rule  —  HBC Protocol v1.2
    --------------------------------------------------------
    The full device UID (e.g. ANDROID-8f2a5d78d919931a) is NOT transmitted
    over the RF link; it would cost 18+ bytes and varies per device.  Instead,
    the HBC decoder derives a stable, globally unique UID from the station
    callsign using a fixed formula:

      PLI   (Mode 1, PLI bit = 0) :  'HBC-{CALLSIGN}'      e.g. 'HBC-KE8TQB'
      Spot  (Mode 1, PLI bit = 1) :  random UUID4           (spots are one-time
                                                              placements with no
                                                              persistent entity)
      Alert (Mode 2, active or cancelled) :  'HBC-{CALLSIGN}-911'
                                             (a cancel reuses the alert's UID so
                                              TAK removes the marker)

    Rationale
    ---------
    Ham radio callsigns are globally unique by ITU regulation and do not change
    for the lifetime of a licence.  Every HBC-capable receiver applying this
    rule will independently produce the SAME UID for the SAME callsign, meaning
    TAK clients across the entire receiving network track the contact under one
    consistent identifier.  No pre-coordination or lookup table is required.

    Uniqueness guarantee
    --------------------
    The 'HBC-' prefix ensures the derived UID cannot collide with UIDs generated
    by real ATAK devices (which use 'ANDROID-', 'WinTAK-', etc.).
    """
    cs = callsign.upper()
    if mode == 1 and not is_spot:
        return f'{HBC_UID_PREFIX}-{cs}'
    if mode == 1 and is_spot:
        return str(uuid.uuid4())   # spots are ephemeral; no stable entity needed
    if mode == 2:
        # Active alert and its cancel share the same UID
        return f'{HBC_UID_PREFIX}-{cs}-911'
    # Default for future modes
    return f'{HBC_UID_PREFIX}-{cs}-M{mode}'


# =============================================================================
# ITA2 REVERSE DECODE TABLES  (HBC Protocol Spec — Table 1)
# =============================================================================
_ITA2_LETTERS_DECODE = {
    '00001': 'E', '00011': 'A', '00100': ' ', '00101': 'S',
    '00110': 'I', '00111': 'U',
    '01001': 'D', '01010': 'R', '01011': 'J', '01100': 'N',
    '01101': 'F', '01110': 'C', '01111': 'K', '10000': 'T',
    '10001': 'Z', '10010': 'L', '10011': 'W', '10100': 'H',
    '10101': 'Y', '10110': 'P', '10111': 'Q', '11000': 'O',
    '11001': 'B', '11010': 'G', '11100': 'M', '11101': 'X',
    '11110': 'V',
}

_ITA2_FIGURES_DECODE = {
    '00001': '3', '00011': '-', '00101': "'", '00110': '8',
    '00111': '7', '01001': '$', '01010': '4', '01100': ',',
    '01101': '!', '01110': ':', '01111': '(', '10000': '5',
    '10001': '"', '10010': ')', '10011': '2', '10100': '#',
    '10101': '6', '10110': '0', '10111': '1', '11000': '9',
    '11001': '?', '11010': '&', '11100': '.', '11101': '/',
    '11110': ';',
}

_ITA2_CR   = '01000'   # CR — callsign field terminator
_ITA2_FIGS = '11011'   # Figures Shift
_ITA2_LTRS = '11111'   # Letters Shift


# =============================================================================
# BIT READER  — sequential bit extraction
# =============================================================================
class BitReader:
    """
    Reads a sequence of bits from a string of '0'/'1' characters.
    Keeps an internal position cursor; raises ValueError if the stream ends
    before the requested number of bits are available.
    """
    def __init__(self, bits: str):
        self._bits = bits
        self._pos  = 0

    def read(self, n: int) -> str:
        """Read n bits as a string of '0'/'1'."""
        chunk = self._bits[self._pos: self._pos + n]
        if len(chunk) < n:
            raise ValueError(
                f'Bit stream exhausted at position {self._pos}: '
                f'need {n} bits, only {len(chunk)} remain'
            )
        self._pos += n
        return chunk

    def read_int(self, n: int) -> int:
        """Read n bits and return as an unsigned integer."""
        return int(self.read(n), 2)

    def read_signed(self, n: int) -> int:
        """Read n bits and return as a two's-complement signed integer."""
        val = self.read_int(n)
        if val >= (1 << (n - 1)):
            val -= (1 << n)
        return val

    @property
    def remaining(self) -> int:
        return len(self._bits) - self._pos


# =============================================================================
# OUTPUT DATACLASS
# =============================================================================
@dataclass
class HBCDecodedMessage:
    """
    Decoded HBC message returned by decode().

    Attributes common to all modes
    --------------------------------
    mode       HBC mode number (1, 2, …)
    version    HBC protocol version (integer)
    callsign   ITA2-decoded header callsign (transmitter)
    lat, lon   Decoded coordinate floats

    Mode-1-specific
    ---------------
    is_spot    False = PLI, True = Spot/Marker
    name       Display name (ASCII, ≤ MAX_NAME_CHARS)

    Mode-2-specific
    ---------------
    alert_active  True = active alert (show on map), False = cancelled
    alert_name    Alert callsign (ASCII, ≤ MAX_NAME_CHARS; empty for cancels)
    orig_name     Originator name (ASCII, ≤ MAX_NAME_CHARS)
    """
    mode:      int
    version:   int
    callsign:  str
    lat:       float
    lon:       float

    # Mode 1
    is_spot:   bool = False
    name:      str  = ''

    # Mode 2 — Alert (active or cancelled)
    alert_active: bool = True
    alert_name:   str  = ''
    orig_name:    str  = ''

    # Mode 3 — GeoChat
    chat_text: str = ''

    # Mode 4 — Shape (`name` above is reused for the shape label)
    shape_kind:   int  = 0     # 0 = circle, 1 = closed polygon, 2 = open polyline
    radius_m:     int  = 0
    shape_points: list = field(default_factory=list)   # [(lat, lon), ...]

    # Mode 5 — CASEVAC (`name` above is reused for the title)
    medevac: dict = field(default_factory=dict)

    # Mode 6 — Extended Marker (v1.3)
    cot_type:     str = ''    # reconstructed full CoT type string
    icon_kind:    int = 0     # 0 none, 1 2525C, 2 spotmap, 3 custom iconset
    spot_argb:    int = 0     # signed 32-bit ARGB (spot map)
    iconset_uuid: str = ''    # lowercase hyphenated iconset uuid
    icon_subpath: str = ''
    has_tint:     bool = False
    tint_argb:    int = 0

    # -------------------------------------------------------------------------
    # CoT XML reconstruction
    # -------------------------------------------------------------------------
    def to_xml(self) -> str:
        """
        Reconstruct a minimal, TAK-compatible CoT XML string.

        Fields that cannot be recovered from the HBC payload are set to the
        standard CoT sentinel / placeholder values used by ATAK when the
        data is unknown or unavailable:

          hae        → 9999999    Height Above Ellipsoid unknown (no altitude data)
          ce         → 9999999    Circular Error unknown (GPS accuracy unknown)
          le         → 9999999    Linear Error unknown (vertical accuracy unknown)
          uid        → HBC-{CALLSIGN}  (deterministic derivation rule)
          time/start → current UTC decode time (original capture time lost)
          stale      → +5 min for PLI/Alert, +1 year for Spot
          how        → m-g for PLI  (machine/GPS),  h-g-i-g-o for Spot

          track speed  → 0.0        No movement data available; assume stationary
          track course → 9999999.0  Heading unknown (standard CoT undefined sentinel)

        Note: track is added to PLI only.  Spot markers are placed objects
        and do not carry a movement vector.
        """
        now   = datetime.now(timezone.utc)
        fmt   = '%Y-%m-%dT%H:%M:%S.%f'

        def ts(dt: datetime) -> str:
            return dt.strftime(fmt)[:-3] + 'Z'   # millisecond precision

        if self.mode == 1:
            return self._xml_mode1(now, ts)
        if self.mode == 2:
            return self._xml_mode2(now, ts)
        if self.mode == 3:
            return self._xml_mode3(now, ts)
        if self.mode == 4:
            return self._xml_mode4(now, ts)
        if self.mode == 5:
            return self._xml_mode5(now, ts)
        if self.mode == 6:
            return self._xml_mode6(now, ts)
        # ADDING A NEW MODE — to_xml:
        # Add an `if self.mode == N:` branch here.
        raise ValueError(f'No XML reconstruction for mode {self.mode}')

    def _xml_mode1(self, now, ts) -> str:
        uid_val = _derive_uid(self.callsign, mode=1, is_spot=self.is_spot)
        if self.is_spot:
            cot_type = _COT_TYPE_SPOT
            how      = 'h-g-i-g-o'
            stale    = now + timedelta(days=365)
        else:
            cot_type = _COT_TYPE_PLI
            how      = 'm-g'
            stale    = now + timedelta(minutes=5)

        root = ET.Element('event', {
            'version': '2.0',
            'uid':     uid_val,
            'type':    cot_type,
            'time':    ts(now),
            'start':   ts(now),
            'stale':   ts(stale),
            'how':     how,
            'access':  'Undefined',
        })
        ET.SubElement(root, 'point', {
            'lat': f'{self.lat:.6f}',
            'lon': f'{self.lon:.6f}',
            'hae': '9999999',
            'ce':  '9999999',
            'le':  '9999999',
        })
        detail = ET.SubElement(root, 'detail')
        ET.SubElement(detail, 'contact', {'callsign': self.name or self.callsign})
        if not self.is_spot:
            ET.SubElement(detail, 'uid', {'Droid': self.name or self.callsign})
            # track: speed=0.0 (no movement data); course=9999999.0 (heading unknown)
            # Both are the standard ATAK sentinel/placeholder values when GPS data
            # for movement is unavailable.
            ET.SubElement(detail, 'track', {
                'speed':  '0.0',
                'course': '9999999.0',
            })
        else:
            ET.SubElement(detail, 'creator', {'callsign': self.callsign})
            ET.SubElement(detail, 'archive')

        ET.indent(root, space='  ')
        return ET.tostring(root, encoding='unicode', xml_declaration=False)

    def _xml_mode2(self, now, ts) -> str:
        """Mode 2 — Alert.  Active alerts produce a b-a-o-tbl event; cancelled
        alerts produce a b-a-o-can with the SAME UID so TAK removes the
        marker from the map."""
        originator = self.orig_name or self.callsign
        uid_val    = _derive_uid(originator, mode=2)   # = HBC-{ORIGINATOR}-911
        if not self.alert_active:
            # Cancelled: short stale so the marker is removed quickly
            stale = now + timedelta(minutes=1)
            root = ET.Element('event', {
                'version': '2.0',
                'uid':     uid_val,
                'type':    _COT_TYPE_CANCEL,
                'time':    ts(now),
                'start':   ts(now),
                'stale':   ts(stale),
                'how':     'm-g',
                'access':  'Undefined',
            })
            ET.SubElement(root, 'point', {
                'lat': f'{self.lat:.6f}',
                'lon': f'{self.lon:.6f}',
                'hae': '9999999',
                'ce':  '9999999',
                'le':  '9999999',
            })
            detail = ET.SubElement(root, 'detail')
            em = ET.SubElement(detail, 'emergency', {'cancel': 'true'})
            em.text = originator      # matches ATAK's exact cancel format
            ET.indent(root, space='  ')
            return ET.tostring(root, encoding='unicode', xml_declaration=False)

        stale = now + timedelta(minutes=5)
        root = ET.Element('event', {
            'version': '2.0',
            'uid':     uid_val,
            'type':    _COT_TYPE_ALERT,
            'time':    ts(now),
            'start':   ts(now),
            'stale':   ts(stale),
            'how':     'm-g',
            'access':  'Undefined',
        })
        ET.SubElement(root, 'point', {
            'lat': f'{self.lat:.6f}',
            'lon': f'{self.lon:.6f}',
            'hae': '9999999',
            'ce':  '9999999',
            'le':  '9999999',
        })
        detail = ET.SubElement(root, 'detail')
        ET.SubElement(detail, 'emergency', {'type': '911 Alert'})
        ET.SubElement(detail, 'contact',
                      {'callsign': self.alert_name or f'{originator}-Alert'})
        ET.SubElement(detail, 'creator', {'callsign': originator})

        ET.indent(root, space='  ')
        return ET.tostring(root, encoding='unicode', xml_declaration=False)

    def _xml_mode3(self, now, ts) -> str:
        """Mode 3 — GeoChat.  Rebuilds a b-t-f event addressed to All Chat
        Rooms.  A fresh message UUID is generated on decode; the sender UID
        follows the HBC derivation rule so all receivers track the sender
        consistently.  Chat carries no position (point 0/0, unknown)."""
        msg_id     = str(uuid.uuid4())
        sender_uid = f'{HBC_UID_PREFIX}-{self.callsign.upper()}'
        uid_val    = f'GeoChat.{sender_uid}.All Chat Rooms.{msg_id}'
        stale      = now + timedelta(days=1)
        root = ET.Element('event', {
            'version': '2.0',
            'uid':     uid_val,
            'type':    _COT_TYPE_CHAT,
            'time':    ts(now),
            'start':   ts(now),
            'stale':   ts(stale),
            'how':     'h-g-i-g-o',
            'access':  'Undefined',
        })
        ET.SubElement(root, 'point', {
            'lat': '0', 'lon': '0',
            'hae': '9999999', 'ce': '9999999', 'le': '9999999',
        })
        detail = ET.SubElement(root, 'detail')
        chat = ET.SubElement(detail, '__chat', {
            'id':             'All Chat Rooms',
            'chatroom':       'All Chat Rooms',
            'senderCallsign': self.callsign,
            'groupOwner':     'false',
            'messageId':      msg_id,
        })
        ET.SubElement(chat, 'chatgrp', {
            'id':   'All Chat Rooms',
            'uid0': sender_uid,
            'uid1': 'All Chat Rooms',
        })
        ET.SubElement(detail, 'link', {
            'uid': sender_uid, 'type': 'a-f-G-U', 'relation': 'p-p',
        })
        remarks = ET.SubElement(detail, 'remarks', {
            'source': f'BAO.F.HBC.{sender_uid}',
            'to':     'All Chat Rooms',
            'time':   ts(now),
        })
        remarks.text = self.chat_text
        ET.indent(root, space='  ')
        return ET.tostring(root, encoding='unicode', xml_declaration=False)

    def _xml_mode4(self, now, ts) -> str:
        """Mode 4 — Shape.  Circle → u-d-c-c; closed 4-point polygon → u-d-r;
        anything else → u-d-f.  Colors/styles are not transmitted, so WinTAK
        defaults are applied.  UID is a fresh UUID4 (placed objects)."""
        uid_val = str(uuid.uuid4())
        stale   = now + timedelta(days=7)
        pts     = self.shape_points
        if self.shape_kind == 0:
            cot_type = _COT_TYPE_CIRCLE
            how      = 'h-g-i-g-o'
            c_lat, c_lon = self.lat, self.lon
        else:
            cot_type = _COT_TYPE_RECT if (self.shape_kind == 1 and len(pts) == 4) \
                       else _COT_TYPE_FREEFORM
            how      = 'h-e'
            c_lat = sum(p[0] for p in pts) / len(pts)
            c_lon = sum(p[1] for p in pts) / len(pts)
        root = ET.Element('event', {
            'version': '2.0',
            'uid':     uid_val,
            'type':    cot_type,
            'time':    ts(now),
            'start':   ts(now),
            'stale':   ts(stale),
            'how':     how,
            'access':  'Undefined',
        })
        ET.SubElement(root, 'point', {
            'lat': f'{c_lat:.6f}',
            'lon': f'{c_lon:.6f}',
            'hae': '9999999', 'ce': '9999999', 'le': '9999999',
        })
        detail = ET.SubElement(root, 'detail')
        ET.SubElement(detail, 'fillColor',   {'value': '-2130706433'})
        ET.SubElement(detail, 'strokeColor', {'value': '-1'})
        ET.SubElement(detail, 'strokeWeight', {'value': '4.0'})
        ET.SubElement(detail, 'strokeStyle', {'value': 'solid'})
        ET.SubElement(detail, 'archive')
        ET.SubElement(detail, 'creator', {
            'uid':      f'{HBC_UID_PREFIX}-{self.callsign.upper()}',
            'type':     'a-f-G-U',
            'callsign': self.callsign,
        })
        if self.shape_kind == 0:
            shape = ET.SubElement(detail, 'shape')
            ET.SubElement(shape, 'ellipse', {
                'major': str(self.radius_m),
                'minor': str(self.radius_m),
                'angle': '360',
            })
        else:
            out_pts = list(pts)
            if self.shape_kind == 1 and cot_type == _COT_TYPE_FREEFORM:
                out_pts.append(pts[0])   # repeat first point to close the ring
            for la, lo in out_pts:
                ET.SubElement(detail, 'link', {'point': f'{la:.6f},{lo:.6f}'})
        ET.SubElement(detail, 'contact', {'callsign': self.name or 'HBC Shape'})
        ET.indent(root, space='  ')
        return ET.tostring(root, encoding='unicode', xml_declaration=False)

    def _xml_mode5(self, now, ts) -> str:
        """Mode 5 — CASEVAC.  Rebuilds a b-r-f-h-c event with the 9-line
        numeric fields in a <_medevac_> element.  UID is a fresh UUID4."""
        uid_val = str(uuid.uuid4())
        stale   = now + timedelta(days=1)
        m = self.medevac
        root = ET.Element('event', {
            'version': '2.0',
            'uid':     uid_val,
            'type':    _COT_TYPE_CASEVAC,
            'time':    ts(now),
            'start':   ts(now),
            'stale':   ts(stale),
            'how':     'h-g-i-g-o',
            'access':  'Undefined',
        })
        ET.SubElement(root, 'point', {
            'lat': f'{self.lat:.6f}',
            'lon': f'{self.lon:.6f}',
            'hae': '9999999', 'ce': '9999999', 'le': '9999999',
        })
        detail = ET.SubElement(root, 'detail')
        ET.SubElement(detail, 'link', {
            'type':            'a-f-G-U',
            'uid':             f'{HBC_UID_PREFIX}-{self.callsign.upper()}',
            'parent_callsign': self.callsign,
            'relation':        'p-p',
        })
        ET.SubElement(detail, 'archive')
        title = self.name or f'{self.callsign}-CASEVAC'
        attrs = {
            'casevac': 'True' if m.get('casevac') else 'False',
            'title':   title,
            'freq':    f"{m.get('freq_mhz', 0.0):.1f}",
        }
        for key in ('urgent', 'urgent_surgical', 'priority', 'routine',
                    'convenience', 'litter', 'ambulatory'):
            if m.get(key, 0):
                attrs[key] = str(m[key])
        if m.get('equipment_none'):
            attrs['equipment_none'] = 'true'
        if m.get('terrain_none'):
            attrs['terrain_none'] = 'true'
            attrs['obstacles']    = 'None'
        attrs['security']            = str(m.get('security', 0))
        attrs['hlz_marking']         = str(m.get('hlz_marking', 0))
        attrs['zone_prot_selection'] = str(m.get('zone_prot', 0))
        ET.SubElement(detail, '_medevac_', attrs)
        ET.SubElement(detail, 'contact', {'callsign': title})
        ET.indent(root, space='  ')
        return ET.tostring(root, encoding='unicode', xml_declaration=False)

    def _xml_mode6(self, now, ts) -> str:
        """Mode 6 — Extended Marker.  Rebuilds the full CoT type plus the
        icon reference (2525C path, spot-map color, or custom iconset
        UUID/path) and optional tint.  UID is a fresh UUID4."""
        uid_val = str(uuid.uuid4())
        stale   = now + timedelta(days=365)
        root = ET.Element('event', {
            'version': '2.0',
            'uid':     uid_val,
            'type':    self.cot_type,
            'time':    ts(now),
            'start':   ts(now),
            'stale':   ts(stale),
            'how':     'h-g-i-g-o',
            'access':  'Undefined',
        })
        ET.SubElement(root, 'point', {
            'lat': f'{self.lat:.6f}',
            'lon': f'{self.lon:.6f}',
            'hae': '9999999', 'ce': '9999999', 'le': '9999999',
        })
        detail = ET.SubElement(root, 'detail')
        ET.SubElement(detail, 'contact',
                      {'callsign': self.name or self.callsign})
        ET.SubElement(detail, 'creator', {'callsign': self.callsign})
        ET.SubElement(detail, 'archive')
        if self.icon_kind == 1:
            t = self.cot_type.split('-')
            mid = '-'.join(t[:2]) if len(t) >= 2 else self.cot_type
            ET.SubElement(detail, 'usericon', {
                'iconsetpath': f'COT_MAPPING_2525C/{mid}/{self.cot_type}'})
        elif self.icon_kind == 2:
            ET.SubElement(detail, 'usericon', {
                'iconsetpath':
                    f'COT_MAPPING_SPOTMAP/b-m-p-s-m/{self.spot_argb}'})
            ET.SubElement(detail, 'color', {'argb': str(self.spot_argb)})
        elif self.icon_kind == 3:
            ET.SubElement(detail, 'usericon', {
                'iconsetpath': f'{self.iconset_uuid}/{self.icon_subpath}'})
        if self.has_tint:
            ET.SubElement(detail, 'color', {'argb': str(self.tint_argb)})
        ET.indent(root, space='  ')
        return ET.tostring(root, encoding='unicode', xml_declaration=False)

    def __str__(self) -> str:
        lines = [
            f'=== HBC Mode {self.mode} Decoded Message ===',
            f'  version  : {self.version}',
            f'  callsign : {self.callsign!r}',
        ]
        if self.mode == 1:
            lines += [
                f'  PLI/Spot : {"Spot" if self.is_spot else "PLI"}',
                f'  name     : {self.name!r}',
            ]
        elif self.mode == 2:
            lines += [
                f'  status     : {"ACTIVE" if self.alert_active else "CANCELLED"}',
                f'  alert_name : {self.alert_name!r}',
                f'  orig_name  : {self.orig_name!r}',
            ]
        elif self.mode == 3:
            lines += [
                f'  chat_text : {self.chat_text!r}',
            ]
        elif self.mode == 4:
            kind_name = {0: 'circle', 1: 'closed-polygon', 2: 'polyline'}.get(self.shape_kind, '?')
            lines += [
                f'  shape      : {kind_name}',
                f'  name       : {self.name!r}',
            ]
            if self.shape_kind == 0:
                lines += [f'  radius     : {self.radius_m} m']
            else:
                lines += [f'  points     : {len(self.shape_points)}']
        elif self.mode == 5:
            m = self.medevac
            lines += [
                f'  title      : {self.name!r}',
                f'  freq       : {m.get("freq_mhz", 0.0)} MHz',
                f'  patients   : urgent={m.get("urgent", 0)} urgent_surgical={m.get("urgent_surgical", 0)} '
                f'priority={m.get("priority", 0)} routine={m.get("routine", 0)} convenience={m.get("convenience", 0)}',
                f'  litter/amb : {m.get("litter", 0)}/{m.get("ambulatory", 0)}',
                f'  flags      : casevac={m.get("casevac", False)} equipment_none={m.get("equipment_none", False)} '
                f'terrain_none={m.get("terrain_none", False)}',
                f'  sec/hlz/zone: {m.get("security", 0)}/{m.get("hlz_marking", 0)}/{m.get("zone_prot", 0)}',
            ]
        lines += [
            f'  lat      : {self.lat:.6f}',
            f'  lon      : {self.lon:.6f}',
        ]
        return '\n'.join(lines)


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _bits_from_bytes(data: bytes) -> str:
    """Convert bytes to a bit string, MSB first per byte."""
    return ''.join(format(b, '08b') for b in data)


def _ita2_decode_callsign(reader: BitReader) -> str:
    """
    Read ITA2-encoded characters from the bit stream until the CR terminator
    (01000) is encountered.  Returns the decoded callsign string.
    """
    result     = ''
    in_figures = False
    while True:
        code = reader.read(5)
        if code == _ITA2_CR:
            break
        elif code == _ITA2_FIGS:
            in_figures = True
        elif code == _ITA2_LTRS:
            in_figures = False
        else:
            table = _ITA2_FIGURES_DECODE if in_figures else _ITA2_LETTERS_DECODE
            result += table.get(code, '?')
    return result


def _decode_name(reader: BitReader) -> str:
    """
    Read the 3-bit length field then the ASCII name characters.
    Returns the name string (empty string if length == 0).
    """
    length = reader.read_int(3)
    if length == 0:
        return ''
    return ''.join(chr(reader.read_int(8)) for _ in range(length))


def _ita2_decode_text(reader: BitReader) -> str:
    """Read ITA2 free text until the CR terminator (same wire format as the
    header callsign field — used by Mode 3 chat)."""
    return _ita2_decode_callsign(reader)


def _decode_coords(reader: BitReader):
    """
    Read 21-bit signed latitude and 22-bit signed longitude.
    Returns (lat_float, lon_float) scaled by ÷10,000.
    """
    lat = reader.read_signed(21) / 10000.0
    lon = reader.read_signed(22) / 10000.0
    return lat, lon


# =============================================================================
# MODE DECODERS
# Each decoder reads payload fields from the BitReader and returns an
# HBCDecodedMessage.  The header (callsign, version, mode) has already been
# read before the decoder is called.
# =============================================================================

def _decode_mode1(reader: BitReader, callsign: str, version: int) -> HBCDecodedMessage:
    """Mode 1 — Minimum PLI or Spot Message."""
    is_spot = bool(reader.read_int(1))   # PLI/Spot bit
    name    = _decode_name(reader)
    lat, lon = _decode_coords(reader)
    return HBCDecodedMessage(
        mode=1, version=version, callsign=callsign,
        lat=lat, lon=lon, is_spot=is_spot, name=name,
    )


def _decode_mode2(reader: BitReader, callsign: str, version: int) -> HBCDecodedMessage:
    """Mode 2 — Alert (active or cancelled).
    Payload: alert_status (1b) + alert_name + originator + lat (21b) + lon (22b).
    Status bit: 1 = active (show on map), 0 = cancelled (remove from map).
    """
    active     = bool(reader.read_int(1))
    alert_name = _decode_name(reader)
    orig_name  = _decode_name(reader)
    lat, lon   = _decode_coords(reader)
    return HBCDecodedMessage(
        mode=2, version=version, callsign=callsign,
        lat=lat, lon=lon, alert_active=active,
        alert_name=alert_name, orig_name=orig_name,
    )


def _decode_mode3(reader: BitReader, callsign: str, version: int) -> HBCDecodedMessage:
    """Mode 3 — GeoChat Text Message.
    Payload: message text (ITA2, CR-terminated).  No coordinates on the wire.
    """
    text = _ita2_decode_text(reader)
    return HBCDecodedMessage(
        mode=3, version=version, callsign=callsign,
        lat=0.0, lon=0.0, chat_text=text,
    )


def _decode_mode4(reader: BitReader, callsign: str, version: int) -> HBCDecodedMessage:
    """Mode 4 — Shape.
    Payload: kind (2b) + name + [circle: lat/lon + radius16 |
    polygon: count4 + first lat/lon + (count-1) x (dlat14 + dlon14)].
    """
    kind = reader.read_int(2)
    if kind == 3:
        raise ValueError('Shape kind 11 is reserved')
    name = _decode_name(reader)
    if kind == 0:
        lat, lon = _decode_coords(reader)
        radius = reader.read_int(16)
        return HBCDecodedMessage(
            mode=4, version=version, callsign=callsign,
            lat=lat, lon=lon, name=name,
            shape_kind=0, radius_m=radius, shape_points=[(lat, lon)],
        )
    count = reader.read_int(4)
    if count < 2:
        raise ValueError(f'Polygon point count {count} invalid (need 2-15)')
    lat, lon = _decode_coords(reader)
    pts = [(lat, lon)]
    ila, ilo = round(lat * 10000), round(lon * 10000)
    for _ in range(count - 1):
        ila += reader.read_signed(14)
        ilo += reader.read_signed(14)
        pts.append((ila / 10000.0, ilo / 10000.0))
    return HBCDecodedMessage(
        mode=4, version=version, callsign=callsign,
        lat=lat, lon=lon, name=name,
        shape_kind=kind, shape_points=pts,
    )


def _decode_mode5(reader: BitReader, callsign: str, version: int) -> HBCDecodedMessage:
    """Mode 5 — CASEVAC / MEDEVAC.
    Payload: title + freq16 + 5 x precedence counts (4b) + litter4 +
    ambulatory4 + flags4 + security2 + hlz3 + zone2 + lat21 + lon22.
    """
    title      = _decode_name(reader)
    freq_units = reader.read_int(16)
    counts = {k: reader.read_int(4) for k in
              ('urgent', 'urgent_surgical', 'priority', 'routine', 'convenience')}
    litter     = reader.read_int(4)
    ambulatory = reader.read_int(4)
    flags      = reader.read_int(4)
    security   = reader.read_int(2)
    hlz        = reader.read_int(3)
    zone       = reader.read_int(2)
    lat, lon   = _decode_coords(reader)
    medevac = dict(freq_mhz=freq_units / 100.0,
                   litter=litter, ambulatory=ambulatory,
                   casevac=bool(flags & 8),
                   equipment_none=bool(flags & 4),
                   terrain_none=bool(flags & 2),
                   security=security, hlz_marking=hlz, zone_prot=zone,
                   **counts)
    return HBCDecodedMessage(
        mode=5, version=version, callsign=callsign,
        lat=lat, lon=lon, name=title, medevac=medevac,
    )


def _decode_mode6(reader: BitReader, callsign: str, version: int) -> HBCDecodedMessage:
    """Mode 6 — Extended Marker (v1.3).
    Payload: name + lat21 + lon22 + type tokens (4b count + 6b each) +
    icon_kind (2b) [+ kind-specific fields] + tint (1b [+ argb32]).
    """
    from hbc_encoder import TOKEN_CHARSET, SPOT_COLORS
    name = _decode_name(reader)
    lat, lon = _decode_coords(reader)
    count = reader.read_int(4)
    cot_type = '-'.join(TOKEN_CHARSET[reader.read_int(6)] for _ in range(count))
    kind = reader.read_int(2)
    spot_argb = 0
    iconset_uuid = ''
    icon_subpath = ''
    if kind == 2:
        palette = reader.read_int(4)
        if palette == 15:
            spot_argb = reader.read_signed(32)
        else:
            c = SPOT_COLORS[min(palette, len(SPOT_COLORS) - 1)]
            spot_argb = c - 0x100000000 if c >= 0x80000000 else c
    elif kind == 3:
        import uuid as _uuid
        raw = bytes(reader.read_int(8) for _ in range(16))
        iconset_uuid = str(_uuid.UUID(bytes=raw))
        icon_subpath = _ita2_decode_text(reader)
    has_tint = reader.read_int(1) == 1
    tint_argb = reader.read_signed(32) if has_tint else 0
    return HBCDecodedMessage(
        mode=6, version=version, callsign=callsign,
        lat=lat, lon=lon, name=name, cot_type=cot_type,
        icon_kind=kind, spot_argb=spot_argb,
        iconset_uuid=iconset_uuid, icon_subpath=icon_subpath,
        has_tint=has_tint, tint_argb=tint_argb,
    )


# ADDING A NEW MODE — decoder:
# def _decode_modeN(reader: BitReader, callsign: str, version: int) -> HBCDecodedMessage:
#     # Read payload fields from `reader` in the order defined in the spec.
#     ...


# =============================================================================
# MODE DISPATCH TABLE
# Register new mode decoders here: mode_number -> decoder function
# =============================================================================
_DECODERS = {
    1: _decode_mode1,
    2: _decode_mode2,
    3: _decode_mode3,
    4: _decode_mode4,
    5: _decode_mode5,
    6: _decode_mode6,
}


# =============================================================================
# PUBLIC API
# =============================================================================

def decode(data) -> HBCDecodedMessage:
    """
    Decode a raw HBC binary payload into an HBCDecodedMessage.

    *** TRANSPORT BOUNDARY — pass in the bytes received from the audio/RF layer. ***

    Parameters
    ----------
    data : bytes | str
        - bytes : raw HBC payload from the transport layer (e.g. OFDM demodulator)
        - str   : bit string of '0'/'1' characters (useful for testing)

    Returns
    -------
    HBCDecodedMessage
        Call .to_xml() to get a CoT XML string for injection into TAK.
    """
    if isinstance(data, (bytes, bytearray)):
        bits = _bits_from_bytes(data)
    elif isinstance(data, str) and all(c in '01' for c in data):
        bits = data
    else:
        raise TypeError('decode() expects bytes or a binary string of 0s and 1s')

    reader = BitReader(bits)

    # ------------------------------------------------------------------
    # Header — common to all modes
    # ------------------------------------------------------------------
    callsign = _ita2_decode_callsign(reader)   # variable-length, CR-terminated
    version  = reader.read_int(3) + 1          # 3-bit field (000 = version 1)
    mode     = reader.read_int(3) + 1          # 3-bit field (000 = mode 1)

    # ------------------------------------------------------------------
    # Payload — dispatch to mode-specific decoder
    # ------------------------------------------------------------------
    decoder = _DECODERS.get(mode)
    if decoder is None:
        raise ValueError(f'No decoder registered for HBC mode {mode}')
    return decoder(reader, callsign, version)


# =============================================================================
# SELF-TEST  (python hbc_decoder.py)
# =============================================================================
if __name__ == '__main__':
    import sys
    sys.path.insert(0, '.')
    from hbc_encoder import encode

    TESTS = [
        ('Mode 1 — XML PLI (ONYX)',
         '''<event version="2.0" uid="ANDROID-636688233" type="a-f-G-U-C" how="m-g">
              <point lat="39.871776" lon="-98.324262" hae="245.901" ce="2.5" le="9999999" />
              <detail><contact callsign="ONYX" /><uid Droid="ONYX" /></detail>
            </event>''',
         dict(mode=1, is_spot=False, name='ONYX', lat=39.8718, lon=-98.3243)),

        ('Mode 1 — XML Spot (U.17.124805)',
         '''<event version="2.0" uid="f1907ab4" type="a-u-G" how="h-g-i-g-o">
              <point lat="39.871743" lon="-100.324462" hae="219.631" ce="9999999" le="9999999" />
              <detail>
                <creator callsign="ONYX" type="a-f-G-U-C" uid="x" />
                <contact callsign="U.17.124805" />
              </detail>
            </event>''',
         dict(mode=6, name='U.17.12', lat=39.8717, lon=-100.3245)),

        # Cancel test uses the actual cancel CoT from ATAK (Alerts.xml)
        ('Mode 2 — XML Alert Cancel (KEYSTON)',
         '''<event version="2.0" uid="ANDROID-6faa524f341bc5a0-9-1-1" type="b-a-o-can"
              time="2026-07-19T00:35:35.07Z" start="2026-07-19T00:35:35.07Z"
              stale="2026-07-19T00:35:45.07Z" how="m-g" access="Undefined">
           <point lat="38.871749" lon="-99.32417" hae="248.301" ce="2.0" le="9999999" />
           <detail><emergency cancel="true">KEYSTON</emergency></detail>
         </event>''',
         dict(mode=2, alert_active=False, alert_name='', orig_name='KEYSTON',
              lat=38.8717, lon=-99.3242)),

        ('Mode 2 — XML Alert (ONYX-Alert)',
         '''<event version="2.0" uid="14403346965-9-1-1" type="b-a-o-tbl" how="m-g">
              <point lat="39.871743" lon="-100.324462" hae="241.601" ce="4.5" le="9999999" />
              <detail><emergency type="911 Alert" /><contact callsign="ONYX-Alert" /></detail>
            </event>''',
         dict(mode=2, alert_active=True, alert_name='ONYX-Al', orig_name='ONYX',
              lat=39.8717, lon=-100.3245)),

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
         b'\x12\r\x12\x0bbobby-Alert',
         dict(mode=2, alert_active=True, alert_name='bobby-A', orig_name='bobby',
              lat=38.8718, lon=-99.3241)),

        # --- Modes 3-5: real WinTAK events from cot_capture.xml (8-18-26) ---
        ('Mode 3 — XML GeoChat (RECEIVER: test message)',
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
          </event>''',
         dict(mode=3, chat_text='TEST MESSAGE', lat=0.0, lon=0.0)),

        ('Mode 4 — XML Circle (Circle 1, 346 m)',
         '''<event version="2.0" uid="858caa5a-ddca-47b0-889c-5299bfd62698" type="u-d-c-c"
              time="2026-08-19T01:21:02.510Z" start="2026-08-19T01:21:02.510Z"
              stale="2026-08-26T01:21:02.510Z" how="h-g-i-g-o">
            <point lat="38.91531734" lon="-99.17975988" hae="9999999.0" ce="9999999.0" le="9999999.0" />
            <detail>
              <creator uid="S-1-5-21" type="a-f-G-U" callsign="RECEIVER" time="2026-08-19T01:20:58:669Z" />
              <shape>
                <ellipse minor="346.236470751501" angle="360" major="346.236470751501" />
              </shape>
              <contact callsign="Circle 1" />
            </detail>
          </event>''',
         dict(mode=4, shape_kind=0, name='Circle ', radius_m=346,
              lat=38.9153, lon=-99.1798)),

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
          </event>''',
         dict(mode=4, shape_kind=1, name='Rectang', num_points=4,
              lat=38.9193, lon=-99.1846)),

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
          </event>''',
         dict(mode=5, name='MED.19.', lat=38.9236, lon=-99.2958,
              medevac=dict(urgent=1, urgent_surgical=2, priority=4, routine=3,
                           convenience=5, litter=0, ambulatory=1,
                           casevac=False, equipment_none=True, terrain_none=True,
                           security=0, hlz_marking=3, zone_prot=0, freq_mhz=0.0))),
    ]

    all_passed = True
    for label, cot_input, expected in TESTS:
        print(f'--- {label} ---')
        try:
            # Encode
            enc = encode(cot_input)
            raw = enc.to_bytes()

            # Decode
            dec = decode(raw)
            print(dec)
            print()
            print('  Reconstructed CoT XML:')
            for line in dec.to_xml().splitlines():
                print(f'    {line}')
            print()

            # Verify key fields
            assert dec.mode    == expected['mode'],                      f'mode mismatch: {dec.mode}'
            assert dec.version == HBC_VERSION,                           f'version mismatch: {dec.version}'
            if 'is_spot' in expected:
                assert dec.is_spot == expected['is_spot'],               f'is_spot mismatch: {dec.is_spot}'
            if 'name' in expected:
                assert dec.name == expected['name'],                     f'name mismatch: {dec.name!r}'
            if 'alert_name' in expected:
                assert dec.alert_name == expected['alert_name'],         f'alert_name mismatch: {dec.alert_name!r}'
            if 'orig_name' in expected:
                assert dec.orig_name == expected['orig_name'],           f'orig_name mismatch: {dec.orig_name!r}'
            if 'alert_active' in expected:
                assert dec.alert_active == expected['alert_active'],     f'alert_active mismatch: {dec.alert_active}'
            if 'chat_text' in expected:
                assert dec.chat_text == expected['chat_text'],           f'chat_text mismatch: {dec.chat_text!r}'
            if 'shape_kind' in expected:
                assert dec.shape_kind == expected['shape_kind'],         f'shape_kind mismatch: {dec.shape_kind}'
            if 'radius_m' in expected:
                assert dec.radius_m == expected['radius_m'],             f'radius mismatch: {dec.radius_m}'
            if 'num_points' in expected:
                assert len(dec.shape_points) == expected['num_points'],  f'point count mismatch: {len(dec.shape_points)}'
            if 'medevac' in expected:
                for k, v in expected['medevac'].items():
                    assert dec.medevac.get(k) == v,                      f'medevac {k} mismatch: {dec.medevac.get(k)!r}'
            assert abs(dec.lat - expected['lat']) < 0.001,               f'lat mismatch: {dec.lat}'
            assert abs(dec.lon - expected['lon']) < 0.001,               f'lon mismatch: {dec.lon}'

            print(f'  PASS\n')
        except Exception as e:
            print(f'  FAIL: {e}\n')
            all_passed = False

    print('All tests passed.' if all_passed else 'SOME TESTS FAILED.')
