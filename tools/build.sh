#!/bin/sh
# Full pipeline: schematic -> placement -> Freerouting -> pours -> DRC -> renders -> fab.
# FREEROUTING points at the release jar (tested with 2.5.0).
set -e
cd "$(dirname "$0")/.."
FREEROUTING=${FREEROUTING:-$HOME/tools/freerouting/freerouting-2.5.0.jar}
python3 tools/gen_sch.py
kicad-cli sch erc --exit-code-violations -o build/erc.rpt ps1-port-tap.kicad_sch
python3 tools/build_pcb.py place
java -jar "$FREEROUTING" --gui.enabled=false -de build/ps1-port-tap.dsn \
    -do build/ps1-port-tap.ses -mp 50 -mt 8 2>&1 | grep -E 'final score|ERROR' || true
python3 tools/build_pcb.py finish
kicad-cli pcb drc --schematic-parity --severity-all --exit-code-violations \
    -o build/drc.rpt ps1-port-tap.kicad_pcb
kicad-cli sch export pdf -o schematic.pdf ps1-port-tap.kicad_sch >/dev/null
tools/render.sh renders >/dev/null
tools/fab.sh >/dev/null
echo BUILD-OK
