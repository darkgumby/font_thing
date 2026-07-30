# font_thing

Generates two STL files from an SVG for 2-color 3D printing inlay designs.

## Output

**outer.stl** — Solid border piece. The SVG shape is offset outward by `thickness` with rounded corners, extruded to `height`, with a pocket cut into the top surface matching the original SVG shape.

**inner.stl** — Inlay piece. The original SVG shape extruded to `cutout_depth`. Fits flush into the pocket of `outer.stl`.

## Requirements

```bash
pip install shapely svgpathtools trimesh
```

## Usage

### Interactive
```bash
./export_stls.sh
```
Prompts for each parameter.

### Command line
```bash
./export_stls.sh <svg> <thickness> <height> <cutout_depth> [flip]
```

```bash
./export_stls.sh design.svg 4 5 1
./export_stls.sh design.svg 4 5 1 yes   # face-down (rotates 180° on Y axis)
```

### Direct
```bash
python3 make_stls.py <svg> [thickness] [height] [cutout_depth] [fn] [flip]
```

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `svg` | Input SVG file | required |
| `thickness` | Outward border offset in mm | 2.0 |
| `height` | Total height of outer.stl in mm | 10.0 |
| `cutout_depth` | Pocket depth / inner.stl height in mm | 3.0 |
| `fn` | Round corner resolution | 64 |
| `flip` | Rotate 180° on Y axis (face-down printing) | no |

## SVG requirements

- Only `<path>` elements are read (no `<rect>`, `<circle>`, `<polygon>`, etc.).
- Each subpath must be closed. Open paths are dropped.
- Compound paths are supported — nested subpaths (e.g. letter counters like "o", "e", "g") are reconstructed as holes by containment.
- Coordinates are used as raw mm — no viewBox/unit scaling, so draw at 1 unit = 1mm.

## Mesh robustness

Shapes that overlap or touch are extruded correctly:

- Disjoint shapes are concatenated directly.
- Overlapping shapes are grouped (by actual geometric intersection, not just bounding box) and merged with a real boolean union, falling back to a shapely-level union if the mesh boolean fails.
- Polygons whose extrusion isn't a clean manifold volume (e.g. a letter whose counter touches its outer ring at one point) are repaired with `buffer(0)` before extruding.

`inner.stl` can still come back non-watertight at isolated single-point pinches where a letter's hole touches its outer boundary — cosmetic, prints fine.
