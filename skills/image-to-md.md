# Image to Markdown — Text & Relationship Extraction

Extracts the text **and the relationships between parts of that text** out of one or more images,
and writes a clean Markdown file. This is not flat OCR: tables stay tables, flows become explicit
`A → B` edges, diagram labels map to the parts they annotate, and hierarchy is preserved. Works on a
single image or a batch.

This skill is a generic workspace tool. It is independent of the LLM-wiki project (the wiki has its
own image-synthesis rules baked into its CLAUDE.md); the two share the same philosophy but neither
depends on the other.

---

## Flags

| Flag | Default | What it does |
|------|---------|--------------|
| `--separate` | off (one combined file) | **Write one Markdown file per image** instead of merging the batch into a single file. The default treats a batch as one related source and synthesizes across images (sequence, elaboration, comparison — see STEP 3); `--separate` is the escape hatch for when the images are genuinely **unrelated** and should not be woven into one narrative. STEP 3 may also *suggest* this flag on its own if it finds the images are independent. For a single image the flag is a no-op (you already get one file). |

Equivalent phrasings in a request that mean `--separate`: "keep them separate", "separate files",
"one file per image".

---

## Core principle — one uniform pipeline, no edge-case branches

A single image is just the **N=1 case** of a batch. The flow is always the same:

> resolve inputs to a list of images → extract structure + relationships from each → (if more than
> one) link across images → write **one** Markdown file with a suggested, user-confirmed name.

The single-vs-multiple distinction never forks the processing or the user interaction. It only
changes *what filename is suggested* (see STEP 4). The only true option is the rare "keep them
separate" escape hatch.

---

## STEP 1 — Resolve inputs to a list of images

Accept images presented any of these ways and normalize to an ordered list:

- **Pasted into the Claude Code prompt** — already attached to the conversation; read them directly.
- **A folder path** — enumerate supported image files in that folder (sorted by filename, so page
  order is stable).
- **Explicit file path(s)** — one or many.

Supported formats: PNG, JPG/JPEG, GIF, WEBP, BMP. Ignore non-image files silently if a folder also
contains other content. If no images are found or provided, ask the user for them and stop.

If the user named an output file or said "separate files" in their request, capture that now so you
can skip the corresponding prompt later.

---

## STEP 2 — Extract text AND relationships from each image

**You must open and read each image with the Read tool. Never describe, transcribe, or attribute
content to an image you have not actually opened — guessing from a filename or surrounding context
is fabrication.**

For each image, capture not just the words but how they relate. Use the right representation per
content type:

- **Tables** → reproduce as Markdown tables, preserving rows, columns, and headers.
- **Flows / arrows / pipelines** (flowcharts, diagrams) → list each edge explicitly as
  `Source → Target` (or `Source —label→ Target` when the arrow is labeled), plus a one-line read of
  what the whole flow does. **Read each arrow's direction from its actual arrowheads at both ends —
  never from the diagram's overall flow.** Inspect every connector for a head at each end: a head at
  one end = one-way (`→`); heads at *both* ends = bidirectional (`↔`). Do not let a diagram's
  top-to-bottom or left-to-right layout stand in for inspecting the arrowheads — bidirectional arrows
  (and arrows pointing "upstream" against the expected flow) are easiest to miss exactly when they run
  counter to that flow or are short. A missed second arrowhead silently turns a mutually-reinforcing
  relationship into a one-way one, which changes the meaning.
- **Hierarchies / trees / nested lists** → preserve nesting with indented Markdown lists.
- **Labeled diagrams / annotated screenshots** → a mapping of each label to the part it annotates
  ("**Top-left panel** — shows X"), so the spatial relationship survives as text.
- **Key–value panels / spec sheets / cards** → definition-style lists or a two-column table.
- **Callouts, captions, footnotes, headings** → keep them attached to what they describe, not
  dumped as loose lines.
- **Plain prose** → transcribe verbatim, preserving paragraph and heading structure.

**Legibility discipline:** if any region is too small, blurry, or cut off to read with confidence,
write `[illegible]` (or `[uncertain: best guess "…"]`) at that spot. Never invent text to fill a
gap. Record what you could not read rather than guessing.

---

## STEP 3 — Link across images (batch only)

When there is more than one image, after extracting each individually, identify relationships
*between* them and record them:

- **Sequence / continuation** — image 2 continues a table or list begun in image 1.
- **Elaboration** — one image is a detail/zoom of another.
- **Comparison** — images present parallel alternatives (before/after, option A/B).
- **Independence** — if two images are genuinely unrelated, say so plainly (this is the signal that
  the user may have wanted `--separate`; mention it).

This cross-image synthesis is the main reason a batch defaults to a single file.

---

## STEP 4 — Decide output shape and name

**Shape (default = one file):** Treat the batch as one related source and write **one** Markdown
file. Only produce one file per image if the user explicitly asked to keep them separate (or STEP 3
found the images are unrelated and the user confirms separating them).

**Name — always suggest, always let the user override.** The interaction is identical in every case;
only the suggestion differs:

| Case | Suggested filename |
|------|--------------------|
| Exactly one image | the image's basename (e.g. `dashboard-q3.png` → `dashboard-q3.md`) — keeps source ↔ output matched |
| Multiple images | a thematic slug derived from a summary of the combined content (e.g. `claude-keyboard-shortcuts.md`) |
| User already gave a name | use it; skip the prompt |

Present the suggestion as the default and ask the user to accept or change it (one quick
confirmation). Do the same for the **output location** — default to the source folder (folder input)
or the current working directory (pasted/explicit-path input), suggested and overridable. If the
user's request already specified name and/or location, don't re-ask.

---

## STEP 5 — Write the Markdown file

Use this structure. For a single image, omit the per-image `##` headings and the cross-image section
— it collapses naturally to one body.

**Do not hard-wrap running text.** Write each sentence, paragraph, transcribed passage, table cell, or
list item as **one continuous physical line** and let the editor soft-wrap it. Never insert a newline
in the middle of a running sentence to keep lines short — those breaks are arbitrary, do not mirror
the image, and make the extraction unfaithful and harder to read/diff/grep in raw form. Insert a line
break **only** at a genuine structural boundary (a new paragraph, a new list item, a new table row, a
new heading) or where the *source image itself* breaks the text and that break carries meaning. When
transcribing text verbatim from an image, reproduce its words faithfully on a single line; do not
re-flow it to an arbitrary column width.

**`tool:` model field — name the CURRENT session model, not the system-prompt identity.** Fill the
`(<model…>)` with the model **actually active when you read the images** — the one shown in the
client's status bar / set by the most recent `/model`. The model identity stated in your system prompt
is only the model at session *start*; it goes **stale the instant the user switches model mid-session
with `/model`**, and it does not update. Do not copy that identity string by reflex (it has produced
wrong attributions before). If you cannot confirm the live model with confidence, name your best
estimate and add `(unverified)` rather than asserting a stale identity.

```markdown
---
source_images:
  - <path-or-name-of-image-1>
  - <path-or-name-of-image-2>
extracted: <YYYY-MM-DD HH:mm:ss>
tool: image-to-md (<current session model — see note above>)
---

# <Title — from content, matching the chosen filename>

## <Image 1 name / short descriptor>
<structured extraction: prose, tables, flow edges, label maps — per STEP 2>

## <Image 2 name / short descriptor>
<…>

## Cross-image relationships   ← batch only; omit for a single image
- <sequence / elaboration / comparison notes from STEP 3>

## Extraction notes   ← only if anything was illegible or uncertain
- <what could not be read, and where>
```

---

## STEP 6 — Report

Tell the user: the output file path(s), how many images were processed, what structure types were
found (tables / flows / diagrams / prose), and explicitly list any `[illegible]` regions so they
know what to double-check against the originals. Never present an extraction as complete if parts
were unreadable.

---

## Relationship to neighbouring skills

- **`pdf-to-images`** is the upstream producer: it rasterizes a PDF into numbered PNGs (and, in its
  default *package* mode, a deterministic text-layer `article.md` sidecar — but **not** graphic-layer
  content like arrows). This skill is the vision counterpart that reads those pixels and recovers
  what the text layer misses.
- **The two-pass slide-deck workflow** (the standard way to make a deck wiki-ingestible when slides
  carry graphic-layer cause-effect arrows):
  1. `pdf-to-images --mode images <deck.pdf>` → bare numbered PNGs (use `images` mode because pass 2
     re-reads every image with vision, making the package-mode text transcript redundant).
  2. `image-to-md --separate <images-folder>` → one `.md` per slide, capturing text **and**
     graphic-layer relationships (arrows, tables, labeled diagrams).
  This standardizes processing so no manual hunting for which slides contain directional indicators
  is needed. See the matching section in `pdf-to-images.md`.
