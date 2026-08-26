# Mode 3 — GeoChat: Worked Examples


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
            groupOwner="false" messageId="e0295a69-0000-0000-0000-000000000000">
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
  Message Tag (v1.6)  CRC-16/CCITT-FALSE of __chat/@messageId
  ('e0295a69-0000-0000-0000-000000000000' → 0x4583):
  0100010110000011                                                 [16 bits]
  Message  'helo landing zone' folds to 'HELO LANDING ZONE'
  (H E L O SP L A N D I N G SP Z O N E), 17 chars + CR              [90 bits]

Total      : 184 bits → 23 bytes
Packed hex : 50 5C 13 78 2A 40 56 19 5E A1 16 0E 81 96 09 21 B1 26 66 89 1C 30 28
```

Decoded: a `b-t-f` event with `chatroom="ONYX"` and — matching ATAK's
native 1:1 wire format — the recipient's UID as the conversation id:
`id="HBC-ONYX"`, `chatgrp uid1="HBC-ONYX"`, `remarks to="HBC-ONYX"`,
text `HELO LANDING ZONE`, and
`uid="GeoChat.HBC-RECEIVER.HBC-ONYX.{fresh-UUID4}"`.

> **Receiver-side substitution:** ATAK's chat service files a 1:1 message
> into the chat window only when `chatgrp/uid1` equals the receiving
> device's *real* UID (e.g. `ANDROID-…`). When the DM recipient is the
> local station, the receiving implementation must replace `HBC-ONYX`
> with the local device UID before injection
> (`chat_recipient_uid_override` in the reference decoder; the companion
> ATAK plugin does this automatically and drops DMs addressed to other
> stations). The derived `HBC-{RECIPIENT}` UID is the offline fallback.

The 16-bit message tag is echoed back by the recipient in a **Mode 0 Ack**
so the sender's ATAK shows the delivered/read checkmark — see
[Mode0-Ack.md](Mode0-Ack.md) for the matching ack frames.

