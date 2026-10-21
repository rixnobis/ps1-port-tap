#!/usr/bin/env python3
"""Build ps1-port-tap.kicad_pcb from the schematic netlist.

  build_pcb.py place   - footprints, outline, silk, nets; writes the board + DSN
  build_pcb.py finish  - imports the Freerouting session, pours GND, stitches, saves

Coordinates are millimetres from the board's top-left corner.
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
NAME = "ps1-port-tap"
PCB = ROOT / f"{NAME}.kicad_pcb"
PRO = ROOT / f"{NAME}.kicad_pro"
SCH = ROOT / f"{NAME}.kicad_sch"
DSN = ROOT / "build" / f"{NAME}.dsn"
SES = ROOT / "build" / f"{NAME}.ses"
FPDIR = Path("/usr/share/kicad/footprints")

OX, OY = 100.0, 100.0          # sheet offset of the board origin
W, H = 40.0, 51.0              # board size
PITCH = 2.54
LINE_Y0 = 9.0                  # J1/J2 pin 1
J1_X, J2_X = 9.0, 31.0
J3_X0, J3_Y = W / 2 - 4 * PITCH, 43.5   # J3 leftmost column; even row is PITCH below
R_Y = 38.4                     # resistor centres

SHORT = {"/DAT": "DAT", "/CMD": "CMD", "/+7V5": "7V5", "/+3V5": "3V5", "/~{CS}": "CS",
         "/SCK": "SCK", "/~{IRQ}": "IRQ", "/~{ACK}": "ACK", "/GND": "GND", "/SHIELD": "SHLD"}
POWER_NETS = ["/GND", "/+7V5", "/+3V5", "/SHIELD"]


def col_x(i):
    """x of J3 column i; column 0 (DAT) is the rightmost."""
    return J3_X0 + PITCH * (8 - i)


def mm(v):
    return pcbnew.FromMM(v)


def pt(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))


def netlist():
    xml = ROOT / "build" / "netlist.xml"
    xml.parent.mkdir(exist_ok=True)
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadxml",
                    "-o", str(xml), str(SCH)], check=True, capture_output=True)
    r = ET.parse(xml).getroot()
    comps = {}
    for c in r.find("components"):
        comps[c.get("ref")] = {
            "value": c.findtext("value"),
            "footprint": c.findtext("footprint"),
            "uuid": c.findtext("tstamps"),
            "fields": {f.get("name"): f.text for f in (c.find("fields") if c.find("fields") is not None else [])},
        }
    pads = {}
    for n in r.find("nets"):
        for node in n:
            pads[(node.get("ref"), node.get("pin"))] = n.get("name")
    return comps, pads


def write_project():
    """Net classes live in the project file; the board reads them on load."""
    d = json.loads(PRO.read_text())
    ns = d["net_settings"]
    base = {"bus_width": 12, "clearance": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
            "tuning_profile": "", "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6}
    ns["classes"] = [dict(base, name="Default", priority=2147483647, track_width=0.3),
                     dict(base, name="Power", priority=0, track_width=0.6, via_diameter=0.8,
                          via_drill=0.4)]
    ns["netclass_patterns"] = [{"netclass": "Power", "pattern": n} for n in POWER_NETS]
    ns["netclass_assignments"] = {}
    rules = d["board"]["design_settings"].setdefault("rules", {})
    # JLCPCB 2-layer capabilities, with margin
    rules.update({"min_clearance": 0.2, "min_track_width": 0.2, "min_via_diameter": 0.6,
                  "min_through_hole_diameter": 0.3, "min_copper_edge_clearance": 0.4,
                  "min_hole_clearance": 0.25, "min_hole_to_hole": 0.5, "min_silk_clearance": 0.0,
                  "min_text_height": 0.8, "min_text_thickness": 0.15})
    PRO.write_text(json.dumps(d, indent=2) + "\n")


def load_fp(fpid):
    lib, name = fpid.split(":")
    fp = pcbnew.FootprintLoad(str(FPDIR / f"{lib}.pretty"), name)
    assert fp is not None, fpid
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def silk(board, s, x, y, size=1.0, angle=0, layer=pcbnew.F_SilkS, mirror=False, thick=0.15):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(pt(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(thick))
    t.SetTextAngleDegrees(angle)
    if mirror:
        t.SetMirrored(True)
    board.Add(t)


def place():
    write_project()
    comps, pads = netlist()
    board = pcbnew.NewBoard(str(PCB))
    board.SetCopperLayerCount(2)

    # nets
    nets = {}
    for name in sorted(set(pads.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni

    pos = {"J1": (J1_X, LINE_Y0, 0), "J2": (J2_X, LINE_Y0, 0)}
    # J3: rotate so the odd (signal) row runs left-to-right on top, GND row below
    # 270 puts pad 2 below pad 1 and runs the pad numbers right-to-left, so pad 1 sits
    # at the right end and column i (pads 2i+1/2i+2) is at col_x(i)
    pos["J3"] = (col_x(0), J3_Y, 270)
    for i in range(8):
        pos[f"R{i + 1}"] = (col_x(i), R_Y, 270)
    for i, (x, y) in enumerate([(3.5, 3.5), (W - 3.5, 3.5), (3.5, H - 3.5), (W - 3.5, H - 3.5)]):
        pos[f"H{i + 1}"] = (x, y, 0)
    mid = LINE_Y0 + 4.5 * PITCH
    for i, (x, y) in enumerate([(3.2, mid - 4.6), (3.2, mid + 4.6), (W - 3.2, mid - 4.6), (W - 3.2, mid + 4.6)]):
        pos[f"H{i + 5}"] = (x, y, 0)

    for ref, c in sorted(comps.items()):
        fp = load_fp(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["uuid"]))
        if c["fields"].get("LCSC"):
            fp.SetField("LCSC", c["fields"]["LCSC"])
            fp.GetField("LCSC").SetVisible(False)
        board.Add(fp)
        x, y, a = pos[ref]
        fp.SetPosition(pt(x, y))
        fp.SetOrientationDegrees(a)
        for pad in fp.Pads():
            net = pads.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(nets[net])
            # The port GND pads are the return path for the whole cable; tie them
            # solid to both pours instead of hoping the taps leave room for spokes.
            if ref in ("J1", "J2") and net == "/GND":
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)

    # rotation sanity: pad 1 must be where the layout assumes
    def padxy(ref, num):
        fp = board.FindFootprintByReference(ref)
        p = [q for q in fp.Pads() if q.GetNumber() == num][0].GetPosition()
        return round(pcbnew.ToMM(p.x) - OX, 3), round(pcbnew.ToMM(p.y) - OY, 3)
    j3_1, j3_2, j3_3 = padxy("J3", "1"), padxy("J3", "2"), padxy("J3", "3")
    assert j3_2[1] > j3_1[1] and abs(j3_2[0] - j3_1[0]) < 0.01, ("J3 even row not below odd", j3_1, j3_2)
    assert abs(j3_3[0] - col_x(1)) < 0.01, ("J3 column 1 not where col_x says", j3_1, j3_3)
    r1_1, r1_2 = padxy("R1", "1"), padxy("R1", "2")
    assert r1_1[1] < r1_2[1], ("R pad 1 not on top", r1_1, r1_2)
    print("J3 pads 1,2,3:", j3_1, j3_2, j3_3, " R1 pads:", r1_1, r1_2)

    # outline with 1 mm corner radius
    rad = 1.0
    segs = [((rad, 0), (W - rad, 0)), ((W, rad), (W, H - rad)),
            ((W - rad, H), (rad, H)), ((0, H - rad), (0, rad))]
    for a, b in segs:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(*a))
        s.SetEnd(pt(*b))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        board.Add(s)
    for cx, cy, sx, sy in [(rad, rad, 0, rad), (W - rad, rad, W - rad, 0),
                           (W - rad, H - rad, W, H - rad), (rad, H - rad, rad, H)]:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetCenter(pt(cx, cy))
        s.SetStart(pt(sx, sy))
        s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(90, pcbnew.DEGREES_T), True)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        board.Add(s)

    # front silk
    silk(board, "CONSOLE", J1_X, LINE_Y0 - 3.3, 1.0)
    silk(board, "DEVICE", J2_X, LINE_Y0 - 3.3, 1.0)
    for n in range(1, 11):
        y = LINE_Y0 + PITCH * (n - 1)
        silk(board, str(n), J1_X - 2.7, y, 0.8, thick=0.15)
        silk(board, str(n), J2_X + 2.7, y, 0.8, thick=0.15)
    order = ["/DAT", "/CMD", "/+7V5", "/+3V5", "/~{CS}", "/SCK", "/~{IRQ}", "/~{ACK}", "/GND"]
    for i, n in enumerate(order):
        silk(board, SHORT[n], col_x(i), J3_Y + PITCH + 3.0, 0.8, angle=90, thick=0.15)
    silk(board, "LA", J3_X0 - 3.0, J3_Y + PITCH / 2, 1.0)
    silk(board, "PS1 PORT TAP  rev A", W / 2, 2.4, 1.0)

    # back silk: the full pinout, so a cut cable can be wired from the board alone
    lines = ["PS1 PAD/MEMCARD PORT", "1 DAT  data from dev", "2 CMD  data to dev",
             "3 +7.5V  rumble", "4 GND", "5 +3.5V  logic", "6 /CS  port select", "7 SCK  clock",
             "8 /IRQ  lightgun", "9 /ACK  acknowledge", "10 SHIELD", "",
             "LA: odd=tap even=GND", "100R sig, 10k rails", "rixnobis/ps1-port-tap"]
    for i, s in enumerate(lines):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(s)
        t.SetLayer(pcbnew.B_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
        t.SetTextThickness(mm(0.15))
        t.SetMirrored(True)
        t.SetPosition(pt(W / 2, 8.5 + 1.55 * i))
        board.Add(t)

    # No tracks under a resistor body: a trace between 0603 pads is legal and makes
    # the part miserable to rework, and the autorouter will happily use the gap.
    for i in range(8):
        k = pcbnew.ZONE(board)
        k.SetIsRuleArea(True)
        k.SetDoNotAllowTracks(True)
        k.SetDoNotAllowVias(True)
        k.SetDoNotAllowZoneFills(False)
        k.SetDoNotAllowPads(False)
        k.SetDoNotAllowFootprints(False)
        k.SetLayer(pcbnew.F_Cu)
        ol = k.Outline()
        ol.NewOutline()
        x = col_x(i)
        for dx, dy in [(-0.7, -0.33), (0.7, -0.33), (0.7, 0.33), (-0.7, 0.33)]:  # pad gap only
            ol.Append(mm(OX + x + dx), mm(OY + R_Y + dy))
        board.Add(k)

    pcbnew.SaveBoard(str(PCB), board)
    DSN.parent.mkdir(exist_ok=True)
    board = pcbnew.LoadBoard(str(PCB))
    # GND is carried by pours on both layers; keep the autorouter off it
    ok = pcbnew.ExportSpecctraDSN(board, str(DSN))
    assert ok, "DSN export failed"
    print("placed; wrote", PCB, DSN)


def seg_dist(p, a, b):
    ax, ay, bx, by, px, py = a.x, a.y, b.x, b.y, p.x, p.y
    dx, dy = bx - ax, by - ay
    t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def via_clear(board, x, y, r, clearance):
    p = pt(x, y)
    need = mm(r + clearance)
    for t in board.GetTracks():
        half = t.GetWidth() / 2 if t.GetClass() == "PCB_TRACK" else t.GetWidth(pcbnew.F_Cu) / 2
        if seg_dist(p, t.GetStart(), t.GetEnd()) < need + half:
            return False
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            sz = pad.GetSize(pcbnew.F_Cu)
            if seg_dist(p, pad.GetPosition(), pad.GetPosition()) < need + max(sz.x, sz.y) / 2 + mm(0.1):
                return False
    return True


def finish():
    board = pcbnew.LoadBoard(str(PCB))
    assert SES.exists(), SES
    ok = pcbnew.ImportSpecctraSES(board, str(SES))
    assert ok, "SES import failed"
    gnd = board.FindNet("/GND")
    assert gnd is not None
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(gnd)
        z.SetLocalClearance(mm(0.3))
        z.SetMinThickness(mm(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.3))
        z.SetThermalReliefSpokeWidth(mm(0.5))
        z.SetIsFilled(False)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in [(0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (0.3, H - 0.3)]:
            ol.Append(mm(OX + x), mm(OY + y))
        board.Add(z)
    # Stitching: GND vias between the B.Cu through-lines turn the strips there into
    # guard ground tied to the F.Cu pour; the rest tie the two pours together.
    # A candidate is kept only if it clears every pad, hole and track.
    cands = [(x, LINE_Y0 + PITCH * (k + 0.5)) for k in range(9) for x in (13.5, 17.5, 21.5)]
    cands += [(x, 35.0) for x in (5.0, W - 5.0)] + [(x, 41.5) for x in (5.0, W - 5.0)]
    cands += [(x, 5.5) for x in (9.0, 15.0, 25.0, 31.0)]
    kept = 0
    for x, y in cands:
        if via_clear(board, x, y, 0.3, 0.25):
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pt(x, y))
            v.SetWidth(mm(0.6))
            v.SetDrill(mm(0.3))
            v.SetNet(gnd)
            board.Add(v)
            kept += 1
    print(f"stitching vias: {kept} of {len(cands)} candidates kept")
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    print("finished;", len(board.GetTracks()), "track/via items")


if __name__ == "__main__":
    {"place": place, "finish": finish}[sys.argv[1]]()
