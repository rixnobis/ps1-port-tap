#!/usr/bin/env python3
"""Generate ps1-port-tap.kicad_sch.

Symbols come from the stock KiCad library and are embedded in the file.
Every pin gets a short wire stub and a net label, so connectivity is carried
by label names rather than by drawn wires.
"""
import math
import re
import sys
import uuid as uuidlib
from pathlib import Path

SYMDIR = Path("/usr/share/kicad/symbols")
OUT = Path(__file__).resolve().parent.parent / "ps1-port-tap.kicad_sch"
ROOT_UUID = "6b1f3c2e-9a4d-4e57-8a0b-5f1d2c3e4a01"

# Port pinout: psx-spx, docs/ps1/pinouts/controller-ports-and-memory-card-ports.md
PORT = {
    1: "DAT",       # data from device (SIO0 RX)
    2: "CMD",       # data to device (SIO0 TX)
    3: "+7V5",      # rumble motor supply
    4: "GND",
    5: "+3V5",      # logic supply
    6: "~{CS}",     # port select
    7: "SCK",       # serial clock
    8: "~{IRQ}",    # lightgun IRQ, controller port only
    9: "~{ACK}",    # data acknowledge
    10: "SHIELD",   # cable shield, passed through, not tapped
}

# Tapped lines: (port pin, series resistor value)
TAPS = [
    (1, "100"), (2, "100"), (3, "10k"), (5, "10k"),
    (6, "100"), (7, "100"), (8, "100"), (9, "100"),
]


def uid():
    return str(uuidlib.uuid4())


def extract_symbol(lib, name):
    text = (SYMDIR / f"{lib}.kicad_sym").read_text()
    m = re.search(r'\n\t\(symbol "%s"\n' % re.escape(name), text)
    if not m:
        sys.exit(f"symbol {lib}:{name} not found")
    start = m.start() + 2  # skip "\n\t"
    depth = 0
    i = start
    in_str = False
    while True:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = text[start:i + 1]
    assert body.startswith(f'(symbol "{name}"'), body[:60]
    body = body.replace(f'(symbol "{name}"', f'(symbol "{lib}:{name}"', 1)
    pins = {}
    for pm in re.finditer(
        r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)\s*\(length [-\d.]+\)'
        r'(?:\s*\(hide yes\))?\s*\(name "[^"]*"(?:.|\n)*?\(number "([^"]+)"', body):
        x, y, a, num = float(pm[1]), float(pm[2]), float(pm[3]), pm[4]
        pins[num] = (x, y, a)
    return body, pins


LIBS = {
    "Conn_01x10": extract_symbol("Connector_Generic", "Conn_01x10"),
    "Conn_02x09_Odd_Even": extract_symbol("Connector_Generic", "Conn_02x09_Odd_Even"),
    "R": extract_symbol("Device", "R"),
    "MountingHole": extract_symbol("Mechanical", "MountingHole"),
}
LIBID = {
    "Conn_01x10": "Connector_Generic:Conn_01x10",
    "Conn_02x09_Odd_Even": "Connector_Generic:Conn_02x09_Odd_Even",
    "R": "Device:R",
    "MountingHole": "Mechanical:MountingHole",
}

items = []


def fmt(v):
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def place(kind, ref, value, footprint, x, y, nets, fields_extra=()):
    """nets: {pin_number: label}; a stub + label is drawn on each pin."""
    _, pins = LIBS[kind]
    su = uid()
    pin_uuids = "".join(f'\n\t\t(pin "{n}"\n\t\t\t(uuid "{uid()}")\n\t\t)' for n in pins)
    extra = "".join(
        f'\n\t\t(property "{k}" "{v}"\n\t\t\t(at {fmt(x)} {fmt(y)} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)'
        for k, v in fields_extra)
    in_bom = "no" if kind == "MountingHole" else "yes"
    items.append(f'''	(symbol
		(lib_id "{LIBID[kind]}")
		(at {fmt(x)} {fmt(y)} 0)
		(unit 1)
		(exclude_from_sim no)
		(in_bom {in_bom})
		(on_board yes)
		(dnp no)
		(uuid "{su}")
		(property "Reference" "{ref}"
			(at {fmt(x + (0 if kind.startswith('Conn') else 2.54))} {fmt(y - (14 if kind.startswith('Conn') else 0.8))} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Value" "{value}"
			(at {fmt(x + (0 if kind.startswith('Conn') else 2.54))} {fmt(y + (16 if kind.startswith('Conn') else 1.2))} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Footprint" "{footprint}"
			(at {fmt(x)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Datasheet" ""
			(at {fmt(x)} {fmt(y)} 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		){extra}{pin_uuids}
		(instances
			(project "ps1-port-tap"
				(path "/{ROOT_UUID}"
					(reference "{ref}")
					(unit 1)
				)
			)
		)
	)''')
    for num, net in nets.items():
        px, py, a = pins[num]
        sx, sy = x + px, y - py                      # library y is up, sheet y is down
        dx, dy = -math.cos(math.radians(a)), math.sin(math.radians(a))
        ex, ey = sx + 2.54 * dx, sy + 2.54 * dy
        items.append(f'''	(wire
		(pts
			(xy {fmt(sx)} {fmt(sy)}) (xy {fmt(ex)} {fmt(ey)})
		)
		(stroke
			(width 0)
			(type default)
		)
		(uuid "{uid()}")
	)''')
        if abs(dx) > 0.5:
            ang, just = (180, "right") if dx < 0 else (0, "left")
        else:
            ang, just = (90, "left") if dy < 0 else (270, "right")
        items.append(f'''	(label "{net}"
		(at {fmt(ex)} {fmt(ey)} {ang})
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify {just} bottom)
		)
		(uuid "{uid()}")
	)''')


def text(s, x, y, size=1.27):
    s = s.replace('"', '\\"').replace("\n", "\\n")  # no raw newlines inside a string
    items.append(f'''	(text "{s}"
		(exclude_from_sim no)
		(at {fmt(x)} {fmt(y)} 0)
		(effects
			(font
				(size {size} {size})
			)
			(justify left bottom)
		)
		(uuid "{uid()}")
	)''')


HDR1 = "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical"
HDR2 = "Connector_PinHeader_2.54mm:PinHeader_2x09_P2.54mm_Vertical"
R0603 = "Resistor_SMD:R_0603_1608Metric"

place("Conn_01x10", "J1", "CONSOLE", HDR1, 40.64, 60.96, dict((str(k), v) for k, v in PORT.items()))
place("Conn_01x10", "J2", "DEVICE", HDR1, 76.2, 60.96, dict((str(k), v) for k, v in PORT.items()))

for i, (pin, val) in enumerate(TAPS):
    net = PORT[pin]
    tap = "TAP_" + re.sub(r"[~{}+]", "", net)
    place("R", f"R{i + 1}", val, R0603, 116.84 + 10.16 * (i % 4), 50.8 + 25.4 * (i // 4),
          {"1": net, "2": tap}, (("LCSC", "C22775" if val == "100" else "C25804"),))

hdr_nets = {}
for i, (pin, _) in enumerate(TAPS):
    hdr_nets[str(2 * i + 1)] = "TAP_" + re.sub(r"[~{}+]", "", PORT[pin])
    hdr_nets[str(2 * i + 2)] = "GND"
hdr_nets["17"] = "GND"
hdr_nets["18"] = "GND"
place("Conn_02x09_Odd_Even", "J3", "LA_TAP", HDR2, 175.26, 60.96, hdr_nets)

for i in range(4):
    place("MountingHole", f"H{i + 1}", "M3", "MountingHole:MountingHole_3.2mm_M3",
          45.72 + 12.7 * i, 106.68, {})
for i in range(4):
    place("MountingHole", f"H{i + 5}", "ZIPTIE", "MountingHole:MountingHole_2.2mm_M2",
          45.72 + 12.7 * i, 121.92, {})

text("PS1 controller / memory card port pass-through + logic analyser tap", 25.4, 22.86, 2.54)
text("Pinout: psx-spx, docs/ps1/pinouts/controller-ports-and-memory-card-ports.md (master).\n"
     "J1 = console side, J2 = device side, wired 1:1. Pin 10 carries the cable shield straight through.\n"
     "Memory card slots have no IRQ (pin 8) and no shield; leave those wires unconnected.", 25.4, 30.48)
text("Taps: signal lines through 100R (keeps analyser lead capacitance off the bus).\n"
     "Supply rails through 10k, so a probe on a rail cannot short it.\n"
     "Fit 0R in place of 100R for a transparent tap.", 109.22, 38.1)
text("J3 odd pins = tapped line, even pins = GND.\nPairs: DAT, CMD, 7V5, 3V5, CS, SCK, IRQ, ACK, GND/GND", 162.56, 91.44)

lib_symbols = "\n".join("\t\t" + LIBS[k][0].replace("\n", "\n\t") for k in LIBS)

OUT.write_text(f'''(kicad_sch
	(version 20260306)
	(generator "eeschema")
	(generator_version "10.0")
	(uuid "{ROOT_UUID}")
	(paper "A4")
	(title_block
		(title "ps1-port-tap")
		(rev "A")
		(company "rixnobis")
	)
	(lib_symbols
{lib_symbols}
	)
{chr(10).join(items)}
	(sheet_instances
		(path "/"
			(page "1")
		)
	)
	(embedded_fonts no)
)
''')
print("wrote", OUT)
