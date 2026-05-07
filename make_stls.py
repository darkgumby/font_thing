#!/usr/bin/env python3
"""
Usage: python3 make_stls.py <svg_file> [thickness] [height] [cutout_depth] [fn]

Generates:
  outer.stl  — offset border extruded to `height`, top pocket = SVG shape
  inner.stl — SVG shape extruded to `cutout_depth` (fits into pocket)
"""

import sys
import numpy as np
from svgpathtools import svg2paths
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
import shapely
import shapely.affinity
import trimesh


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


def get_subpath_polygons(svg_file):
    """Return list of shapely Polygons, one per closed SVG subpath."""
    paths, _ = svg2paths(svg_file)
    polys = []
    for path in paths:
        for pts in path_to_subpaths(path):
            if len(pts) < 3:
                continue
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


def build_with_holes(polys):
    """Reconstruct SVG even-odd fill: smaller polygons contained within a larger
    one become its holes. Matches how SVG compound paths render in a browser."""
    sorted_polys = sorted(polys, key=lambda p: p.area, reverse=True)
    used = set()
    result = []

    for i, outer in enumerate(sorted_polys):
        if i in used:
            continue
        holes = []
        for j, inner in enumerate(sorted_polys):
            if j <= i or j in used:
                continue
            if outer.contains(inner.centroid):
                holes.append(list(inner.exterior.coords))
                used.add(j)
        poly = Polygon(list(outer.exterior.coords), holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
        result.append(poly)
        used.add(i)

    return unary_union(result)


def translate_to_origin(geom):
    minx, miny, _, _ = geom.bounds
    return shapely.affinity.translate(geom, xoff=-minx, yoff=-miny)


def extrude(geom, height):
    """Extrude shapely Polygon or MultiPolygon to trimesh solid."""
    if isinstance(geom, Polygon):
        return trimesh.creation.extrude_polygon(geom, height)
    parts = [trimesh.creation.extrude_polygon(p, height) for p in geom.geoms]
    return trimesh.util.concatenate(parts)


def make_stls(svg_file, thickness, height, cutout_depth, fn=64, flip=False):
    print(f"Parsing {svg_file}...")
    polys = get_subpath_polygons(svg_file)
    print(f"  Found {len(polys)} subpath polygons")

    # filled: all interior solid — used for outer border base shape
    filled = translate_to_origin(unary_union(polys))
    filled = shapely.make_valid(filled)

    # with_holes: preserves letter counters — used for cutout and inner.stl
    with_holes = translate_to_origin(build_with_holes(polys))
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

    # Build pocket as one manifold solid — concatenate is not watertight for MultiPolygon
    if isinstance(filled, Polygon):
        pocket = trimesh.creation.extrude_polygon(filled, cutout_depth + 0.01)
    else:
        parts = [trimesh.creation.extrude_polygon(p, cutout_depth + 0.01) for p in filled.geoms]
        pocket = trimesh.boolean.union(parts)
    pocket.apply_translation([0, 0, bottom_h])

    outer_mesh = trimesh.boolean.difference([body, pocket])
    if flip:
        outer_mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0]))
        mn = outer_mesh.bounds[0]
        outer_mesh.apply_translation([-mn[0], -mn[1], -mn[2]])
    outer_mesh.export("outer.stl")
    print("→ outer.stl")

    # inner STL: SVG shape with holes, extruded to cutout_depth
    print("Building inner.stl...")
    if isinstance(with_holes, Polygon):
        inner = trimesh.creation.extrude_polygon(with_holes, cutout_depth)
    else:
        parts = [trimesh.creation.extrude_polygon(p, cutout_depth) for p in with_holes.geoms]
        inner = trimesh.boolean.union(parts)
    if flip:
        inner.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0]))
        mn = inner.bounds[0]
        inner.apply_translation([-mn[0], -mn[1], -mn[2]])
    inner.export("inner.stl")
    print("→ inner.stl")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make_stls.py <svg> [thickness] [height] [cutout_depth] [fn] [flip]")
        sys.exit(1)

    svg_file     = sys.argv[1]
    thickness    = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    height       = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    cutout_depth = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
    fn           = int(sys.argv[5])   if len(sys.argv) > 5 else 64
    flip         = sys.argv[6].lower() in ("1", "true", "yes", "y") if len(sys.argv) > 6 else False

    print(f"SVG:          {svg_file}")
    print(f"Thickness:    {thickness} mm")
    print(f"Height:       {height} mm")
    print(f"Cutout depth: {cutout_depth} mm")
    print(f"FN (round):   {fn}")
    print(f"Flip:         {flip}")
    print()

    make_stls(svg_file, thickness, height, cutout_depth, fn, flip)
