#!/usr/bin/env python3
"""
Image Viewer Agent — PIL-based structural image analyzer.
Extracts layout, color regions, and text-dense areas as structured JSON.

Usage:
    python analyze_image.py <image_path> [--output result.json] [--detail high|medium|low]

Output: JSON with layout analysis, color regions, and content hints.
Meant as a fallback when multimodal models cannot read images directly.
"""

import sys
import json
import os
from collections import Counter

try:
    from PIL import Image, ImageStat, ImageFilter
except ImportError:
    print(json.dumps({"error": "PIL/Pillow not installed. Run: pip install Pillow"}))
    sys.exit(1)


def analyze_image(image_path, detail="medium"):
    """Main entry: analyze an image and return structured results."""
    if not os.path.exists(image_path):
        return {"error": f"File not found: {image_path}"}

    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    # Scale for faster processing
    if detail == "high":
        scale = max(1, min(w, h) // 600)
    elif detail == "low":
        scale = max(1, min(w, h) // 200)
    else:  # medium
        scale = max(1, min(w, h) // 400)

    small_w, small_h = w // scale, h // scale
    small = img.resize((small_w, small_h), Image.LANCZOS)
    pixels = list(small.get_flattened_data())

    result = {
        "file": os.path.basename(image_path),
        "dimensions": {"width": w, "height": h},
        "aspect_ratio": round(w / h, 2),
        "scale_factor": scale,
        "analysis": {}
    }

    # 1. Overall color analysis
    result["analysis"]["color"] = analyze_colors(pixels, small_w, small_h)

    # 2. Layout structure (horizontal/vertical bands)
    result["analysis"]["layout"] = analyze_layout(small_w, small_h, pixels)

    # 3. Edge density (indicates text/detail regions)
    result["analysis"]["edge_density"] = analyze_edges(small, small_w, small_h)

    # 4. Screen type inference
    result["analysis"]["screen_type"] = infer_type(result["analysis"])

    # 5. Content zones (largest colored blocks)
    result["analysis"]["zones"] = find_zones(small_w, small_h, pixels)

    return result


def analyze_colors(pixels, w, h):
    """Analyze color distribution of the image."""
    # Fast sampling: every Nth pixel
    step = max(1, len(pixels) // 2000)
    sampled = pixels[::step]

    # HSL conversion helpers
    def rgb_to_hsl(r, g, b):
        r, g, b = r / 255.0, g / 255.0, b / 255.0
        mx, mn = max(r, g, b), min(r, g, b)
        l = (mx + mn) / 2
        if mx == mn:
            h = s = 0.0
        else:
            d = mx - mn
            s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
            if mx == r:
                h = (g - b) / d + (6 if g < b else 0)
            elif mx == g:
                h = (b - r) / d + 2
            else:
                h = (r - g) / d + 4
            h /= 6
        return h * 360, s, l

    # Classify each color
    dark_count = light_count = mid_count = 0
    red_count = green_count = blue_count = orange_count = yellow_count = 0
    gray_count = 0

    for r, g, b in sampled:
        brightness = (r + g + b) / 3
        if brightness < 60:
            dark_count += 1
        elif brightness > 200:
            light_count += 1
        else:
            mid_count += 1

        # Dominant channel detection
        if r > 100 and r > g * 1.3 and r > b * 1.3:
            red_count += 1
        elif g > 100 and g > r * 1.3 and g > b * 1.3:
            green_count += 1
        elif b > 100 and b > r * 1.3 and b > g * 1.3:
            blue_count += 1
        elif r > 150 and g > 100 and b < r * 0.7:
            orange_count += 1
        elif r > 150 and g > 150 and b < r * 0.8:
            yellow_count += 1

        # Gray detection
        if max(r, g, b) - min(r, g, b) < 20:
            gray_count += 1

    total = len(sampled)
    total_pixels = len(pixels)

    # Unique-color signal (helps detect solid/low-texture images).
    # JPEG noise is reduced by quantizing to 32-step bins before counting.
    unique_colors = len({(r // 32, g // 32, b // 32) for r, g, b in sampled})

    # Dominant hue share (ratio of the most frequent color family).
    hue_counts = {
        "red": red_count, "green": green_count, "blue": blue_count,
        "orange": orange_count, "yellow": yellow_count,
    }
    dominant_hue = max(hue_counts, key=lambda k: hue_counts[k])
    dominant_hue_share = round(hue_counts[dominant_hue] / total * 100, 1) if total else 0.0

    return {
        "total_pixels": total_pixels,
        "brightness": {
            "dark_pct": round(dark_count / total * 100, 1),
            "mid_pct": round(mid_count / total * 100, 1),
            "light_pct": round(light_count / total * 100, 1),
            "dominant": "dark" if dark_count > mid_count and dark_count > light_count
            else "light" if light_count > dark_count and light_count > mid_count
            else "mid"
        },
        "hue_dominance": {
            "red_pct": round(red_count / total * 100, 1),
            "green_pct": round(green_count / total * 100, 1),
            "blue_pct": round(blue_count / total * 100, 1),
            "orange_pct": round(orange_count / total * 100, 1),
            "yellow_pct": round(yellow_count / total * 100, 1),
            "gray_pct": round(gray_count / total * 100, 1),
        },
        "is_dark_theme": dark_count > light_count,
        "unique_colors": unique_colors,
        "dominant_hue": dominant_hue,
        "dominant_hue_share": dominant_hue_share,
    }


def analyze_layout(w, h, pixels):
    """Analyze horizontal band structure to detect UI layout."""
    bands = []
    band_height = max(1, h // 30)  # ~30 horizontal bands
    rows_per_band = h // band_height

    for i in range(min(30, band_height)):
        start_row = i * rows_per_band
        end_row = min((i + 1) * rows_per_band, h)

        band_pixels = []
        for row in range(start_row, end_row):
            for col in range(w):
                idx = row * w + col
                if idx < len(pixels):
                    band_pixels.append(pixels[idx])

        if band_pixels:
            avg_brightness = sum(sum(p) / 3 for p in band_pixels) / len(band_pixels)
            # Color variance
            r_vals = [p[0] for p in band_pixels]
            g_vals = [p[1] for p in band_pixels]
            b_vals = [p[2] for p in band_pixels]
            r_var = max(r_vals) - min(r_vals)
            g_var = max(g_vals) - min(g_vals)
            b_var = max(b_vals) - min(b_vals)

            bands.append({
                "y_start": start_row,
                "y_end": end_row,
                "avg_brightness": round(avg_brightness, 1),
                "color_variance": round((r_var + g_var + b_var) / 3, 1),
                "likely_type": "text_area" if (r_var + g_var + b_var) / 3 > 30
                else "solid_area"
            })

    # Detect header/footer (first/last 5% that are uniform)
    header_band = bands[:max(1, len(bands) // 10)]
    footer_band = bands[-max(1, len(bands) // 10):]

    return {
        "band_count": len(bands),
        "header_likely": _is_uniform(header_band),
        "footer_likely": _is_uniform(footer_band),
        "content_starts_at_pct": round(100 * _find_content_start(bands) / h, 1),
        "bands": bands[:15] + bands[-5:] if len(bands) > 20 else bands
    }


def _is_uniform(bands):
    """Check if bands are uniform (likely header/footer/toolbar)."""
    if not bands:
        return False
    brightnesses = [b["avg_brightness"] for b in bands]
    return max(brightnesses) - min(brightnesses) < 15


def _find_content_start(bands):
    """Find where content begins (after header/toolbar)."""
    for i, band in enumerate(bands):
        if band["color_variance"] > 20:
            return band["y_start"]
    return bands[0]["y_start"] if bands else 0


def analyze_edges(small_img, w, h):
    """Detect edge density to find text-rich regions."""
    gray = small_img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_pixels = list(edges.get_flattened_data())

    # Divide into a 10x10 grid, compute edge density per cell
    grid_size = 10
    cell_w, cell_h = w // grid_size, h // grid_size
    grid = []

    for row in range(grid_size):
        for col in range(grid_size):
            edge_count = 0
            pixel_count = 0
            for y in range(row * cell_h, min((row + 1) * cell_h, h)):
                for x in range(col * cell_w, min((col + 1) * cell_w, w)):
                    idx = y * w + x
                    if idx < len(edge_pixels):
                        if edge_pixels[idx] > 30:  # Edge threshold
                            edge_count += 1
                        pixel_count += 1
            if pixel_count > 0:
                grid.append({
                    "row": row, "col": col,
                    "edge_density": round(edge_count / pixel_count * 100, 1)
                })

    # Find "hot zones" - cells with high edge density (text areas)
    hot_zones = [g for g in grid if g["edge_density"] > 8]
    cold_zones = [g for g in grid if g["edge_density"] < 2]

    avg_density = sum(g["edge_density"] for g in grid) / len(grid) if grid else 0

    return {
        "grid_cells": grid,
        "avg_edge_density": round(avg_density, 1),
        "text_rich_zones": len(hot_zones),
        "flat_zones": len(cold_zones),
        "likely_has_text": len(hot_zones) > 5,
        "likely_screenshot_of_text": avg_density > 5 and len(hot_zones) > 3
    }


def infer_type(analysis):
    """Infer what kind of image this is."""
    color = analysis["color"]
    edge = analysis["edge_density"]
    layout = analysis["layout"]

    clues = []

    # Solid / low-texture image detection (highest priority).
    # A uniform flat color (e.g. a pure-blue test image) has almost no unique
    # quantized colors, minimal edge detail, and a single overwhelming color
    # family. Even if uniform bands look like title bars, it should never be
    # mistaken for a real UI screenshot.
    if (
        color.get("unique_colors", 100) <= 8
        and edge["avg_edge_density"] < 5
        and color.get("dominant_hue_share", 0) > 85
    ):
        clues.append("likely_solid_low_texture")
        return {
            "clues": clues,
            "best_guess": "纯色/低纹理画面 (uniform flat color)",
        }

    # Dark theme vs light theme
    if color["is_dark_theme"]:
        clues.append("dark_theme")

    # Screenshot of code/terminal
    if color["brightness"]["dark_pct"] > 70 and edge["likely_has_text"]:
        clues.append("likely_code_editor")
    elif edge["likely_screenshot_of_text"] and color["brightness"]["light_pct"] > 50:
        clues.append("likely_document_or_chat")

    # UI screenshot
    if layout["header_likely"] or layout["footer_likely"]:
        clues.append("has_ui_chrome")

    # Presentation/slide
    if color["brightness"]["dark_pct"] > 80 and color["hue_dominance"]["blue_pct"] > 10:
        clues.append("likely_dark_slide_or_diagram")

    # Webpage
    if color["brightness"]["light_pct"] > 60 and edge["likely_has_text"]:
        clues.append("likely_webpage_or_app")

    # Color alerts
    if color["hue_dominance"]["red_pct"] > 5:
        clues.append("red_elements_present")
    if color["hue_dominance"]["green_pct"] > 5:
        clues.append("green_elements_present")
    if color["hue_dominance"]["orange_pct"] > 5:
        clues.append("orange_elements_present")

    return {
        "clues": clues,
        "best_guess": _best_guess(clues)
    }


def _best_guess(clues):
    """Make best guess about image type from clues."""
    if "likely_code_editor" in clues and "dark_theme" in clues:
        return "代码编辑器/终端截图 (暗色主题)"
    elif "likely_document_or_chat" in clues and "has_ui_chrome" in clues:
        return "应用/聊天界面截图"
    elif "likely_dark_slide_or_diagram" in clues:
        return "深色演示/架构图"
    elif "likely_webpage_or_app" in clues:
        return "网页/应用界面截图"
    elif "has_ui_chrome" in clues:
        return "带UI框架的应用截图"
    return "普通图片/照片"


def find_zones(w, h, pixels):
    """Find distinct colored zones (approximate)."""
    # Simplified: sample grid and group similar colors
    zone_grid = 20  # 20x20 sampling
    cell_w, cell_h = max(1, w // zone_grid), max(1, h // zone_grid)
    zones = []

    for row in range(zone_grid):
        for col in range(zone_grid):
            cell_pixels = []
            for y in range(row * cell_h, min((row + 1) * cell_h, h)):
                for x in range(col * cell_w, min((col + 1) * cell_w, w)):
                    idx = y * w + x
                    if idx < len(pixels):
                        cell_pixels.append(pixels[idx])

            if cell_pixels:
                avg_r = sum(p[0] for p in cell_pixels) / len(cell_pixels)
                avg_g = sum(p[1] for p in cell_pixels) / len(cell_pixels)
                avg_b = sum(p[2] for p in cell_pixels) / len(cell_pixels)
                brightness = (avg_r + avg_g + avg_b) / 3

                # Only record cells with distinct color
                saturation = max(avg_r, avg_g, avg_b) - min(avg_r, avg_g, avg_b)
                if saturation > 30 or brightness < 50 or brightness > 200:
                    zones.append({
                        "row": row, "col": col,
                        "avg_color": f"rgb({int(avg_r)},{int(avg_g)},{int(avg_b)})",
                        "brightness": round(brightness, 1),
                        "saturation": round(saturation, 1)
                    })

    return zones[:50]  # Limit zone count


SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".jfif"}
MAX_DIR_ANALYZE = 200  # cap to avoid runaway memory/time on huge dirs


def summarize(r):
    """Extract key fields into a compact, comparable row."""
    color = r.get("analysis", {}).get("color", {})
    edge = r.get("analysis", {}).get("edge_density", {})
    screen = r.get("analysis", {}).get("screen_type", {})
    dims = r.get("dimensions", {})
    return {
        "file": r.get("file"),
        "width": dims.get("width"),
        "height": dims.get("height"),
        "aspect_ratio": r.get("aspect_ratio"),
        "is_dark_theme": color.get("is_dark_theme"),
        "dominant_brightness": color.get("brightness", {}).get("dominant"),
        "has_text": edge.get("likely_has_text"),
        "screen_type": screen.get("best_guess"),
    }


def analyze_dir(directory, detail="medium"):
    """Analyze all supported images in a directory; return a normalized table.

    Graceful degradation notes:
    - A corrupted / unreadable individual image never aborts the batch. It is
      recorded as a per-file entry with a friendly "corrupted or unreadable"
      error marker plus a running error_count for the whole directory.
    - Very large directories are guarded by an upper analysis cap
      (MAX_DIR_ANALYZE). Once the cap is reached the scan stops early and
      reports partial_processed=True so callers know the result is a deliberate
      truncation, not a silently incomplete scan.
    """
    if not os.path.isdir(directory):
        return {"error": f"Directory not found: {directory}"}
    images = []
    errors = 0
    candidates = 0
    for name in sorted(os.listdir(directory)):
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED_EXTS:
            continue
        candidates += 1
        if len(images) - errors >= MAX_DIR_ANALYZE:
            break
        path = os.path.join(directory, name)
        try:
            r = analyze_image(path, detail)
            images.append(summarize(r))
        except Exception as e:  # noqa: BLE001
            errors += 1
            images.append({
                "file": name,
                "error": "corrupted or unreadable image",
                "detail": str(e),
            })
    result = {
        "mode": "directory_analysis",
        "files_analyzed": len(images) - errors,
        "error_count": errors,
        "candidate_count": candidates,
        "partial_processed": candidates > MAX_DIR_ANALYZE,
        "images": images,
    }
    if result["partial_processed"]:
        result["note"] = (
            f"Directory has {candidates} image candidates; only the first "
            f"{MAX_DIR_ANALYZE} were analyzed to bound memory and time. "
            "Result is a truncated scan, not a full picture."
        )
    if errors:
        result["note"] = (
            f"{errors} corrupted/unreadable file(s) were skipped and reported "
            "per-file; the remaining batch was analyzed normally."
        )
    return result


def compare_images(path_a, path_b):
    """Compare two images and return structural similarity metrics.

    Useful for UI-screenshot regression, chart-variant comparison, or
    verifying two renders are visually identical. Returns similarity_score
    (0-100), mean pixel diff, identical/significant-change ratio, and a
    human-readable verdict.
    """
    if not os.path.exists(path_a):
        return {"error": f"File not found: {path_a}"}
    if not os.path.exists(path_b):
        return {"error": f"File not found: {path_b}"}

    try:
        ga = Image.open(path_a).convert("L").resize((96, 96), Image.LANCZOS)
        gb = Image.open(path_b).convert("L").resize((96, 96), Image.LANCZOS)
        da = Image.open(path_a).size
        db = Image.open(path_b).size
    except Exception as e:  # noqa: BLE001
        return {"error": f"compare failed: {e}"}

    la, lb = list(ga.get_flattened_data()), list(gb.get_flattened_data())
    diffs = [abs(x - y) for x, y in zip(la, lb)]
    mean_diff = sum(diffs) / len(diffs)
    pct_identical = sum(1 for d in diffs if d < 12) / len(diffs) * 100
    pct_significant = sum(1 for d in diffs if d > 32) / len(diffs) * 100
    similarity = max(0.0, 100.0 - mean_diff)
    verdict = "identical" if mean_diff < 1 else "similar" if mean_diff < 30 else "different"

    return {
        "mode": "compare",
        "images": [os.path.basename(path_a), os.path.basename(path_b)],
        "dimensions": {
            "a": {"width": da[0], "height": da[1]},
            "b": {"width": db[0], "height": db[1]},
        },
        "similarity_score": round(similarity, 1),
        "mean_pixel_diff": round(mean_diff, 1),
        "pct_identical_pixels": round(pct_identical, 1),
        "pct_significant_diff": round(pct_significant, 1),
        "verdict": verdict,
    }


if __name__ == "__main__":
    # Parse args: single image | --dir <folder> | --compare <imgA> <imgB>; plus --output/--detail
    image_path = None
    directory = None
    compare_paths = []
    output_path = None
    detail = "medium"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        elif args[i] == "--detail" and i + 1 < len(args):
            detail = args[i + 1]
            i += 2
        elif args[i] == "--dir" and i + 1 < len(args):
            directory = args[i + 1]
            i += 2
        elif args[i] == "--compare" and i + 2 < len(args):
            compare_paths = [args[i + 1], args[i + 2]]
            i += 3
        elif image_path is None:
            image_path = args[i]
            i += 1
        else:
            i += 1

    if not image_path and not directory and not compare_paths:
        print("Usage: python analyze_image.py <image_path | --dir <folder> | --compare <imgA> <imgB>> [--output result.json] [--detail high|medium|low]")
        sys.exit(1)

    if compare_paths:
        result = compare_images(compare_paths[0], compare_paths[1])
    elif directory:
        result = analyze_dir(directory, detail)
    else:
        result = analyze_image(image_path, detail)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ Analysis saved to {output_path}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
