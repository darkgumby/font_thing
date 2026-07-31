# font_thing

Generates two STL files from an SVG for 2-color 3D printing inlay designs.

## Output

**`<svg>_outer.stl`** — Solid border piece. The SVG shape is offset outward by `thickness` with rounded corners, extruded to `height`, with a pocket cut into the top surface matching the SVG shape's stroke outline (counter/island areas, e.g. the two bowls of a "B", stay uncut and flush with the border — only the letter stroke gets recessed). Optionally has a spike/pin embedded into the bottom edge.

**`<svg>_inner.stl`** — Inlay piece. The original SVG shape (with holes preserved) extruded to `cutout_depth`, positioned to drop directly into the pocket of the outer piece — same X/Y/Z placement, so importing both as-is into a slicer already has them aligned for a multi-color print.

Output filenames default to the input SVG's name with `_outer`/`_inner` appended (`design.svg` → `design_outer.stl`, `design_inner.stl`); pass explicit paths to override.

## Requirements

```bash
pip install -r requirements.txt
```

`pyclipper` provides real nonzero-fill winding-rule polygon ops, used to correctly distinguish genuine letter counters from same-winding decorative accents (naive containment-based hole detection gets this wrong on some fonts). `flask`/`werkzeug` are only needed for the web UI. `manifold3d`/`rtree` back some of `trimesh`'s boolean/section operations — not obvious from the import statements, but required.

## Docker

```bash
docker build -t font-thing .
docker run -d -p 5000:5000 --restart unless-stopped font-thing
```

The image ships without any `.svg` files (those are local example/working files, not app code) or `spike.stl` — the app handles both gracefully: an empty SVG list shows an upload prompt instead of a broken dropdown, and a missing `spike.stl` falls back to a procedurally-generated default spike. Add your own SVGs via the web UI's upload feature after deploying.

`uploads/` and `web_outputs/` live inside the container's writable layer — mount them as volumes (`-v` flags) if you need uploaded files or generated STLs to survive a container recreate/redeploy.

## Usage

### Web UI
```bash
python3 app.py [--host 127.0.0.1] [--port 5000]
```
Open the printed URL in a browser:

- **Pick an SVG** from a dropdown listing every `.svg` in this directory (repo dir + `uploads/`), with a live preview image that updates as you change the selection.
- **Upload a new SVG** via the upload form — saved to `uploads/`, validated as `.svg`, filename sanitized, and auto-selected afterward.
- **Delete** the currently-selected SVG from disk (with a confirm prompt) — works for any SVG, not just uploaded ones; these files aren't git-tracked, so this only affects local working files, not version history.
- **Light/dark theme toggle** (top right), defaulting to system preference and persisted in the browser across sessions.
- Set generation parameters (thickness/height/cutout depth/fn/flip, spike options) and **Generate** — renders both output STLs together in one orbit-able Three.js view (drag to rotate, scroll to zoom), correctly aligned at their real relative position (outer in red, inner in white), plus download links. Each generation writes to its own timestamped folder under `web_outputs/` so concurrent/previous runs don't clobber each other.
- If no SVGs exist yet, the dropdown/preview are replaced with an upload prompt instead of showing an unusable empty select.

### Interactive (CLI)
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
python3 make_stls.py <svg> [thickness] [height] [cutout_depth] [fn] [flip] [spike] [outer_out] [inner_out] [spike_length] [spike_width]
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
| `spike` | Attach a spike/pin mesh to the bottom edge, embedded into the border. `yes` uses `spike.stl` in cwd (or a generated default if that file doesn't exist), or pass a path to a different mesh | no |
| `outer_out` | Output path for the outer STL | `<svg>_outer.stl` |
| `inner_out` | Output path for the inner STL | `<svg>_inner.stl` |
| `spike_length` | Spike length in mm (scaled along its long axis, anchored at the blunt end) | 150.0 |
| `spike_width` | Spike cross-section width in mm (scaled anchored at center) | mesh's own width (5mm for the built-in default) |

## Spike attachment

When `spike` is enabled, the spike mesh (`spike.stl` in cwd, a generated default pointed rod if that file is missing, or a custom path) is auto-oriented (long axis detected via PCA, pointed end identified by cross-sectional radius) to lie flat, pointed end leading away from the artwork, rescaled to `spike_length`/`spike_width` and to `height` along Z (so it spans the full piece thickness), and embedded into the bottom edge of the border — centered on whichever letter stroke is closest to the piece's horizontal center. A custom `spike` path that doesn't exist raises an error (only the default `spike.stl` falls back to a generated mesh).

The embed position is verified by real polygon coverage (not just proximity) to guarantee two things regardless of `thickness`:

- The embedded stub is fully inside solid material — never poking out a thin stroke's sides.
- The embedded stub never overlaps the pocket area, so the spike is never exposed inside the pocket cavity.

If the border is too thin anywhere to fit the spike safely (e.g. `spike_width` larger than `thickness` allows), generation fails with a clear error rather than silently placing it unsafely.

## SVG requirements

- Only `<path>` elements are read (no `<rect>`, `<circle>`, `<polygon>`, etc.).
- Each subpath must be closed. Open paths are dropped.
- Compound paths are supported — nested subpaths (e.g. letter counters like "o", "e", "g") are reconstructed as holes using the SVG's actual nonzero-fill winding rule (via `pyclipper`), matching how a browser renders the same path — not a naive "smaller shape inside a bigger one" containment guess, which breaks on fonts that use nested same-winding decorative accents.
- Coordinates are used as raw mm — no viewBox/unit scaling, so draw at 1 unit = 1mm.

## Mesh robustness

Shapes that overlap or touch are extruded correctly:

- Disjoint shapes are concatenated directly.
- Overlapping shapes are grouped (by actual geometric intersection, not just bounding box) and merged with a real boolean union, falling back to a shapely-level union if the mesh boolean fails.
- Polygons whose extrusion isn't a clean manifold volume (e.g. a letter whose counter touches its outer ring at one point) are repaired with `buffer(0)` before extruding.

`inner.stl` can still come back non-watertight at isolated single-point pinches where a letter's hole touches its outer boundary — cosmetic, prints fine.
