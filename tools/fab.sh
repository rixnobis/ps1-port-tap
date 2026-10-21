#!/bin/sh
# Gerbers, drill, BOM and CPL for JLCPCB, into fab/.
set -e
cd "$(dirname "$0")/.."
pcb=ps1-port-tap.kicad_pcb; sch=ps1-port-tap.kicad_sch
rm -rf fab; mkdir -p fab/gerbers
kicad-cli pcb export gerbers --layers F.Cu,B.Cu,F.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
    --subtract-soldermask --no-protel-ext -o fab/gerbers/ "$pcb" >/dev/null
kicad-cli pcb export drill --format excellon --drill-origin absolute --excellon-units mm -o fab/gerbers/ "$pcb" >/dev/null
(cd fab/gerbers && zip -q ../ps1-port-tap-gerbers.zip *)
# BOM: JLC columns, SMD parts only (headers are hand-fitted)
kicad-cli sch export bom --fields 'Value,Reference,Footprint,LCSC' \
    --labels 'Comment,Designator,Footprint,LCSC Part #' --group-by 'Value,Footprint,LCSC' \
    --ref-range-delimiter '' --exclude-dnp -o fab/bom-all.csv "$sch" >/dev/null
{ head -1 fab/bom-all.csv; grep '"C[0-9]' fab/bom-all.csv; } > fab/ps1-port-tap-bom.csv
rm fab/bom-all.csv
# CPL: JLC columns
kicad-cli pcb export pos --format csv --units mm --side front --smd-only -o fab/pos.csv "$pcb" >/dev/null
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open("fab/pos.csv")))
with open("fab/ps1-port-tap-cpl.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in rows:
        w.writerow([r["Ref"], r["PosX"] + "mm", r["PosY"] + "mm", "Top", r["Rot"]])
print(len(rows), "placements")
PY
rm fab/pos.csv
ls -l fab fab/gerbers
