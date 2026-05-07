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
