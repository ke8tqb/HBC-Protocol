"""Cross-validate Mode 6 (v1.3) against the Java implementation's output."""
from hbc_encoder import encode
from hbc_decoder import decode

TESTS = {
    '2525': ('<event version="2.0" uid="f1907ab4" type="a-u-G" how="h-g-i-g-o">'
             '<point lat="40.621743" lon="-85.204462" hae="219.631" ce="9999999" le="9999999"/>'
             '<detail><creator callsign="ONYX" type="a-f-G-U-C" uid="x"/>'
             '<usericon iconsetpath="COT_MAPPING_2525C/a-u/a-u-G"/>'
             '<color argb="-1"/>'
             '<contact callsign="U.17.124805"/></detail></event>'),
    'spotmap': ('<event version="2.0" uid="abc" type="b-m-p-s-m" how="h-g-i-g-o">'
                '<point lat="40.1" lon="-85.2" hae="0" ce="9999999" le="9999999"/>'
                '<detail><creator callsign="ONYX"/>'
                '<usericon iconsetpath="COT_MAPPING_SPOTMAP/b-m-p-s-m/-256"/>'
                '<color argb="-256"/>'
                '<contact callsign="SPOT1"/></detail></event>'),
    'custom': ('<event version="2.0" uid="def" type="a-f-A" how="h-g-i-g-o">'
               '<point lat="40.5" lon="-85.5" hae="0" ce="9999999" le="9999999"/>'
               '<detail><creator callsign="KE8TQB"/>'
               '<usericon iconsetpath="6d781afb-89a6-4c07-b2b9-a89748b6a38f/AIR/EMS.PNG"/>'
               '<contact callsign="MEDEVAC"/></detail></event>'),
}

JAVA = {
    '2525': 'C3 2B D4 0B D5 4B 8C 4D CB 8C 4C 8C 65 93 97 FD 99 C9 C2 0F FF FF FF FC',
    'spotmap': 'C3 2B D4 0B 54 D4 13 D5 0C 4C 3C D1 97 FF 02 CB 86 7B 61 08',
    'custom': ('78 76 6F C2 F9 40 BD 35 15 11 15 59 05 0C C5 C1 19 7A 14 1C 94 95 B6 BC'
               ' 0D 7D C4 D3 26 03 D9 5C D4 4B A4 5B 51 C7 8C CA DF 7E 1E 17 7C FD 99 A4 00'),
}

ok = True
for k, xml in TESTS.items():
    m = encode(xml)
    h = ' '.join(f'{b:02X}' for b in m.to_bytes())
    match = h == JAVA[k]
    print(k, 'mode', m.mode, 'bytes', m.byte_count,
          'JAVA-MATCH' if match else 'MISMATCH')
    if not match:
        print('  py  :', h)
        print('  java:', JAVA[k])
        ok = False
    d = decode(m.to_bytes())
    print('  decode:', d.cot_type, 'kind', d.icon_kind, d.callsign, repr(d.name))
    assert d.to_xml().startswith('<event')

print('ALL CROSS-CHECKS PASSED' if ok else 'CROSS-CHECK FAILURES')
raise SystemExit(0 if ok else 1)
