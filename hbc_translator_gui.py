#!/usr/bin/env python3
"""
hbc_translator_gui.py - HBC <-> CoT XML Translator GUI
=======================================================
Paste a CoT XML event OR an HBC binary payload into the top pane, press
Translate (or Ctrl+Enter), and the other representation appears in the
bottom pane.

Input auto-detection
--------------------
  starts with '<'            -> CoT XML        -> encoded to HBC
  only 0/1 characters        -> HBC bit string -> decoded to CoT XML
  hex digits (spaces, 0x,
  commas, dashes ignored)    -> HBC bytes      -> decoded to CoT XML

The hbc_encoder / hbc_decoder modules are located via (first match wins):
  1. HBC_PROTOCOL_PATH environment variable
  2. the directory containing this script
  3. C:\\Users\\david\\Desktop\\HBC-Protocol   (local clone)
  4. \\\\Primary\\David\\CoT Project\\HBC-Protocol

Usage
-----
  python  hbc_translator_gui.py             open the GUI
  pythonw hbc_translator_gui.py             open the GUI (no console window)
  python  hbc_translator_gui.py --selftest  translation logic check, no GUI
"""

import os
import re
import sys

# ---------------------------------------------------------------------------
# Locate and import the HBC protocol modules
# ---------------------------------------------------------------------------
_SEARCH_PATHS = [
    os.environ.get('HBC_PROTOCOL_PATH', ''),
    os.path.dirname(os.path.abspath(__file__)),
    r'C:\Users\david\Desktop\HBC-Protocol',
    r'\\Primary\David\CoT Project\HBC-Protocol',
]

encode = decode = None
_IMPORT_ERROR = None
try:
    for _p in _SEARCH_PATHS:
        if _p and os.path.isfile(os.path.join(_p, 'hbc_encoder.py')):
            if _p not in sys.path:
                sys.path.insert(0, _p)
            break
    from hbc_encoder import encode
    from hbc_decoder import decode
except ImportError as _e:
    _IMPORT_ERROR = (
        'Could not import hbc_encoder / hbc_decoder.\n\nSearched:\n  '
        + '\n  '.join(p for p in _SEARCH_PATHS if p)
        + '\n\nSet the HBC_PROTOCOL_PATH environment variable to the folder '
        + f'containing the HBC-Protocol repo.\n\n({_e})'
    )


# ---------------------------------------------------------------------------
# Translation core (GUI-independent, used by --selftest too)
# ---------------------------------------------------------------------------

def detect_input(text: str):
    """Classify pasted text. Returns (kind, payload) with kind in
    {'xml', 'hex', 'bits'}."""
    s = text.strip().lstrip('\ufeff')
    if not s:
        raise ValueError('Input is empty - paste a CoT XML event or HBC hex/bits.')
    if s.startswith('<'):
        return 'xml', s
    compact = re.sub(r'0[xX]', '', s)
    compact = re.sub(r'[\s,;:\-_]', '', compact)
    if not compact:
        raise ValueError('Input contains no data.')
    if re.fullmatch(r'[01]+', compact) and len(compact) >= 16:
        return 'bits', compact
    if re.fullmatch(r'[0-9A-Fa-f]+', compact):
        if len(compact) % 2:
            raise ValueError(
                f'Hex input has an odd number of digits ({len(compact)}) - '
                'one nibble is missing somewhere.')
        return 'hex', compact
    bad = sorted(set(re.findall(r'[^0-9A-Fa-f]', compact)))[:8]
    raise ValueError(
        'Input not recognized. Expected CoT XML (starts with "<"), an HBC hex '
        f'dump, or a 0/1 bit string. Offending characters: {" ".join(bad)}')


def translate(text: str):
    """Translate pasted text to the other representation.

    Returns (direction, status_line, output_text, primary_artifact) where
    primary_artifact is the copyable result: the HBC hex string for
    XML->HBC, or the reconstructed CoT XML for HBC->XML.
    """
    if _IMPORT_ERROR:
        raise RuntimeError(_IMPORT_ERROR)
    kind, payload = detect_input(text)

    if kind == 'xml':
        msg = encode(payload)
        raw = msg.to_bytes()
        hex_spaced = ' '.join(f'{b:02X}' for b in raw)
        xml_size = len(payload.encode('utf-8'))
        pct = 100 - 100 * len(raw) / max(1, xml_size)
        out = (
            f'=== HBC payload - {len(raw)} bytes ===\n{hex_spaced}\n\n'
            f'=== Bit stream - {msg.bit_count} bits ===\n{msg.bits}\n\n'
            f'=== Field breakdown ===\n{msg}'
        )
        status = (f'XML -> HBC   |   Mode {msg.mode} ({msg.cot_type})   |   '
                  f'{msg.bit_count} bits / {len(raw)} bytes   |   '
                  f'{xml_size} B XML -> {len(raw)} B HBC ({pct:.0f}% smaller)')
        return 'xml->hbc', status, out, hex_spaced

    data = payload if kind == 'bits' else bytes.fromhex(payload)
    dec = decode(data)
    xml_out = dec.to_xml()
    out = (f'=== Reconstructed CoT XML ===\n{xml_out}\n\n'
           f'=== Decoded fields ===\n{dec}')
    src = (f'{len(payload)} bits' if kind == 'bits'
           else f'{len(payload) // 2} bytes hex')
    status = (f'HBC -> XML   |   Mode {dec.mode}   |   '
              f'callsign {dec.callsign!r}   |   input: {src}')
    return 'hbc->xml', status, out, xml_out


# ---------------------------------------------------------------------------
# Built-in examples (real values from the 8-18-26 WinTAK capture / README)
# ---------------------------------------------------------------------------

EXAMPLE_XML = '''<event version="2.0" uid="ANDROID-KE8TQB-001" type="a-f-G-U-C"
       time="2026-07-12T19:00:41.00Z" start="2026-07-12T19:00:41.00Z"
       stale="2026-07-12T19:05:41.00Z" how="m-g" access="Undefined">
  <point lat="39.871776" lon="-98.324262" hae="9999999" ce="9999999" le="9999999" />
  <detail>
    <contact callsign="KE8TQB" />
    <uid Droid="KE8TQB" />
    <track speed="0.0" course="9999999.0" />
  </detail>
</event>'''

# Mode 3 GeoChat: RECEIVER -> "TEST MESSAGE" (15 bytes)
EXAMPLE_HEX = '50 5C 13 78 2A 40 50 09 60 4E 04 A5 1E 82 80'


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def run_gui() -> int:
    import tkinter as tk
    from tkinter import ttk, messagebox
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title('HBC \u21c4 CoT XML Translator')
    root.geometry('1020x780')

    if _IMPORT_ERROR:
        messagebox.showerror('HBC modules not found', _IMPORT_ERROR)
        root.destroy()
        return 1

    mono = ('Consolas', 10)
    state = {'primary': ''}

    # --- toolbar ---------------------------------------------------------
    bar = ttk.Frame(root, padding=(8, 6, 8, 2))
    bar.pack(fill='x')

    # --- panes -----------------------------------------------------------
    paned = ttk.Panedwindow(root, orient='vertical')
    paned.pack(fill='both', expand=True, padx=8, pady=(2, 2))

    in_frame = ttk.Labelframe(
        paned, text=' Input  -  CoT XML  or  HBC (hex / bit string) ', padding=4)
    out_frame = ttk.Labelframe(paned, text=' Output ', padding=4)
    paned.add(in_frame, weight=1)
    paned.add(out_frame, weight=1)

    in_text = ScrolledText(in_frame, wrap='word', font=mono, undo=True, height=12)
    in_text.pack(fill='both', expand=True)
    out_text = ScrolledText(out_frame, wrap='word', font=mono, height=12)
    out_text.pack(fill='both', expand=True)

    # --- status bar ------------------------------------------------------
    status_var = tk.StringVar(
        value='Paste CoT XML or HBC hex/bits into the top pane, then press '
              'Translate (Ctrl+Enter).')
    status = ttk.Label(root, textvariable=status_var, relief='sunken',
                       anchor='w', padding=(6, 3))
    status.pack(fill='x', side='bottom')

    # --- actions ---------------------------------------------------------
    def set_output(content: str):
        out_text.delete('1.0', 'end')
        out_text.insert('1.0', content)

    def do_translate(event=None):
        try:
            _, stat, out, primary = translate(in_text.get('1.0', 'end'))
        except Exception as e:
            state['primary'] = ''
            status_var.set(f'Error: {e}')
            set_output(f'*** {e} ***')
            return 'break'
        state['primary'] = primary
        set_output(out)
        status_var.set(stat)
        return 'break'

    def do_copy():
        if not state['primary']:
            status_var.set('Nothing to copy yet - translate something first.')
            return
        root.clipboard_clear()
        root.clipboard_append(state['primary'])
        kind = 'HBC hex' if not state['primary'].startswith('<') else 'CoT XML'
        status_var.set(f'{kind} result copied to clipboard '
                       f'({len(state["primary"])} characters).')

    def do_send_back():
        """Move the primary result into the input pane (easy round-tripping)."""
        if not state['primary']:
            status_var.set('Nothing to send back yet - translate something first.')
            return
        in_text.delete('1.0', 'end')
        in_text.insert('1.0', state['primary'])
        set_output('')
        status_var.set('Result moved to input - press Translate to go the '
                       'other direction.')

    def do_clear():
        in_text.delete('1.0', 'end')
        set_output('')
        state['primary'] = ''
        status_var.set('Cleared.')

    def load_example_xml():
        in_text.delete('1.0', 'end')
        in_text.insert('1.0', EXAMPLE_XML)
        status_var.set('Loaded example CoT XML (KE8TQB PLI) - press Translate.')

    def load_example_hex():
        in_text.delete('1.0', 'end')
        in_text.insert('1.0', EXAMPLE_HEX)
        status_var.set('Loaded example HBC hex (Mode 3 GeoChat) - press Translate.')

    ttk.Button(bar, text='Translate  (Ctrl+Enter)', command=do_translate)\
        .pack(side='left', padx=(0, 6))
    ttk.Button(bar, text='Copy Result', command=do_copy).pack(side='left', padx=6)
    ttk.Button(bar, text='Result \u2192 Input', command=do_send_back)\
        .pack(side='left', padx=6)
    ttk.Button(bar, text='Clear', command=do_clear).pack(side='left', padx=6)
    ttk.Button(bar, text='Example XML', command=load_example_xml)\
        .pack(side='right', padx=(6, 0))
    ttk.Button(bar, text='Example HBC', command=load_example_hex)\
        .pack(side='right', padx=6)

    root.bind('<Control-Return>', do_translate)

    root.mainloop()
    return 0


# ---------------------------------------------------------------------------
# Self-test (no GUI)
# ---------------------------------------------------------------------------

def run_selftest() -> int:
    if _IMPORT_ERROR:
        print(_IMPORT_ERROR)
        return 1
    ok = True

    def check(name, cond, extra=''):
        nonlocal ok
        print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name,
                               (' - ' + extra) if extra else ''))
        ok = ok and cond

    print('Translator self-test (no GUI):')

    # XML -> HBC (known Mode 1 vector from the README)
    d, _s, _o, hex_out = translate(EXAMPLE_XML)
    check('detect XML', d == 'xml->hbc')
    check('Mode 1 hex matches README vector',
          hex_out == '78 76 6F C2 F9 40 0C 96 8A 70 A8 A2 84 61 57 EC 3F CD 40',
          hex_out)

    # HBC hex -> XML (round-trip the bytes we just produced)
    d2, _s2, _o2, xml_out = translate(hex_out)
    check('detect hex', d2 == 'hbc->xml')
    check('round-trip uid', 'HBC-KE8TQB' in xml_out)
    check('round-trip callsign', 'callsign="KE8TQB"' in xml_out)

    # Messy hex formatting (0x prefixes, commas, newlines)
    messy = ',\n'.join('0x' + h for h in hex_out.split())
    d3, _s3, _o3, xml3 = translate(messy)
    check('messy hex accepted', d3 == 'hbc->xml' and 'HBC-KE8TQB' in xml3)

    # Bit-string input
    from hbc_encoder import encode as _enc
    bits = _enc(EXAMPLE_XML).bits
    d4, _s4, _o4, xml4 = translate(bits)
    check('bit-string input', d4 == 'hbc->xml' and 'HBC-KE8TQB' in xml4)

    # Captured Mode 3 chat hex -> XML
    d5, _s5, _o5, xml5 = translate(EXAMPLE_HEX)
    check('chat hex decodes', d5 == 'hbc->xml' and 'TEST MESSAGE' in xml5
          and 'RECEIVER' in xml5)

    # Error handling
    try:
        translate('this is not valid input !!!')
        check('junk input rejected', False)
    except ValueError:
        check('junk input rejected', True)

    print('Result:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(run_selftest())
    sys.exit(run_gui())
