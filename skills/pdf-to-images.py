#!/usr/bin/env python3
"""
pdf-to-images engine — rasterize every page of one or more PDFs to numbered PNGs,
optionally packaged with an article.md sidecar built from the PDF's text layer, OR
(text-safe PDFs only) extract straight to markdown with no rasterization.

This is a generic transform. It assigns NO wiki catalog IDs and knows nothing about
any wiki; it produces a self-contained folder per PDF that a human (or a wiki acquire
step) can drop into raw/ and rename to NNNN_<slug> there.

Usage:
    python pdf-to-images.py [options] <PDF | folder> [<PDF | folder> ...]

Options:
    --dpi N            Render resolution (default 200). 150 = lossless for a vision LLM
                       (it downsamples to ~1568px long edge anyway); 300 ~= 4x the disk
                       of 150 for no LLM gain, only human-zoom margin.
    --mode MODE        images (DEFAULT): <slug>/0001.png...  (numbered PNGs only)
                       package:          <slug>/article.md + <slug>/images/0001.png...
                       md:               <slug>/article.md (text-only, NO PNGs) — but ONLY
                                         if the PDF passes the deterministic text-safe
                                         router below; otherwise it FAILS SAFE and renders
                                         to images (so graphic-layer content is never lost).
    --out DIR          Where to create the per-PDF output folder(s).
                       Default: alongside each source PDF.
    --force            Overwrite an existing non-empty output folder.

Why images is the default: package mode's article.md is a TEXT-LAYER-ONLY transcript. It
captures nothing from the graphic layer — diagram arrows, cause-effect flows, charts, and
text baked into figures are invisible to it. Defaulting to images forces every page through
a downstream vision pass (e.g. /image-to-md), so no graphic-layer content is silently lost.
Pass --mode package explicitly only when you knowingly want the free text sidecar too.

The text-safe router (used by --mode md): a PDF is "text-safe" — safe to extract as
markdown WITHOUT rasterizing — ONLY if EVERY page has (a) no embedded raster images,
(b) near-empty vector drawings (no diagrams / charts / line-tables), AND (c) substantial
extractable text. "Has no embedded images" is NOT sufficient: a PDF with zero image objects
can still be full of vector arrows/diagrams/line-tables, which the text layer drops. Any page
failing any test makes the whole PDF not text-safe, and md mode then fails safe to rendering.

Output is orientation-agnostic: each page renders at the requested DPI against its own
page size, so portrait and landscape decks are both handled with no special-casing.

Prints one JSON object per processed PDF (prefixed RESULT:) and a final RESULT_SUMMARY:
line, so the calling agent can report exact paths, counts and text-layer status.
"""
import sys, os, re, json, subprocess, argparse, datetime


def ensure_pymupdf():
    try:
        import fitz  # noqa
        return
    except ImportError:
        print("pymupdf not found; installing...", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pymupdf"],
                       check=True)


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "document"


def resolve_inputs(paths):
    pdfs = []
    for p in paths:
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                if fn.lower().endswith(".pdf"):
                    pdfs.append(os.path.join(p, fn))
        elif os.path.isfile(p) and p.lower().endswith(".pdf"):
            pdfs.append(p)
        else:
            print(f"skip (not a PDF or folder): {p}", file=sys.stderr)
    # de-dup preserving order
    seen, out = set(), []
    for p in pdfs:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap)
            out.append(ap)
    return out


def classify_pdf(doc, draw_threshold=3, min_chars=100):
    """Deterministic text-safe router.

    Returns (text_safe: bool, reasons: list[str]). A PDF is text-safe — safe to extract as
    markdown WITHOUT rasterizing — ONLY if EVERY page has no embedded raster images, a
    near-empty vector-drawing count (diagrams/charts/line-tables exceed the threshold), and
    substantial extractable text. The discriminator is deliberately NOT "does the PDF have
    images": a zero-image PDF full of vector arrows/diagrams/line-tables would be misrouted to
    text-only and silently lose that graphic-layer content. Fail-safe by design — any page that
    trips any test makes the whole PDF not text-safe, so md mode renders instead.
    """
    reasons = []
    for i, page in enumerate(doc, start=1):
        imgs = len(page.get_images(full=False))
        draws = len(page.get_drawings())
        chars = len(page.get_text("text").strip())
        if imgs > 0:
            reasons.append(f"page {i}: {imgs} embedded raster image(s)")
        if draws > draw_threshold:
            reasons.append(f"page {i}: {draws} vector drawings (diagram/chart/line-table risk)")
        if chars < min_chars:
            reasons.append(f"page {i}: only {chars} extractable chars (image-only/scanned)")
    return (len(reasons) == 0), reasons


def _dir_size(d):
    total = 0
    for root, _, files in os.walk(d):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def render_pages(doc, images_dir, dpi):
    """Rasterize every page to images_dir/NNNN.png; return (page_texts, pages_with_text, width)."""
    n = doc.page_count
    width = len(str(n)) if n >= 10000 else 4  # 4-digit default, widen only past 9999
    page_texts, pages_with_text = [], 0
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=dpi)
        pix.save(os.path.join(images_dir, f"{i:0{width}d}.png"))
        txt = page.get_text("text").strip()
        if txt:
            pages_with_text += 1
        page_texts.append(txt)
    return page_texts, pages_with_text, width


def process_pdf(pdf_path, dpi, mode, out_root, force):
    import fitz
    src_name = os.path.basename(pdf_path)
    slug = slugify(os.path.splitext(src_name)[0])
    base = out_root if out_root else os.path.dirname(pdf_path)
    pkg_dir = os.path.join(base, slug)

    doc = fitz.open(pdf_path)
    n = doc.page_count

    # ---- md mode: deterministic router (text-only, else FAIL-SAFE render) ----
    fell_back, fallback_reason = False, []
    if mode == "md":
        text_safe, reasons = classify_pdf(doc)
        if text_safe:
            md_path = os.path.join(pkg_dir, "article.md")
            if os.path.isfile(md_path) and not force:
                return {"pdf": pdf_path, "status": "skipped_exists", "output": pkg_dir}
            os.makedirs(pkg_dir, exist_ok=True)
            page_texts = [p.get_text("text").strip() for p in doc]
            write_md_only(pkg_dir, src_name, n, page_texts)
            return {
                "pdf": pdf_path, "status": "ok", "mode": "md", "output": pkg_dir,
                "pages": n, "orientation": orientation(doc),
                "has_text_layer": True, "pages_without_text": 0,
                "size_mb": round(_dir_size(pkg_dir) / (1024 * 1024), 1),
            }
        # not text-safe -> fall through to the render path, flagged
        mode, fell_back, fallback_reason = "images", True, reasons

    images_dir = os.path.join(pkg_dir, "images") if mode == "package" else pkg_dir

    # collision guard
    if os.path.isdir(images_dir) and any(
        f.lower().endswith(".png") for f in os.listdir(images_dir)
    ) and not force:
        return {"pdf": pdf_path, "status": "skipped_exists", "output": pkg_dir}

    os.makedirs(images_dir, exist_ok=True)
    page_texts, pages_with_text, width = render_pages(doc, images_dir, dpi)
    has_text_layer = sum(len(t) for t in page_texts) > 200

    if mode == "package":
        write_article_md(pkg_dir, src_name, n, dpi, page_texts, width, has_text_layer)

    result = {
        "pdf": pdf_path,
        "status": "ok",
        "mode": mode,
        "output": pkg_dir,
        "pages": n,
        "dpi": dpi,
        "orientation": orientation(doc),
        "has_text_layer": has_text_layer,
        "pages_without_text": n - pages_with_text,
        "size_mb": round(_dir_size(pkg_dir) / (1024 * 1024), 1),
    }
    if fell_back:
        # md was requested but the router found graphic-layer content; rendered instead.
        result["routed_from"] = "md"
        result["fallback_reason"] = fallback_reason
    return result


def orientation(doc):
    r = doc[0].rect
    return "landscape" if r.width >= r.height else "portrait"


def write_article_md(pkg_dir, src_name, n, dpi, page_texts, width, has_text_layer):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "---",
        f"source_pdf: {src_name}",
        f"pages: {n}",
        f"rendered_dpi: {dpi}",
        f"has_text_layer: {str(has_text_layer).lower()}",
        f"tool: pdf-to-images",
        f"extracted: {ts}",
        "---",
        "",
        f"# {os.path.splitext(src_name)[0]}",
        "",
    ]
    for i, txt in enumerate(page_texts, start=1):
        img = f"images/{i:0{width}d}.png"
        lines.append(f"## Slide {i}")
        lines.append("")
        lines.append(f"![Slide {i}]({img})")
        lines.append("")
        if txt:
            lines.append(txt)
        else:
            lines.append("*(no text layer on this page — see image)*")
        lines.append("")
    with open(os.path.join(pkg_dir, "article.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def write_md_only(pkg_dir, src_name, n, page_texts):
    """Text-only article.md (no PNGs, no image embeds) for a PDF that passed the text-safe router."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "---",
        f"source_pdf: {src_name}",
        f"pages: {n}",
        f"has_text_layer: true",
        f"tool: pdf-to-md",
        f"mode: text-only (no rasterization; PDF passed the text-safe router)",
        f"extracted: {ts}",
        "---",
        "",
        f"# {os.path.splitext(src_name)[0]}",
        "",
    ]
    for i, txt in enumerate(page_texts, start=1):
        lines.append(f"## Page {i}")
        lines.append("")
        lines.append(txt if txt else "*(no extractable text on this page)*")
        lines.append("")
    with open(os.path.join(pkg_dir, "article.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--mode", choices=["images", "package", "md"], default="images")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ensure_pymupdf()
    pdfs = resolve_inputs(args.inputs)
    if not pdfs:
        print("No PDF inputs resolved.", file=sys.stderr)
        sys.exit(2)

    results = []
    for pdf in pdfs:
        try:
            r = process_pdf(pdf, args.dpi, args.mode, args.out, args.force)
        except Exception as e:
            r = {"pdf": pdf, "status": "error", "error": str(e)}
        results.append(r)
        # ascii-safe single-line result for the agent
        print("RESULT:" + json.dumps(r, ensure_ascii=True))

    print("RESULT_SUMMARY:" + json.dumps({
        "pdf_count": len(pdfs),
        "ok": sum(1 for r in results if r.get("status") == "ok"),
        "skipped": sum(1 for r in results if r.get("status") == "skipped_exists"),
        "errors": sum(1 for r in results if r.get("status") == "error"),
        "md_fellback_to_images": sum(1 for r in results if r.get("routed_from") == "md"),
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
