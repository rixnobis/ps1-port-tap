#!/bin/sh
# Render each copper and silk layer (plus a composite) of the board to PNG.
# usage: tools/render.sh [outdir]
set -e
cd "$(dirname "$0")/.."
out=${1:-renders}
mkdir -p "$out"
pcb=ps1-port-tap.kicad_pcb
plot() {  # name layers [extra args]
    name=$1; layers=$2; shift 2
    kicad-cli pcb export svg --mode-single --fit-page-to-board --exclude-drawing-sheet \
        --page-size-mode 2 --layers "$layers" "$@" -o "$out/$name.svg" "$pcb" >/dev/null
    rsvg-convert -b white -h 1800 "$out/$name.svg" -o "$out/$name.png"
    rm "$out/$name.svg"
}
plot F.Cu        F.Cu,Edge.Cuts
plot B.Cu        B.Cu,Edge.Cuts --mirror
plot F.SilkS     F.SilkS,F.Mask,Edge.Cuts
plot B.SilkS     B.SilkS,B.Mask,Edge.Cuts --mirror
plot composite   F.Cu,B.Cu,F.SilkS,Edge.Cuts
kicad-cli pcb render --side top --quality high -w 1800 -h 1640 -o "$out/3d-top.png" "$pcb" >/dev/null
kicad-cli pcb render --side bottom --quality high -w 1800 -h 1640 -o "$out/3d-bottom.png" "$pcb" >/dev/null
ls -l "$out"
