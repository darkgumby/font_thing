# font_thing

SVG → two STL files (outer border + inner inlay) for 2-color 3D-print inlay designs. See README.md for user-facing usage/params — this file is for an agent modifying the code.

## Architecture

- **`make_stls.py`** — all geometry logic, single file, no internal package structure. Entry point at bottom (`sys.argv` parsing, `if __name__ == "__main__"`). Called both by `export_stls.sh` (CLI) and `app.py` (web UI, via subprocess or direct import — check `app.py`'s `generate()` route to confirm which).
  - SVG parsing: `get_raw_subpaths`, `get_subpath_polygons`, `path_to_subpaths`
  - Winding/hole resolution: `nonzero_fill` (uses `pyclipper` for real nonzero-fill — do not replace with naive containment checks, that was a past bug)
  - Extrusion: `extrude`, `extrude_clean`, `extrude_group`, `group_overlapping`
  - Spike attachment (optional pin embedded in outer piece): `orient_spike`, `find_fully_embedded_x`, `find_embeddable_spot`, `generate_default_spike`, `scale_axis_centered`, `attach_spike`
  - Orchestration: `make_stls(...)` — ties the above together, called by both CLI and web paths
- **`app.py`** — Flask web UI. Routes: `/` (index/dropdown+preview), `/upload`, `/delete`, `/svgs/<name>` (preview image), `/generate` (runs `make_stls`, writes to timestamped `web_outputs/<run_id>/`), `/preview/<run_id>` (Three.js dual-STL viewer), `/files/<run_id>/<filename>` (download).
- **`templates/`** — `index.html` (upload/select/params form), `preview.html` (Three.js viewer).
- **`export_stls.sh`** — thin CLI wrapper, prompts for missing args, calls `make_stls.py` via `python3`.

## Conventions / gotchas

- Coordinates are raw mm, no SVG viewBox/unit scaling — don't add unit conversion.
- Only `<path>` elements are read from SVGs; other SVG shape elements are silently ignored (by design, see README's "SVG requirements").
- Hole detection MUST go through `pyclipper`'s nonzero-fill winding (`nonzero_fill`) — naive size/containment-based hole detection breaks on fonts with nested same-winding decorative accents (this was fixed once already).
- Spike embedding is safety-checked by real polygon coverage (`find_fully_embedded_x`/`find_embeddable_spot`), not proximity — keep it that way; a proximity-only check can place spikes poking out of thin strokes.
- `manifold3d`/`rtree` are required even though nothing imports them directly by name — they back some of `trimesh`'s boolean/section ops. Don't remove them from `requirements.txt` on the assumption they're unused.
- `spike.stl` is excluded from the Docker image on purpose; missing-file fallback (`generate_default_spike`) must keep working.
- No automated test suite exists yet — verify geometry changes by actually running `make_stls.py` against `test.svg`/`sombrero_plain.svg`/`hello_world.svg` and inspecting the resulting STLs (e.g. load in a viewer, or check `trimesh` reports a valid watertight mesh).

## Workflow rules (from global CLAUDE.md, repeated here since project-local docs are read first)

- Branch before making changes; don't commit to `main` directly.
- Keep README.md and TODO.md current whenever features are added/removed/changed.
- This project has no help dialog/modal in the web UI currently — if one is added, keep it in sync with README too.
- Never commit without explicit user instruction.
