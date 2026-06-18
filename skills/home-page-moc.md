# Home-page MOC — (re)generate a wiki's Obsidian Map of Content

Regenerates `<wiki-root>/home-page.md`, an Obsidian **Map of Content**: an A–Z + Numerals index of
every wiki page with a top jump-bar, so a reader opens one page and drills into any topic. The home
page is a **build artifact** — it is regenerated, never hand-edited.

Generic across any wiki using the schema's `wiki/{concepts,tools,workflows,setup-guides,
causal-chains,metaphors}/` layout. Deterministic, stdlib-only (no dependencies). The engine is
`home-page-moc.py` in this folder.

## When to run it

- As the **final step of every ingest** (the wiki schema's Ingest workflow calls for this), so the
  home page never drifts from the page set.
- On demand any time pages were added/renamed/removed.

## STEP 1 — Run the generator

```bash
python "~/.claude/skills/home-page-moc.py" --root <wiki-root> [--title "..."]
```

- `--root` is the wiki root (the folder containing `wiki/`, `index.md`, `log.md`). Defaults to the
  current directory.
- `--title` overrides the H1. By default the title is derived from `index.md`'s H1 (e.g.
  `# FDN Wiki — Index` → `# FDN Wiki — Map of Content`).
- Use whichever Python is available (on this machine `/c/Python314/python`; elsewhere `python`, then
  `py -3`, then `python3`).

It prints one `RESULT:{…}` JSON line with the output path and counts (`pages`, `sections`,
`mirrors`). Parse that — don't eyeball the file.

## STEP 2 — Report

Tell the user the `home-page.md` path and the page/section counts. If `mirrors` is non-zero, note how
many `-vs-` mirror entries were emitted. The file is committed with the wiki (like `index.md`).

---

## What it produces (the rules, in one place)

- **Sections:** one per first character — `A`–`Z` (uppercased), then a `Numerals` section for slugs
  starting with a digit. **Empty letters are skipped.** A jump-bar of Obsidian heading links
  (`[[#A|A]] · … · [[#Numerals|#]]`) sits at the top so no scrolling is needed to reach a letter.
- **Entries:** every `wiki/**/*.md` page as `[[slug]] (singular-category)`, where the category is the
  parent folder singularized (`concepts`→`concept`, `tools`→`tool`, `workflows`→`workflow`,
  `setup-guides`→`setup-guide`, `causal-chains`→`causal-chain`, `metaphors`→`metaphor`).
- **Sort:** natural within each section, so `5r-protocol` < `8-ohdg` < `25-bricks-analogy` (not the
  lexical `25` < `5` < `8`).
- **`-vs-` mirror entries:** a page may declare a `moc_mirror: <slug>` frontmatter field naming the
  swapped-operand form of a `-vs-` slug. The generator then emits, under the mirror's own letter, a
  **plain-text** pointer `mirror-slug (see [[real-slug]])` (only the `(see …)` is a link). Example:
  on `functional-vs-conventional-paradigm.md`, `moc_mirror: conventional-vs-functional-paradigm`
  yields, under **C**, `conventional-vs-functional-paradigm (see [[functional-vs-conventional-paradigm]])`,
  while the real page keeps its normal `(concept)` entry under **F**. The mirror spelling **cannot be
  derived by string-swapping** (a shared trailing noun like "paradigm" must stay pinned), so it must
  be declared on the page; the generator never invents it.

## Gotchas

- **Do not hand-edit `home-page.md`** — it carries an `AUTO-GENERATED` banner and is overwritten on
  every run. To change an entry, fix the underlying page (or its `moc_mirror` field) and regenerate.
- A new `-vs-` page needs a `moc_mirror:` line added by hand once (at ingest time); without it, only
  the real-letter entry appears and no mirror is emitted.
