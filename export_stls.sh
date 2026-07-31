#!/usr/bin/env bash
# Usage: ./export_stls.sh [svg] [thickness] [height] [cutout_depth] [flip]
# Exports outer.stl and inner.stl

if [ -z "$1" ]; then
    read -rp "SVG file: " SVG
else
    SVG="$1"
fi

if [ -z "$2" ]; then
    read -rp "Outline thickness mm [5.0]: " THICKNESS
    THICKNESS="${THICKNESS:-5.0}"
else
    THICKNESS="$2"
fi

if [ -z "$3" ]; then
    read -rp "Height mm [10.0]: " HEIGHT
    HEIGHT="${HEIGHT:-10.0}"
else
    HEIGHT="$3"
fi

if [ -z "$4" ]; then
    read -rp "Cutout depth mm [3.0]: " CUTOUT
    CUTOUT="${CUTOUT:-3.0}"
else
    CUTOUT="$4"
fi

if [ -z "$5" ]; then
    read -rp "Flip face down? [y/N]: " FLIP
    FLIP="${FLIP:-no}"
else
    FLIP="$5"
fi

SCRIPT="$(dirname "$0")/make_stls.py"

python3 "$SCRIPT" "$SVG" "$THICKNESS" "$HEIGHT" "$CUTOUT" 64 "$FLIP"
