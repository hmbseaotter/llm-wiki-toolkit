#!/usr/bin/env python3
"""msword-to-pdf engine — convert MS Word (and other LibreOffice-readable) documents to PDF.

The PDF is a bridge into the existing PDF pipeline: a Word document can carry graphic-layer content
(embedded images, diagrams, charts, drawn shapes/arrows, line-tables) that a text-only extraction
silently drops. Converting to PDF and then routing through pdf-to-images (rasterize -> vision) or
pdf-to-md (text-safe, with a fail-safe to rendering) guarantees that graphic content is never lost,
and reuses ONE pipeline for both Word and PDF sources — no parallel Word-rasterizer.

Backend: LibreOffice headless (`soffice --convert-to pdf`). Requires LibreOffice installed
(winget install --id TheDocumentFoundation.LibreOffice). MS Word itself is NOT required.

Usage:
    python msword-to-pdf.py [--out DIR] [--force] <doc | folder> ...

Accepts .doc .docx .rtf .odt (anything LibreOffice Writer opens). A folder expands to all such files
in it. Output PDFs land next to each source (or in --out). Prints one RESULT:{...} JSON line per
file and a final RESULT_SUMMARY:, so the caller can report exact paths and route each PDF onward.
"""
import sys, os, json, glob, argparse, subprocess, tempfile, shutil
from pathlib import Path

EXTS = (".doc", ".docx", ".rtf", ".odt")


def find_soffice():
    for name in ("soffice", "soffice.exe", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice", "/usr/bin/libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if os.path.isfile(p):
            return p
    return None


def resolve_inputs(paths):
    docs = []
    for p in paths:
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                if fn.lower().endswith(EXTS):
                    docs.append(os.path.join(p, fn))
        elif os.path.isfile(p) and p.lower().endswith(EXTS):
            docs.append(p)
        else:
            print(f"skip (not a Word/ODF doc or folder): {p}", file=sys.stderr)
    seen, out = set(), []
    for d in docs:
        ap = os.path.abspath(d)
        if ap not in seen:
            seen.add(ap)
            out.append(ap)
    return out


def convert_one(soffice, src, out_root, force, profile_url):
    base = os.path.abspath(out_root) if out_root else os.path.dirname(src)
    os.makedirs(base, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    dest = os.path.join(base, stem + ".pdf")
    if os.path.isfile(dest) and not force:
        return {"src": src, "status": "skipped_exists", "output": dest}
    cmd = [soffice, "--headless", f"-env:UserInstallation={profile_url}",
           "--convert-to", "pdf", "--outdir", base, src]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"src": src, "status": "error", "error": "soffice timed out (300s)"}
    # Decide success by the artifact, not the exit code: LibreOffice prints a benign
    # "Could not find platform independent libraries" warning to stderr on some builds while
    # still producing the PDF, so only the file's existence is authoritative.
    if not os.path.isfile(dest):
        return {"src": src, "status": "error",
                "error": (r.stderr or r.stdout or "no PDF produced").strip()[-400:]}
    return {"src": src, "status": "ok", "output": dest,
            "size_mb": round(os.path.getsize(dest) / (1024 * 1024), 1)}


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    soffice = find_soffice()
    if not soffice:
        print("LibreOffice (soffice) not found. Install it:\n"
              "  winget install --id TheDocumentFoundation.LibreOffice -e "
              "--accept-package-agreements --accept-source-agreements", file=sys.stderr)
        sys.exit(3)

    docs = resolve_inputs(args.inputs)
    if not docs:
        print("No .doc/.docx/.rtf/.odt inputs resolved.", file=sys.stderr)
        sys.exit(2)

    # One isolated LibreOffice profile per run, in a real temp dir: avoids clobbering the user's
    # GUI profile and the "soffice is already running" conflict. Must be a file:// URI; Path.as_uri()
    # produces the correct form on Windows (file:///C:/...) and POSIX (file:///tmp/...).
    profile_dir = tempfile.mkdtemp(prefix="lo_msword_")
    profile_url = Path(profile_dir).as_uri()
    try:
        results = []
        for d in docs:
            r = convert_one(soffice, d, args.out, args.force, profile_url)
            results.append(r)
            print("RESULT:" + json.dumps(r, ensure_ascii=True))
        print("RESULT_SUMMARY:" + json.dumps({
            "doc_count": len(docs),
            "ok": sum(1 for r in results if r.get("status") == "ok"),
            "skipped": sum(1 for r in results if r.get("status") == "skipped_exists"),
            "errors": sum(1 for r in results if r.get("status") == "error"),
            "soffice": soffice,
        }, ensure_ascii=True))
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
