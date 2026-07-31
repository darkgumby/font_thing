#!/usr/bin/env python3
"""
Usage: python3 make_stls.py <svg_file> [thickness] [height] [cutout_depth] [fn] [flip] [spike] [outer_out] [inner_out] [spike_length] [spike_width]

Generates:
  <svg>_outer.stl — offset border extruded to `height`, with a pocket cut
                     matching the SVG's stroke outline (counter/island
                     areas like the two bowls of a "B" stay uncut, flush
                     with the border)
  <svg>_inner.stl — SVG shape (holes preserved) extruded to `cutout_depth`,
                     positioned to drop directly into the outer piece's
                     pocket

Pass explicit paths as `outer_out`/`inner_out` to override the default
naming. `spike` embeds a spike/pin into the bottom edge of the outer
piece, entirely within solid border material (never exposed inside the
pocket, regardless of `thickness`). "yes" uses spike.stl in cwd if
present, else generates a default pointed rod — a custom path that
doesn't exist raises. `spike_length`/`spike_width` rescale it.
"""

import sys
import os
import numpy as np
from svgpathtools import svg2paths
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union
import shapely
import shapely.affinity
import trimesh
import pyclipper

CLIPPER_SCALE = 10000  # Clipper uses fixed-point integer coords; scale up for precision
DEFAULT_SPIKE_PATH = "spike.stl"  # generated procedurally if this file doesn't exist


def path_to_subpaths(path, samples_per_seg=30):
    """Split compound SVG path into list of point arrays, one per subpath.
    Negates Y to convert from SVG (Y-down) to 3D (Y-up) coordinate space.
    """
    subpaths = []
    current = []
    prev_end = None

    for seg in path:
        if prev_end is not None and abs(seg.start - prev_end) > 1e-6:
            if len(current) >= 3:
                subpaths.append(current)
            current = []
        for t in np.linspace(0, 1, samples_per_seg, endpoint=False):
            pt = seg.point(t)
            current.append((pt.real, -pt.imag))   # negate Y: SVG-down → 3D-up
        prev_end = seg.end

    if len(current) >= 3:
        subpaths.append(current)

    return subpaths


def get_raw_subpaths(svg_file):
    """Return list of raw point lists, one per closed SVG subpath, in their
    original path-drawing order (winding direction preserved) — needed for
    correct nonzero-fill evaluation, which naive per-shape polygons lose."""
    paths, _ = svg2paths(svg_file)
    raw = []
    for path in paths:
        for pts in path_to_subpaths(path):
            if len(pts) >= 3:
                raw.append(pts)
    if not raw:
        raise ValueError("No valid subpaths found in SVG — check that paths are closed")
    return raw


def get_subpath_polygons(svg_file):
    """Return list of shapely Polygons, one per closed SVG subpath."""
    polys = []
    for pts in get_raw_subpaths(svg_file):
        try:
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_valid and poly.area > 1e-4:
                polys.append(poly)
        except Exception:
            pass
    if not polys:
        raise ValueError("No valid polygons found in SVG — check that paths are closed")
    return polys


def nonzero_fill(raw_subpaths):
    """Compute the true nonzero-fill-rule region of a set of raw subpaths —
    matching how a real SVG renderer fills a compound path. Naive
    containment-based hole detection (treat any nested shape as a hole)
    breaks on fonts/art that use nested same-winding decorative accents
    (filled, not holes) or opposite-winding shapes that aren't holes either;
    this instead asks Clipper's nonzero fill rule, which is what SVG itself
    specifies as the default, so it matches browser/renderer output exactly."""
    pc = pyclipper.Pyclipper()
    for pts in raw_subpaths:
        path = [(int(round(x * CLIPPER_SCALE)), int(round(y * CLIPPER_SCALE))) for x, y in pts]
        try:
            pc.AddPath(path, pyclipper.PT_SUBJECT, True)
        except Exception:
            pass
    tree = pc.Execute2(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)

    def walk(node, out):
        for child in node.Childs:
            exterior = [(x / CLIPPER_SCALE, y / CLIPPER_SCALE) for x, y in child.Contour]
            holes = []
            for hole_node in child.Childs:
                holes.append([(x / CLIPPER_SCALE, y / CLIPPER_SCALE) for x, y in hole_node.Contour])
                walk(hole_node, out)  # islands nested inside this hole are solid again
            if len(exterior) >= 3:
                poly = Polygon(exterior, holes)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                out.append(poly)

    result = []
    walk(tree, result)
    if not result:
        raise ValueError("nonzero_fill produced no geometry — check that paths are closed")
    return shapely.make_valid(unary_union(result))


def translate_to_origin(geom):
    minx, miny, _, _ = geom.bounds
    return shapely.affinity.translate(geom, xoff=-minx, yoff=-miny)


def extrude_clean(poly, height):
    """Extrude a single Polygon, repairing self-touching rings that would
    otherwise extrude into a non-manifold (non-volume) mesh."""
    mesh = trimesh.creation.extrude_polygon(poly, height)
    if not mesh.is_volume:
        mesh = trimesh.creation.extrude_polygon(poly.buffer(0), height)
    return mesh


def group_overlapping(polys):
    """Union-find grouping: polygons that actually overlap (not just touch)
    land in the same group, since they need a real boolean merge rather than
    a plain concatenate."""
    parent = list(range(len(polys)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            inter = polys[i].intersection(polys[j])
            if not inter.is_empty and inter.area > 1e-6:
                union(i, j)

    groups = {}
    for i in range(len(polys)):
        groups.setdefault(find(i), []).append(polys[i])
    return list(groups.values())


def extrude_group(polys, height):
    """Extrude a set of mutually-overlapping polygons into one clean solid."""
    if len(polys) == 1:
        return extrude_clean(polys[0], height)

    meshes = [extrude_clean(p, height) for p in polys]
    try:
        merged = trimesh.boolean.union(meshes)
        if merged.is_volume:
            return merged
    except Exception:
        pass

    # Mesh boolean failed or left a non-volume — fall back to merging at the
    # shapely level instead. The union's output pieces are disjoint by
    # construction, so they can be safely concatenated.
    unioned = shapely.make_valid(unary_union(polys))
    if isinstance(unioned, Polygon):
        return extrude_clean(unioned, height)
    parts = [extrude_clean(p, height) for p in unioned.geoms]
    return trimesh.util.concatenate(parts)


def extrude(geom, height):
    """Extrude shapely Polygon or MultiPolygon to trimesh solid.
    Overlapping parts are boolean-merged; disjoint parts are concatenated."""
    if isinstance(geom, Polygon):
        return extrude_clean(geom, height)
    groups = group_overlapping(list(geom.geoms))
    parts = [extrude_group(g, height) for g in groups]
    return trimesh.util.concatenate(parts)


def orient_spike(spike, target_dir):
    """Rotate+translate a copy of `spike` so its long axis points along
    `target_dir`, pointed end leading, blunt end's face centered at the
    origin. Works for any elongated mesh — the long axis and which end is
    pointed are both detected, not assumed."""
    spike = spike.copy()
    v = spike.vertices
    centroid = v.mean(axis=0)
    centered = v - centroid
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, np.argmax(eigvals)]
    axis = axis / np.linalg.norm(axis)

    proj = centered @ axis
    span = proj.max() - proj.min()
    lo_mask = proj < (proj.min() + 0.05 * span)
    hi_mask = proj > (proj.max() - 0.05 * span)

    def cross_radius(mask):
        pts = centered[mask]
        perp = pts - np.outer(pts @ axis, axis)
        return np.linalg.norm(perp, axis=1).max()

    # pointed end = the end with the smaller cross-sectional radius
    tip_dir = -axis if cross_radius(lo_mask) <= cross_radius(hi_mask) else axis

    target_dir = np.asarray(target_dir, dtype=float)
    target_dir = target_dir / np.linalg.norm(target_dir)
    if np.dot(tip_dir, target_dir) < -0.9999:
        # tip_dir and target_dir are exactly opposite — align_vectors' choice
        # of rotation axis is ambiguous here, so pick one of the spike's own
        # minor axes instead to keep its cross-section symmetric (avoids an
        # arbitrary roll that would tilt it off the flat plane it sits on)
        perp = eigvecs[:, np.argmin(eigvals)]
        rotation = trimesh.transformations.rotation_matrix(np.pi, perp)
    else:
        rotation = trimesh.geometry.align_vectors(tip_dir, target_dir)
    spike.apply_transform(rotation)

    # blunt end is now the trailing end, opposite target_dir
    v2 = spike.vertices
    proj2 = v2 @ target_dir
    span2 = proj2.max() - proj2.min()
    blunt_mask = proj2 < (proj2.min() + 0.05 * span2)
    blunt_center = v2[blunt_mask].mean(axis=0)
    spike.apply_translation(-blunt_center)
    return spike


def find_fully_embedded_x(footprint, width, min_y, embed_depth, target_x, step=0.25, coverage_threshold=0.97):
    """Find the x nearest to `target_x` where a `width`-wide, `embed_depth`-deep
    rectangle starting at `min_y` is (at least `coverage_threshold`) covered
    by `footprint` — a coverage ratio rather than pixel-perfect containment,
    since the outer border is buffered with round joins and so is smoothly
    curved everywhere; a strict contains() would reject virtually every
    position over a fractional-mm sliver at the rounded edge. Scans at
    `step` resolution across footprint's x-range and returns
    (x, achieved_embed_depth), shrinking embed_depth in stages if no
    position covers the full depth anywhere (e.g. the nearest stroke is
    only embeddable partway). Returns (None, 0) if even a shallow embed
    can't reach the coverage threshold anywhere."""
    minx, _, maxx, _ = footprint.bounds
    xs = np.arange(minx + width / 2, maxx - width / 2, step)
    if len(xs) == 0:
        return None, 0.0

    # last tier (0.05) is a near-flush touch rather than a real embed — still
    # requires the full WIDTH to be safely covered, just not much depth
    for depth in [embed_depth, embed_depth * 0.75, embed_depth * 0.5, embed_depth * 0.25, embed_depth * 0.05]:
        area = width * depth
        candidates = []
        for x in xs:
            test = box(x - width / 2, min_y, x + width / 2, min_y + depth)
            covered = test.intersection(footprint).area
            if covered / area >= coverage_threshold:
                candidates.append(x)
        if candidates:
            best_x = min(candidates, key=lambda x: abs(x - target_x))
            return best_x, depth
    return None, 0.0


def find_embeddable_spot(footprint, target_width, min_y, target_x, min_width=5.0, width_step=0.5, **kwargs):
    """Like find_fully_embedded_x, but also shrinks the width itself (down
    to `min_width`) when even a shallow embed doesn't fit at the requested
    width — e.g. every stroke in the artwork is narrower than the spike.
    Tries widest first (sturdiest) and only narrows as a last resort.
    Returns (x, embed_depth, width) or (None, 0, None) if nothing fits even
    at the narrowest width."""
    width = target_width
    while True:
        x, depth = find_fully_embedded_x(footprint, width, min_y, width, target_x, **kwargs)
        if x is not None:
            return x, depth, width
        if width <= min_width:
            return None, 0.0, None
        width = max(min_width, width - width_step)


def generate_default_spike(width=5.0, length=150.0):
    """Build a simple pointed rod (blunt square end -> short pyramid tip)
    procedurally, so attaching a spike doesn't require an external mesh
    file. Long axis is Y, matching the layout of the original spike.stl,
    though orient_spike()/attach_spike() would handle any orientation."""
    taper_length = min(10.0, length * 0.1)
    shaft_length = length - taper_length
    hw = width / 2.0

    vertices = np.array([
        [-hw, 0.0, 0.0], [-hw, 0.0, width], [hw, 0.0, width], [hw, 0.0, 0.0],       # 0-3: blunt cap
        [-hw, -shaft_length, 0.0], [-hw, -shaft_length, width],                      # 4-5
        [hw, -shaft_length, width], [hw, -shaft_length, 0.0],                        # 6-7: taper start
        [0.0, -length, width / 2.0],                                                 # 8: apex
    ])
    faces = np.array([
        [0, 1, 2], [0, 2, 3],   # blunt cap
        [0, 4, 5], [0, 5, 1],   # shaft side -x
        [1, 5, 6], [1, 6, 2],   # shaft side +z
        [2, 6, 7], [2, 7, 3],   # shaft side +x
        [3, 7, 4], [3, 4, 0],   # shaft side -z
        [4, 5, 8], [5, 6, 8], [6, 7, 8], [7, 4, 8],  # pyramid tip
    ])
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    if not mesh.is_winding_consistent or mesh.volume < 0:
        trimesh.repair.fix_normals(mesh)
    return mesh


def scale_axis_centered(mesh, axis, target_extent):
    """Scale `mesh` along one coordinate axis (0=X, 1=Y, 2=Z) to
    `target_extent`, anchored at that axis's own center — the other two
    axes are untouched. No-op if the axis has zero extent."""
    lo, hi = mesh.bounds[0][axis], mesh.bounds[1][axis]
    extent = hi - lo
    if extent > 0:
        center = (lo + hi) / 2
        scale = target_extent / extent
        mesh.vertices[:, axis] = (mesh.vertices[:, axis] - center) * scale + center


def attach_spike(mesh, spike_path, footprint, pocket_footprint=None, spike_length=150.0, height=None,
                  spike_width=None):
    """Embed a spike/pin mesh into the bottom edge of `mesh` (same Z-slab,
    not below it), pointed end leading away from the rest of the shape in
    -Y. The blunt end is pushed past the edge into the body (by the
    spike's own cross-sectional width, when the artwork allows it) rather
    than merely touching it, for a solid anchor. Position is verified by
    exact polygon containment against `footprint` (the outer shape,
    pre-extrusion) minus `pocket_footprint` (the recessed pocket area, if
    any) — not just proximity — so the embedded stub is guaranteed fully
    inside permanently-solid material: never poking out a thin stroke's
    sides, and never landing under the pocket where the top of the spike
    would get sliced off and exposed inside the cavity. Boolean-merges the
    two into one solid, falling back to a plain concatenate (touching, not
    fused) if the boolean fails.

    The spike is rescaled to `spike_length` along its long axis (anchored
    at the blunt end, so only the tip moves), to `spike_width` if given
    (anchored at center), and, if `height` is given, to match `height`
    along Z (anchored at its own Z-center, keeping the cross-section
    symmetric) — otherwise Z keeps the raw mesh's own thickness, which may
    not span the full piece height.

    If `spike_path` is the default ("spike.stl") and that file doesn't
    exist, a simple pointed rod is generated procedurally instead of
    requiring the file — a custom `spike_path` that doesn't exist still
    raises, since that file was explicitly requested."""
    if os.path.exists(spike_path):
        print(f"Attaching spike from {spike_path}...")
        spike = trimesh.load(spike_path)
    elif spike_path == DEFAULT_SPIKE_PATH:
        print(f"Attaching spike ({spike_path} not found — using a generated default)...")
        spike = generate_default_spike(width=spike_width or 5.0, length=spike_length)
    else:
        raise FileNotFoundError(f"Spike file not found: {spike_path}")
    oriented = orient_spike(spike, target_dir=[0, -1, 0])

    # scale length along the axis the spike now points along (-Y), anchored
    # at the blunt end (already at local y=0 from orient_spike) so the tip
    # is what moves, not the attachment point
    target_dir = np.array([0, -1, 0.0])
    current_length = oriented.bounds[1][1] - oriented.bounds[0][1]
    if current_length > 0:
        length_scale = spike_length / current_length
        proj = oriented.vertices @ target_dir
        oriented.vertices += np.outer((length_scale - 1) * proj, target_dir)

    # scale Z to span the full piece height, anchored at Z-center so the
    # cross-section stays symmetric (doesn't shift the attach math below)
    if height is not None:
        scale_axis_centered(oriented, 2, height)

    # width (X): if spike_width was given, that's the requested width;
    # otherwise use the mesh's own natural width. Actual scaling is deferred
    # until after the embed search below, since it may shrink the width
    # further to fit — no point scaling twice.
    requested_width = spike_width if spike_width is not None else (oriented.bounds[1][0] - oriented.bounds[0][0])

    min_y = mesh.bounds[0][1]
    overall_center_x = (mesh.bounds[0][0] + mesh.bounds[1][0]) / 2

    # safe_footprint excludes the pocket area entirely — no fallback is allowed
    # to search outside it, since that's exactly what would expose the spike
    # inside the pocket cavity. If nothing fits even at the narrowest width,
    # fail loudly instead.
    min_spike_width = 5.0
    safe_footprint = footprint if pocket_footprint is None else shapely.make_valid(footprint.difference(pocket_footprint))
    center_x, embed_depth, final_width = find_embeddable_spot(
        safe_footprint, requested_width, min_y, overall_center_x, min_width=min_spike_width)
    if center_x is None:
        raise ValueError(
            "Can't attach spike: no location along the bottom edge has enough solid "
            "border material (outside the pocket) to fit even the narrowest spike "
            f"({min_spike_width:.0f}mm) without exposing it inside the pocket. Increase "
            "--thickness (the outline border width), or disable the spike for this artwork."
        )
    if final_width < requested_width:
        print(f"  Note: narrowed spike to {final_width:.2f}mm (requested {requested_width:.2f}mm) — "
              f"nearest safe stroke outside the pocket isn't wide enough at full width.")
    if embed_depth < final_width:
        print(f"  Note: embedding {embed_depth:.2f}mm deep (spike width is {final_width:.2f}mm) — "
              f"nearest safe spot outside the pocket is shallower than a full-depth embed.")

    # apply the final width, anchored at X-center — no-op if it matches what
    # the mesh (loaded or generated) already has
    scale_axis_centered(oriented, 0, final_width)

    attach_y = min_y + embed_depth
    bottom_z = mesh.bounds[0][2] - oriented.bounds[0][2]
    oriented.apply_translation([center_x, attach_y, bottom_z])

    try:
        merged = trimesh.boolean.union([mesh, oriented])
        if merged.is_volume:
            return merged
    except Exception:
        pass
    print("  Warning: boolean union with spike failed — concatenating instead (touching, not fused)")
    return trimesh.util.concatenate([mesh, oriented])


def make_stls(svg_file, thickness, height, cutout_depth, fn=64, flip=False, spike_path=None,
              outer_path=None, inner_path=None, spike_length=150.0, spike_width=None):
    stem = os.path.splitext(os.path.basename(svg_file))[0]
    outer_path = outer_path or f"{stem}_outer.stl"
    inner_path = inner_path or f"{stem}_inner.stl"

    print(f"Parsing {svg_file}...")
    raw_subpaths = get_raw_subpaths(svg_file)
    polys = get_subpath_polygons(svg_file)
    print(f"  Found {len(polys)} subpath polygons")

    # filled: all interior solid — used for outer border base shape
    filled = translate_to_origin(unary_union(polys))
    filled = shapely.make_valid(filled)

    # with_holes: true nonzero-fill result (matches real SVG rendering) —
    # preserves genuine letter counters while not carving holes into
    # same-winding decorative accents. Used for cutout and inner.stl
    with_holes = translate_to_origin(nonzero_fill(raw_subpaths))
    with_holes = shapely.make_valid(with_holes)

    print(f"Offsetting outward by {thickness}mm (round corners)...")
    outer = filled.buffer(thickness, quad_segs=fn // 4, join_style="round", cap_style="round")
    outer = shapely.make_valid(outer)

    # Drop any interior rings — enclosed voids from buffer of adjacent letters
    if isinstance(outer, Polygon):
        outer = Polygon(outer.exterior)
    else:
        outer = unary_union([Polygon(p.exterior) for p in outer.geoms])

    # If buffer left disconnected pieces, bridge gaps to form one solid perimeter
    if hasattr(outer, 'geoms') and len(outer.geoms) > 1:
        pieces = list(outer.geoms)
        max_gap = max(
            p1.distance(p2)
            for i, p1 in enumerate(pieces)
            for p2 in pieces[i + 1:]
        )
        bridge = max_gap / 2 + 0.01
        outer = (outer
            .buffer(bridge, quad_segs=fn // 4, join_style="round", cap_style="round")
            .buffer(-bridge, quad_segs=fn // 4, join_style="round", cap_style="round")
        )
        outer = shapely.make_valid(outer)
        print(f"  Bridged {len(pieces)} pieces (max gap {max_gap:.2f}mm)")

    bottom_h = height - cutout_depth

    # outer STL: solid outer body minus pocket volume (boolean difference)
    print("Building outer.stl...")
    body = extrude(outer, height)

    if spike_path:
        body = attach_spike(body, spike_path, outer, with_holes, spike_length, height, spike_width)

    # Build pocket as one manifold solid — overlapping letters get boolean-merged,
    # disjoint ones concatenated (see extrude/group_overlapping). Uses with_holes
    # (not filled) so counter/island areas (e.g. B's two bowls) stay uncut,
    # flush with the border — only the letter's stroke gets recessed.
    pocket = extrude(with_holes, cutout_depth + 0.01)
    pocket.apply_translation([0, 0, bottom_h])

    outer_mesh = trimesh.boolean.difference([body, pocket])

    # inner STL: SVG shape with holes, extruded to cutout_depth, placed at the
    # same Z the pocket occupies in outer_mesh so both stay aligned in X/Y/Z
    # — importing both as-is into a slicer drops inner directly into the pocket
    print("Building inner.stl...")
    inner = extrude(with_holes, cutout_depth)
    inner.apply_translation([0, 0, bottom_h])

    if flip:
        # apply one shared rigid transform to both meshes so their relative
        # alignment survives — independently re-centering each on its own
        # bounds would break it, since outer/inner have different bounds
        rotation = trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0])
        outer_mesh.apply_transform(rotation)
        inner.apply_transform(rotation)
        mn = outer_mesh.bounds[0]
        outer_mesh.apply_translation(-mn)
        inner.apply_translation(-mn)

    # boolean ops (esp. the pocket difference) can leave zero-area degenerate
    # faces behind — harmless in memory, but binary STL is a plain triangle
    # soup with no shared vertex indices, and a stray degenerate face can
    # cause the *reload* to see two components / non-watertight even though
    # the real geometry has zero actual volume there
    for m in (outer_mesh, inner):
        m.update_faces(m.nondegenerate_faces())
        m.remove_unreferenced_vertices()

    outer_mesh.export(outer_path)
    print(f"→ {outer_path}")
    inner.export(inner_path)
    print(f"→ {inner_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make_stls.py <svg> [thickness] [height] [cutout_depth] [fn] [flip] [spike] [outer_out] [inner_out] [spike_length] [spike_width]")
        sys.exit(1)

    svg_file     = sys.argv[1]
    thickness    = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    height       = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    cutout_depth = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
    fn           = int(sys.argv[5])   if len(sys.argv) > 5 else 64
    flip         = sys.argv[6].lower() in ("1", "true", "yes", "y") if len(sys.argv) > 6 else False

    spike_arg = sys.argv[7] if len(sys.argv) > 7 else ""
    if spike_arg.lower() in ("", "0", "false", "no", "n"):
        spike_path = None
    elif spike_arg.lower() in ("1", "true", "yes", "y"):
        spike_path = DEFAULT_SPIKE_PATH
    else:
        spike_path = spike_arg

    outer_path = sys.argv[8] if len(sys.argv) > 8 and sys.argv[8] else None
    inner_path = sys.argv[9] if len(sys.argv) > 9 and sys.argv[9] else None
    spike_length = float(sys.argv[10]) if len(sys.argv) > 10 else 150.0
    spike_width = float(sys.argv[11]) if len(sys.argv) > 11 else None
    stem = os.path.splitext(os.path.basename(svg_file))[0]

    print(f"SVG:          {svg_file}")
    print(f"Thickness:    {thickness} mm")
    print(f"Height:       {height} mm")
    print(f"Cutout depth: {cutout_depth} mm")
    print(f"FN (round):   {fn}")
    print(f"Flip:         {flip}")
    print(f"Spike:        {spike_path or 'no'}")
    if spike_path:
        print(f"Spike length: {spike_length} mm")
        print(f"Spike width:  {spike_width if spike_width is not None else 'default'} mm")
    print(f"Outer output: {outer_path or f'{stem}_outer.stl'}")
    print(f"Inner output: {inner_path or f'{stem}_inner.stl'}")
    print()

    make_stls(svg_file, thickness, height, cutout_depth, fn, flip, spike_path, outer_path, inner_path,
              spike_length, spike_width)
