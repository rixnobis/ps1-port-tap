#!/usr/bin/env python3
"""Build ps1-port-tap.kicad_pcb from the schematic netlist.

  build_pcb.py place   - footprints, outline, silk, nets and the hand route
  build_pcb.py finish  - pours GND on both layers, stitches, saves

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
FPDIR = Path("/usr/share/kicad/footprints")

OX, OY = 100.0, 100.0          # sheet offset of the board origin
W, H = 40.0, 51.0              # board size
PITCH = 2.54
LINE_Y0 = 9.0                  # J1/J2 pin 1
J1_X, J2_X = 9.0, 31.0
# J3 sits 0.6 mm left of centre so the DAT tap via (rightmost column, on line 1)
# clears J2 pad 1; even row is PITCH below
J3_X0, J3_Y = W / 2 - 4 * PITCH - 0.6, 43.5
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

    # No pour inside a pad row: between two pads the fill can only form pointed
    # cusps, so it stops at a straight edge along the row instead. GND pads inside
    # a strip reach the pour through explicit traces (see route()).
    CL = 0.85 + 0.3
    strips = [(J1_X - CL, LINE_Y0 - CL, J1_X + CL, LINE_Y0 + 9 * PITCH + CL),
              (J2_X - CL, LINE_Y0 - CL, J2_X + CL, LINE_Y0 + 9 * PITCH + CL),
              (col_x(8) - CL, J3_Y - CL, col_x(0) + CL, J3_Y + PITCH + CL),
              (col_x(7) - 0.8, R_Y - 1.55, col_x(0) + 0.8, R_Y + 1.55, "F")]  # SMD: top only
    for x0, y0, x1, y1, *side in strips:
        k = pcbnew.ZONE(board)
        k.SetIsRuleArea(True)
        k.SetDoNotAllowZoneFills(True)
        k.SetDoNotAllowTracks(False)
        k.SetDoNotAllowVias(False)
        k.SetDoNotAllowPads(False)
        k.SetDoNotAllowFootprints(False)
        lset = pcbnew.LSET()
        lset.AddLayer(pcbnew.F_Cu)
        if not side:
            lset.AddLayer(pcbnew.B_Cu)
        k.SetLayerSet(lset)
        ol = k.Outline()
        ol.NewOutline()
        for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            ol.Append(mm(OX + x), mm(OY + y))
        board.Add(k)

    route(board, nets, pads)
    pcbnew.SaveBoard(str(PCB), board)
    print("placed and routed;", PCB)


# Port pins tapped, in J3 column order (column 0 = DAT, the rightmost)
TAP_PINS = [1, 2, 3, 5, 6, 7, 8, 9]
POWER_W, SIGNAL_W = 0.6, 0.3


def track(board, net, layer, a, b, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pt(*a))
    t.SetEnd(pt(*b))
    t.SetLayer(layer)
    t.SetWidth(mm(w))
    t.SetNet(net)
    board.Add(t)


def route(board, nets, pads):
    """Every run is straight. Port line n crosses B.Cu from J1 pin n to J2 pin n;
    a tapped line drops through a via at its J3 column and runs straight down F.Cu
    to its resistor, and the resistor runs straight down to its J3 pin."""
    tapped = {pin: i for i, pin in enumerate(TAP_PINS)}
    for n in range(1, 11):
        net_name = pads[("J1", str(n))]
        net = nets[net_name]
        y = LINE_Y0 + PITCH * (n - 1)
        w = POWER_W if net_name in POWER_NETS else SIGNAL_W
        if n not in tapped:
            track(board, net, pcbnew.B_Cu, (J1_X, y), (J2_X, y), w)
            continue
        x = col_x(tapped[n])
        track(board, net, pcbnew.B_Cu, (J1_X, y), (x, y), w)
        track(board, net, pcbnew.B_Cu, (x, y), (J2_X, y), w)
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pt(x, y))
        big = net_name in POWER_NETS
        v.SetWidth(mm(0.8 if big else 0.6))
        v.SetDrill(mm(0.4 if big else 0.3))
        v.SetNet(net)
        board.Add(v)
        r = f"R{tapped[n] + 1}"
        fp = board.FindFootprintByReference(r)
        p1 = [q for q in fp.Pads() if q.GetNumber() == "1"][0].GetPosition()
        p2 = [q for q in fp.Pads() if q.GetNumber() == "2"][0].GetPosition()
        r_y1, r_y2 = pcbnew.ToMM(p1.y) - OY, pcbnew.ToMM(p2.y) - OY
        assert abs(pcbnew.ToMM(p1.x) - OX - x) < 0.001, (r, "not under its via")
        track(board, net, pcbnew.F_Cu, (x, y), (x, r_y1), w)
        tap = nets[pads[(r, "2")]]
        track(board, tap, pcbnew.F_Cu, (x, r_y2), (x, J3_Y), SIGNAL_W)

    # GND out of the no-pour strips: the J3 even row is bussed on both layers and
    # the bus runs past both ends of the row into the pour; the port GND pads get a
    # straight F.Cu stub into the pour (B.Cu already has the through-line).
    gnd = nets["/GND"]
    gy = J3_Y + PITCH
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        track(board, gnd, layer, (col_x(8) - 2.2, gy), (col_x(0) + 2.2, gy), POWER_W)
        track(board, gnd, layer, (col_x(8), J3_Y), (col_x(8), gy), POWER_W)  # pad 17
    y4 = LINE_Y0 + 3 * PITCH
    track(board, gnd, pcbnew.F_Cu, (J1_X, y4), (J1_X - 2.5, y4), POWER_W)   # outward,
    track(board, gnd, pcbnew.F_Cu, (J2_X, y4), (J2_X + 2.5, y4), POWER_W)   # clear of taps


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
    gnd = board.FindNet("/GND")
    assert gnd is not None
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(gnd)
        z.SetLocalClearance(mm(0.3))
        # 0.4 mm minimum width: no pour sliver can squeeze between two header pads
        # (0.84 mm gap less 2 x 0.3 mm clearance), and isolated islands are dropped
        z.SetMinThickness(mm(0.4))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
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
    mids = [J3_X0 + PITCH * (k + 0.5) for k in range(1, 8)]  # between tap columns
    cands = [(x, LINE_Y0 + PITCH * (k + 0.5)) for k in range(9) for x in mids]
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
