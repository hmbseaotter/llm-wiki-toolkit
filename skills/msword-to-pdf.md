# MS Word to PDF — bridge Word/ODF documents into the PDF pipeline

Converts `.doc` / `.docx` (and `.rtf` / `.odt`) documents to **PDF**, so a Word source can flow
through the **same** extraction pipeline as a PDF: `/pdf-to-images` (rasterize → vision) for
documents with graphics, or `/pdf-to-md` (text-only, with a fail-safe) for genuinely pure-text ones.

There is deliberately **no parallel Word rasterizer.** A Word document can carry graphic-layer
content — embedded images, diagrams, charts, drawn shapes/arrows, line-tables — that a text-only
extraction silently drops. Going through PDF means the completeness guarantees we built for PDFs
(images-default, the `/pdf-to-md` graphic-content router) apply to Word sources for free.

The engine is `msword-to-pdf.py` in this folder. Backend: **LibreOffice headless**
(`soffice --convert-to pdf`). MS Word itself is not required.

## Dependency — LibreOffice must be installed

This skill requires LibreOffice. If `soffice` is missing the engine exits with code 3 and the install
command. To install (run in an **elevated** terminal so the MSI finalizes cleanly):

```
winget install --id TheDocumentFoundation.LibreOffice -e --silent --accept-package-agreements --accept-source-agreements
```

(If a prior install left LibreOffice misbehaving, `winget uninstall --id TheDocumentFoundation.LibreOffice -e`
then reinstall, elevated.)

## STEP 1 — Resolve inputs

Accept a single document path, several paths, or a **folder** (all `.doc/.docx/.rtf/.odt` in it). If
the user gave none, ask for a path and stop. Capture any stated `--out` location.

## STEP 2 — Run the converter

```bash
python "~/.claude/skills/msword-to-pdf.py" [--out DIR] [--force] <doc|folder> ...
```

- Output PDFs land next to each source (or in `--out`); the PDF is named from the source filename.
- Collision guard: an existing `<name>.pdf` is not overwritten unless `--force` is given
  (`status: skipped_exists`) — confirm with the user before forcing.
- Use whichever Python launcher is available — `python`, or `py -3`, or `python3`.

Each `RESULT:{…}` line gives the output PDF path; the `RESULT_SUMMARY:` gives counts and the resolved
`soffice` path. Parse these — don't eyeball the folder. (A benign LibreOffice stderr warning,
"Could not find platform independent libraries", does not indicate failure — the engine judges
success by whether the PDF was actually written, not by exit code.)

## STEP 3 — Route the PDF onward (the important step)

A converted Word document is now just a PDF — hand it to the PDF pipeline. **Default to the image
route**, because most Word documents that are worth ingesting carry figures/tables:

- **Has any graphics** (embedded images, diagrams, charts, or even tables drawn as lines): run
  `/pdf-to-images` (its default `images` mode) → numbered PNGs → then `/image-to-md` for the vision
  extraction. This is the path for the typical mixed text+figures document.
- **Genuinely pure text** (prose only — rare for a doc you'd rasterize): run `/pdf-to-md`. Its
  deterministic router double-checks and **fails safe to images** if it finds graphic-layer content,
  so you cannot lose figures by guessing wrong.
- **When in doubt, use `/pdf-to-images`.**

## STEP 4 — Report

Per document: the source, the produced PDF path and page-equivalent size, and which onward route you
took (and why). For wiki use, the resulting package (PNGs or text `article.md`) is drop-in for `raw/`
once the user prefixes a catalog ID (`raw/NNNN_<slug>/`) — identical to a natively-PDF source. Keep
the original Word file as the master if the user wants full fidelity (analogous to the PDF master
rule in the wiki's Images-and-assets schema).

## Relationship to neighbouring skills

- **`pdf-to-images` / `pdf-to-md`** — the downstream pipeline this skill feeds; all the routing and
  completeness fail-safes live there.
- **`image-to-md`** — the vision pass over the PNGs for any graphics-bearing document.
- **`firecrawl-parse`** — can extract a Word file's *text* to markdown directly, no LibreOffice. Use
  it only when the document is known to be pure prose and you accept that any embedded
  figures/diagrams are dropped. For completeness ("never silently lose graphic content"), prefer this
  skill → PDF → image+vision route.
