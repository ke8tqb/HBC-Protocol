# Mode 0 — Ack: Worked Examples

Mode 0 (v1.6) confirms delivery and reading of a **Direct Message** so the
sender's ATAK chat window shows the same checkmarks it would on an IP
network. It rides the previously reserved wire mode bits `111`.

This example continues the Direct Message example from
[Mode3-GeoChat.md](Mode3-GeoChat.md): RECEIVER sent ONYX "helo landing
zone" with message tag `0x4583` (CRC-16/CCITT-FALSE of the sender's ATAK
`messageId` `e0295a69-0000-0000-0000-000000000000`).

## How the acks are produced

On the recipient EUD (ONYX), ATAK automatically emits a `b-t-f-d`
(delivered) receipt when the message is stored and a `b-t-f-r` (read)
receipt when the conversation is opened. The HBC implementation intercepts
those receipt events — ATAK addresses them by receipt UID == the
acknowledged message's `messageId` — and transmits each as a compact
Mode 0 frame instead.

On the original sender (RECEIVER), the ack's 16-bit tag is looked up in
the map of recently sent DMs (tag → original `messageId`), and a
`b-t-f-d`/`b-t-f-r` receipt CoT is injected with `uid` == that
`messageId`. ATAK matches receipts to chat messages purely by that UID,
which flips the checkmark.

## Delivered ack — ONYX → RECEIVER, tag 0x4583

```
Header
  Callsign 'ONYX' : O=11000 N=01100 Y=10101 X=11101 + CR 01000      [25 bits]
  Version → 000
  Mode 0  → 111   (previously reserved bit pattern)

Payload
  Recipient  ITA2, CR-terminated — the original DM sender:
  'RECEIVER' = R=01010 E=00001 C=01110 E=00001 I=00110 V=11110
               E=00001 R=01010 + CR=01000                           [45 bits]
  Ack Kind   [2 bits]  00 = delivered (b-t-f-d)
  Msg Tag    [16 bits] 0x4583 → 0100010110000011

Total      : 94 bits → 12 bytes
Packed hex : C3 2B D4 0E A0 B8 26 F0 54 81 16 0C
```

## Read ack — same frame, Ack Kind = 01

```
Ack Kind   [2 bits]  01 = read (b-t-f-r)

Total      : 94 bits → 12 bytes
Packed hex : C3 2B D4 0E A0 B8 26 F0 54 85 16 0C
```

## Reconstructed CoT (sender side, after tag → messageId lookup)

```xml
<event version="2.0" uid="e0295a69-0000-0000-0000-000000000000" type="b-t-f-d"
       time="2026-08-26T03:40:00.000Z" start="2026-08-26T03:40:00.000Z"
       stale="2026-08-26T03:45:00.000Z" how="h-g-i-g-o" access="Undefined">
  <point lat="0" lon="0" hae="9999999" ce="9999999" le="9999999" />
  <detail>
    <__chatreceipt ackedUid="e0295a69-0000-0000-0000-000000000000"
                   senderCallsign="ONYX" />
  </detail>
</event>
```

The read receipt is identical except `type="b-t-f-r"`.

## Notes

- Acks are addressed by callsign: stations whose callsign does not match
  the recipient field ignore the frame entirely.
- If the tag is not found in the sender's map (e.g. the plugin restarted
  since the DM was sent), the ack is logged and dropped — the decoder's
  offline fallback UID is `HBC-ACK-{TAG}` (e.g. `HBC-ACK-4583`), which is
  intentionally meaningless to ATAK.
- Ack kinds `10` and `11` are reserved.
