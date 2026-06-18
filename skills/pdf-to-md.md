# PDF to MD — text-only extraction for genuinely graphic-free PDFs

Extracts a PDF's text layer straight to a markdown `article.md` **without rasterizing** — the
efficient path for a PDF that is genuinely pure text (prose, no diagrams, charts, or tables). It
exists so you don't waste a render→vision round-trip on a document that has no graphic-layer content
to recover.

It shares the same engine as `/pdf-to-images` (`pdf-to-images.py`, `--mode md`) and is a **thin
wrapper** over it. The engine — not this skill — owns the routing decision, so the two skills never
call each other.

---

## The one thing that matters: this skill fails safe to rasterizing

A PDF with **no embedded image objects is NOT necessarily pure text.** It can be full of **vector**
arrows, flowcharts, charts, and line-tables — exactly the graphic-layer content the text layer drops
silently. Extracting such a PDF as text-only would produce *plausible-looking but incomplete* output
(e.g. a flowchart's arrows gone, a table's structure flattened) — the failure mode the whole
PDF pipeline is built to prevent.

So the engine runs a **deterministic router** before doing anything. A PDF is "text-safe" — eligible
for text-only extraction — **only if EVERY page** satisfies all three:

1. **no embedded raster images**, AND
2. **near-empty vector drawings** (`page.get_drawings()` at or below a small threshold — diagrams,
   charts, and line-tables exceed it), AND
3. **substantial extractable text** (rules out scanned/image-only pages).

If any page fails any test, the PDF is **not** text-safe and the engine **fails safe: it rasterizes
to images instead** (identical to `/pdf-to-images` default output) and tells you it did, with the
reason. **When in doubt, it renders.** That means even if a user mistakenly runs `/pdf-to-md` on a
slide deck or a diagram-heavy report, no graphic-layer content is lost — they simply get PNGs back
and a note to run the vision pass.

---

## STEP 1 — Resolve inputs

Accept a single PDF path, several PDF paths, or a **folder** (all `*.pdf` in it). If the user gave
none, ask for a path and stop. Capture any stated `--out` location so you don't re-ask.

## STEP 2 — Ensure the engine can run

Same engine as `/pdf-to-images`; it self-installs **PyMuPDF** on first use. Use whichever Python is
available (on this machine `/c/Python314/python`; elsewhere try `python`, then `py -3`, then
`python3`).

## STEP 3 — Run the engine in `md` mode

```bash
python "~/.claude/skills/pdf-to-images.py" --mode md [--out DIR] [--force] <PDF|folder> ...
```

- **Text-safe PDF** → writes `<out>/<slug>/article.md` only (no PNGs), with `## Page N` sections of
  extracted text. The `RESULT:` line shows `"mode": "md"`.
- **Not text-safe** → the engine **fails safe and rasterizes**: you get `<out>/<slug>/0001.png…`
  instead, and the `RESULT:` line carries `"mode": "images"`, `"routed_from": "md"`, and a
  `"fallback_reason"` array (e.g. `"page 3: 24 vector drawings (diagram/chart/line-table risk)"`).
- `--out` defaults to the source PDF's own folder; `<slug>` is the PDF filename slugified.
- Collision guard: the engine refuses to overwrite an existing `article.md` (or PNG set) unless
  `--force` is given; on `status: skipped_exists`, confirm with the user before re-running with
  `--force`.

Parse the `RESULT:`/`RESULT_SUMMARY:` JSON lines — don't eyeball the output tree.

## STEP 4 — Report

Per PDF, tell the user which path the router took:

- **Stayed text-only (`mode: md`):** report the `article.md` path, page count, and that no
  rasterization was needed. Done.
- **Fell back to images (`routed_from: md`):** state plainly that the PDF was **not** pure text —
  give the `fallback_reason` (which page(s) and why) — and that it was rasterized instead. Then point
  the user to the vision pass: run **`/image-to-md`** over the produced PNGs to recover the
  graphic-layer content (this is the standard `/pdf-to-images` → `/image-to-md` two-pass flow). The
  `RESULT_SUMMARY:` `md_fellback_to_images` count tells you how many of a batch fell back.

For wiki use, the produced folder is drop-in for `raw/` once the user prefixes a catalog ID
(`raw/NNNN_<slug>/`), exactly like `/pdf-to-images` output.

---

## When to use which skill

- **`/pdf-to-md`** — you are confident the PDF is **pure prose** (a text report, an article, a
  contract) with no diagrams/charts/tables. Efficient: no images written, no vision pass needed.
- **`/pdf-to-images`** — anything with graphics: slide decks, diagrams, charts, scanned pages, or
  **when in doubt.** It always rasterizes for the downstream vision pass.
- You cannot break things by guessing wrong: `/pdf-to-md` on a graphic PDF fails safe to
  `/pdf-to-images` behavior, and `/pdf-to-images` never does text-only.

## Relationship to neighbouring skills

- **`pdf-to-images`** — the sibling skill and shared engine; the rasterizing path and the default for
  any graphics-bearing PDF. `/pdf-to-md`'s fail-safe routes back to exactly its behavior.
- **`image-to-md`** — the vision pass to run over PNGs when `/pdf-to-md` falls back to images (or
  whenever you rasterize a deck with `/pdf-to-images`).
- **`firecrawl-parse`** — also extracts a PDF's text to markdown; use it for local files when you
  only need the words and don't want the page-level `## Page N` structure or the graphic-layer
  fail-safe this skill provides.
