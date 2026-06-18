# PDF to Images — slide/page rasterizer with text-layer sidecar

Turns one or more PDFs into a self-contained folder per PDF: every page rendered to a numbered
PNG (`0001.png`, `0002.png`, …). The **default is `--mode images`** (bare numbered PNGs) so that
every page is forced through a downstream vision pass and no graphic-layer content is ever silently
lost; opt into `--mode package` to *also* get an `article.md` text sidecar with each page's image
embedded next to its text.

> **Enforcement: this skill always rasterizes.** When invoked as `/pdf-to-images` the skill runs
> the engine in `images` (or `package`) mode — never text-only. The text layer alone drops
> graphic-layer content (arrows, diagrams, charts, line-tables), which produces *plausible-looking
> but incomplete* extraction — the worst failure mode. If a PDF is genuinely pure text (prose, no
> diagrams/tables/charts) and you want to skip rasterization for efficiency, that is the separate
> **`/pdf-to-md`** skill — which has a deterministic fail-safe that renders anyway if it detects any
> graphic-layer content. See "What happens for different PDF types" below.

This is a **general-purpose tool** — independent of any wiki: it assigns no
catalog IDs and knows nothing about any `raw/` folder. It produces a clean package that a human (or
a wiki's acquire step) can drop into `raw/` and rename to `NNNN_<slug>` *there*. Keeping ID
assignment out of this skill preserves the wiki's "assign once, freeze forever" contract.

The actual work is done by the companion engine **`pdf-to-images.py`** (same folder as this file).
It is deterministic — no per-image LLM judgment happens here; that judgment (illustrative vs
decorative, relationship extraction) belongs to the downstream wiki ingest, which reads the PNGs
with vision later.

---

## Why images, and why 200 DPI (the reasoning baked into the defaults)

- A vision LLM **downsamples** every image to ~1568 px on the long edge before it sees it — about
  **150 DPI** for a Letter page. So 150 DPI is the *lossless floor* for the model; **200** is the
  default (a small margin for a human zooming the rendered page); **300** is ~4× the disk of 150
  for **no** LLM gain. Don't raise DPI to fix tiny/dense text — the model downsamples anyway; the
  text layer in `article.md` is what rescues small print.
- PNG, not JPEG: slides are sharp text on flat color, where PNG is lossless and crisp — the right
  choice for the **extraction** pass (maximum fidelity for vision).
- Rendering is **orientation-agnostic** (renders each page at the DPI against its own size), so
  portrait and landscape decks need no special handling.

**Two-stage image lifecycle (extraction vs. archive).** The 200 DPI PNGs this skill emits are for the
*extraction* pass (vision text/relationship extraction). They are **transient working files** — large
and no longer needed once extraction is done. If the pages are being **archived/deposited** somewhere
they'll only be viewed (e.g. a wiki's `raw/` folder), re-render them small — **JPEG at ~150 DPI** —
straight from the PDF (one clean generation, not by recompressing the PNGs), which shrinks disk ~5–10×
while staying perfectly readable on screen. Keep the **original PDF as the master** fidelity fallback.
Note a PDF cannot be embedded as an inline image in markdown (`![](x.pdf)` yields only a click-to-open
link), so the lightweight JPEGs are what render inline; the PDF is reference-on-demand. (In the LLM-wiki
workflow this is codified in the schema's *Images and assets* rule 8 — `raw/_master/<file>.pdf` plus
per-page JPEGs.)

---

## STEP 1 — Resolve inputs

Accept any of: a single PDF path, several PDF paths, or a **folder** (all `*.pdf` in it, sorted).
The engine takes them as positional args and expands folders itself. If the user gave none, ask
for a path and stop.

Capture any options the user stated in their request so you don't re-ask: DPI, `images`-only mode,
output location.

## STEP 2 — Ensure the engine can run

The engine self-installs **PyMuPDF** on first use, so normally you just run it. Use whichever Python
launcher is available — `python`, or `py -3`, or `python3`. PyMuPDF needs **no** external binaries
(no Ghostscript/poppler).

## STEP 3 — Run the engine

```bash
python "~/.claude/skills/pdf-to-images.py" [--dpi 200] [--mode images|package] [--out DIR] [--force] <PDF|folder> ...
```

- **`--mode images`** (DEFAULT): per PDF → `<out>/<slug>/0001.png…` (numbered PNGs only, no `article.md`)
- **`--mode package`**: per PDF → `<out>/<slug>/article.md` + `<out>/<slug>/images/0001.png…` (explicit opt-in for the text sidecar)
- (The engine also has a `--mode md` for text-only extraction; do not call it from this skill — it belongs to `/pdf-to-md`.)
- **`--out`** defaults to the source PDF's own folder; `<slug>` is derived from the PDF filename.
- The engine **refuses to overwrite** a folder that already holds PNGs unless `--force` is given —
  if you hit `status: skipped_exists`, confirm with the user before re-running with `--force`.

Each PDF prints a `RESULT:{…}` JSON line; the run ends with `RESULT_SUMMARY:{…}`. Parse these for
the report — don't eyeball the PNG list.

## STEP 4 — Report

Per PDF, tell the user: output folder path, page/image count, DPI, orientation, whether a text
layer was found, and **how many pages had no text** (those rely on the image alone). Give the total
on-disk size so the disk cost is visible. Surface any `error` or `skipped_exists` results
explicitly. For wiki use, remind the user the folder is drop-in for `raw/` once they prefix the
catalog ID (`raw/NNNN_<slug>/`).

---

## Default mode and the "sidecar", in one place

- **The default is `--mode images`.** Running the skill with **no** `--mode` flag gives you bare
  numbered PNGs — *not* the text sidecar. Pass `--mode package` explicitly when you also want the
  free `article.md` transcript. (This default was deliberately set to images so the text layer can
  never silently substitute for the vision pass; this is the canonical statement.)
- **What the `article.md` "sidecar" is.** A *sidecar* is a companion file written alongside the
  images. Here it is `article.md`: the PDF's own embedded **text layer**, extracted
  **deterministically** (no OCR, no vision, no LLM — the same text you'd get by selecting and copying
  in a PDF viewer), with **each page's PNG embedded next to that page's text**. So package mode =
  *images PLUS a free text transcript of the slides*, interleaved. `images` mode just drops
  `article.md` and leaves the bare numbered PNGs.
- **The catch with the text layer:** it captures only what is stored *as text*. Anything living in
  the **graphic layer** — diagram arrows, cause-effect flows, charts, text baked into a figure — is
  invisible to it. That is what the vision pass (`/image-to-md`) is for. This is exactly why the text
  sidecar is never the default and is never used *instead of* rasterizing.

## What happens for different PDF types

Because the engine rasterizes **pages** (not embedded image objects), you always get one PNG per
page regardless of what the PDF contains. What varies is how useful the run is and which tool fits:

| PDF type | What this skill produces | Note |
|----------|--------------------------|------|
| **Born-digital with diagrams/charts/tables** (typical slide deck) | one PNG per page → feed to `/image-to-md` (vision) | the main case; vision recovers graphic-layer arrows/labels the text layer can't see |
| **Scanned / image-only** (each page *is* a photo) | one PNG per page; `has_text_layer: false`, every page in `pages_without_text` | rasterizing + vision is the *only* way to get the content — the text layer rescues nothing |
| **Pure text, no graphics** (prose, no diagrams/tables) | one PNG per page (still) | rasterizing→vision works but is wasteful here — prefer **`/pdf-to-md`**, which extracts the text directly and skips the round-trip |

A "PDF with no embedded images" is **not** the same as "pure text": a zero-image PDF can still be
full of vector arrows, diagrams, charts, and line-tables. Routing decisions must hinge on
graphic-layer *content*, not on whether image objects exist — which is exactly what `/pdf-to-md`'s
fail-safe router checks (`page.get_drawings()` near-empty, no embedded images, substantial text).

## Pairing with `/image-to-md` — the two-pass slide-deck workflow

The standard way to turn a slide deck into wiki-ingestible Markdown, especially when slides carry
**graphic-layer cause-effect arrows** (which no text layer can see) and manually triaging which
slides have them would be too cumbersome:

1. **Pass 1 — rasterize:** `pdf-to-images <deck.pdf>` → bare numbered PNGs, one per page (this is the
   default mode now). **Pass 2 re-reads every image with vision anyway**, so the package-mode
   `article.md` text transcript would be redundant here.
2. **Pass 2 — vision extraction:** `image-to-md --separate <images-folder>` → **one `.md` per slide**,
   capturing text content **and** the graphic-layer relationships (arrows read from their actual
   arrowheads, tables, labeled diagrams). See `--separate` in that skill.

This standardizes processing — every slide goes through the same vision pass, so no manual hunting
for which slides contain directional indicators. Do **not** shortcut a real slide deck with the text
layer alone: a deck that *looks* "mostly bullet text" routinely hides a few cause-effect arrows or a
line-table that the text layer drops silently. The only place text-only extraction is appropriate is
a genuinely graphic-free PDF, and that is what **`/pdf-to-md`** is for — with a fail-safe that
rasterizes anyway the moment it detects graphic-layer content.

## Relationship to neighbouring skills

- **`firecrawl-parse`** extracts a PDF's *text* to markdown but does **not** rasterize pages — use
  it when you only need the words. This skill is the image-producing counterpart (and still emits
  the text layer as a sidecar).
- **`image-to-md`** goes the other direction: it reads existing images with vision and writes a
  structured markdown extraction. Pair them via the two-pass workflow above when slides carry
  graphic-layer content (arrows, diagrams) that a text layer cannot capture.
- **`pdf-to-md`** is the sibling skill for the *opposite* case: a genuinely text-only PDF (no
  diagrams/charts/tables), where rasterizing then re-reading with vision is wasted work. It shares
  this engine (`--mode md`) and has a deterministic fail-safe — if it detects any graphic-layer
  content it renders to images instead, routing the job back here. Reach for `/pdf-to-md` only when
  you are confident the PDF is pure prose; when in doubt, use `/pdf-to-images` (this skill).
