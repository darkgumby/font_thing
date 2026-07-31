#!/usr/bin/env python3
"""
Local web UI for make_stls.py with a built-in Three.js STL preview.

Usage: python3 app.py [--port 5000]
"""

import argparse
import glob
import os
import time
import traceback

from flask import Flask, render_template, request, send_from_directory, redirect, url_for
from werkzeug.utils import secure_filename

from make_stls import make_stls

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(BASE_DIR, "web_outputs")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

app = Flask(__name__)


def svg_search_dirs():
    return [BASE_DIR, UPLOAD_DIR]


def list_svgs():
    names = set()
    for d in svg_search_dirs():
        names.update(os.path.basename(p) for p in glob.glob(os.path.join(d, "*.svg")))
    return sorted(names)


def list_uploaded_svgs():
    """Names deletable via /delete — only ones that actually live in
    UPLOAD_DIR, never the repo's own example SVGs."""
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(UPLOAD_DIR, "*.svg")))


def resolve_svg_path(name):
    """Basename-only lookup across the repo dir and uploads dir — returns
    None if `name` isn't a bare filename or doesn't exist in either."""
    if not name or os.path.basename(name) != name:
        return None
    for d in svg_search_dirs():
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate):
            return candidate
    return None


@app.route("/")
def index():
    return render_template(
        "index.html", svgs=list_svgs(), error=request.args.get("error"),
        selected=request.args.get("selected"), uploaded=list_uploaded_svgs(),
    )


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("svg_file")
    if not file or not file.filename:
        return redirect(url_for("index", error="No file selected"))
    if not file.filename.lower().endswith(".svg"):
        return redirect(url_for("index", error="Only .svg files can be uploaded"))

    name = secure_filename(file.filename)
    if not name:
        return redirect(url_for("index", error="Invalid filename"))

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file.save(os.path.join(UPLOAD_DIR, name))
    return redirect(url_for("index", selected=name))


@app.route("/delete", methods=["POST"])
def delete():
    name = request.form.get("svg", "")
    if not name or os.path.basename(name) != name or name not in list_uploaded_svgs():
        return redirect(url_for("index", error=f"Can't delete {name!r} — only uploaded files can be deleted"))
    os.remove(os.path.join(UPLOAD_DIR, name))
    return redirect(url_for("index"))


@app.route("/svgs/<name>")
def svgs(name):
    path = resolve_svg_path(name)
    if not path:
        return "Not found", 404
    return send_from_directory(os.path.dirname(path), os.path.basename(path), mimetype="image/svg+xml")


@app.route("/generate", methods=["POST"])
def generate():
    svg_name = request.form.get("svg", "")
    svg_path = resolve_svg_path(svg_name)
    if not svg_path:
        return redirect(url_for("index", error=f"Invalid SVG selection: {svg_name!r}"))

    try:
        thickness = float(request.form.get("thickness", 2.0))
        height = float(request.form.get("height", 10.0))
        cutout_depth = float(request.form.get("cutout_depth", 3.0))
        fn = int(request.form.get("fn", 64))
        flip = request.form.get("flip") == "on"
        spike_enabled = request.form.get("spike") == "on"
        spike_length = float(request.form.get("spike_length", 150.0))
        spike_width_raw = request.form.get("spike_width", "").strip()
        spike_width = float(spike_width_raw) if spike_width_raw else None
    except ValueError as e:
        return redirect(url_for("index", error=f"Invalid parameter: {e}"))

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(OUTPUT_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)
    stem = os.path.splitext(svg_name)[0]
    outer_path = os.path.join(run_dir, f"{stem}_outer.stl")
    inner_path = os.path.join(run_dir, f"{stem}_inner.stl")

    try:
        make_stls(
            svg_path, thickness, height, cutout_depth, fn, flip,
            "spike.stl" if spike_enabled else None,
            outer_path, inner_path, spike_length, spike_width,
        )
    except Exception as e:
        traceback.print_exc()
        return redirect(url_for("index", error=f"Generation failed: {e}"))

    return redirect(url_for(
        "preview", run_id=run_id,
        outer=os.path.basename(outer_path), inner=os.path.basename(inner_path),
    ))


@app.route("/preview/<run_id>")
def preview(run_id):
    outer = request.args.get("outer")
    inner = request.args.get("inner")
    run_dir = os.path.join(OUTPUT_ROOT, run_id)
    if not (outer and inner and os.path.isfile(os.path.join(run_dir, outer)) and os.path.isfile(os.path.join(run_dir, inner))):
        return redirect(url_for("index", error="Preview files not found"))
    return render_template(
        "preview.html", run_id=run_id, outer=outer, inner=inner,
        outer_url=url_for("files", run_id=run_id, filename=outer),
        inner_url=url_for("files", run_id=run_id, filename=inner),
    )


@app.route("/files/<run_id>/<filename>")
def files(run_id, filename):
    # run_id comes from our own generated timestamps; filename is basename-
    # checked below, so no path traversal beyond OUTPUT_ROOT is possible
    if os.path.basename(run_id) != run_id or os.path.basename(filename) != filename:
        return "Invalid path", 400
    run_dir = os.path.join(OUTPUT_ROOT, run_id)
    return send_from_directory(run_dir, filename)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    app.run(host=args.host, port=args.port, debug=False)
