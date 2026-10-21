#!/bin/sh
# Full pipeline: schematic -> placement and route -> pours -> DRC -> geometry check
# -> renders, zoomed crops -> fab. Stops on any ERC, DRC or geometry finding.
set -e
cd "$(dirname "$0")/.."
mkdir -p build
python3 tools/gen_sch.py
kicad-cli sch erc --exit-code-violations -o build/erc.rpt ps1-port-tap.kicad_sch
python3 tools/build_pcb.py place
python3 tools/build_pcb.py finish
kicad-cli pcb drc --schematic-parity --severity-all --exit-code-violations \
    -o build/drc.rpt ps1-port-tap.kicad_pcb
python3 tools/check_geometry.py ps1-port-tap.kicad_pcb
kicad-cli sch export pdf -o schematic.pdf ps1-port-tap.kicad_sch >/dev/null
tools/render.sh renders >/dev/null
tools/crops.sh ps1-port-tap.kicad_pcb renders/crops >/dev/null
tools/fab.sh >/dev/null
echo BUILD-OK
