# Wiki compile — build deferred causal-chains + lint + regen MOC (the finishing step)

The closing step that makes a round of changes to an LLM wiki — any wiki built on the
`compounding-llm-wiki` schema (its `CLAUDE.md`) — **fully usable**. Ingestion runs on a cheaper model
that *defers* the heavy reasoning — it logs `Causal-chain candidates` in `log.md` instead of building
them — and lint is periodic. This skill drains that backlog: it **compiles** the synthesized layer
(builds the warranted `causal-chain` pages), **lints** the whole wiki, and **regenerates** the MOC.

The schema's own framing: *"knowledge is compiled once, kept current, and gets richer with every
source."* This is that compile.

**Run it after a round of ingestion OR after manual Obsidian edits** — it is trigger-agnostic. It is
also **safe to run anytime**: STEP 0 is a cheap, model-free dirty-check that exits before spending any
Opus reasoning if there is nothing to compile.

## Model

Causal-chain construction and lint are reasoning-heavy — the schema routes them to **`claude-opus-4-8`**.
- If the current session is already on Opus, run inline (Model-selection routing rule 3).
- If not, dispatch the build+lint work to a subagent with `model: claude-opus-4-8`, or tell the user
  to `/model` up. Never run the synthesis/lint on a model chosen only for ingestion.
- STEP 0 (the dirty-check) is pure shell — run it on any model.

---

## STEP 0 — Dirty-check gate (model-free; exit early if idle)

Run from the wiki root (the folder with `wiki/`, `index.md`, `log.md`). Decide whether there is
anything to compile **before** invoking any Opus reasoning. There is work to do if **any** of:

1. **Unbuilt causal-chain candidates** — `log.md` has `Causal-chain candidates` / `Candidate causal
   chains` entries logged *after* the most recent `## […] causal-chain |` or `## […] compile |` entry.
2. **Lint deltas** (cheap shell checks):
   - missing pages: `comm -23 <(grep -rhoE '\[\[[^]#|]+' wiki index.md | sed 's/^\[\[//' | grep -v '^raw/' | sort -u) <(find wiki -name '*.md' -exec basename {} .md \; | sort -u)` — compare against the known-accepted forward-link set recorded in the last compile/lint log entry; only *new* ones count.
   - stale pending-pointers: any `*(page pending — closest coverage: …)*` whose wanted slug now has a file.
   - MOC drift: re-run the MOC generator (deterministic/idempotent), then test with
     `git diff --ignore-all-space --quiet home-page.md` — a **non-zero exit means real content drift**
     (the MOC was stale). Do **not** judge drift with plain `git status`: on Windows the generator
     writes LF while the repo normalizes to CRLF, so `git status` reports `home-page.md` as modified on
     line endings alone — a false positive that would trigger a needless compile. Compare content,
     ignoring whitespace/line-endings.
3. **Working-tree changes** to `wiki/` or `index.md` (manual Obsidian edits) — `git status --short
   wiki/ index.md` plus any uncommitted/committed-since-last-compile changes via `git diff`.

If **none** apply → print `nothing to compile (wiki is current)` and **stop**. Do not build, do not
spend Opus. Report that to the user.

**Classify the dirty reason and scope the expensive work to the delta — this is the empty-run guard.**
The model-free checks above reliably catch *structural* drift (new candidates, new orphans/missing
links, malformed directions, MOC drift) whether or not the edit was committed. What they cannot catch
cheaply is *semantic* manual change — a hand-added causal relationship that should become a chain, or a
newly introduced contradiction; detecting those *is* the Opus reasoning being gated. So:

- Run the **cheap, state-based work always** when dirty: lint structural checks + MOC regen (no Opus).
- Run the **expensive Opus reasoning (causal-chain construction, contradiction sweep) only over the
  delta**: the new `log.md` candidates **plus** the set of pages in `git diff` since the last compile.
  Do **not** re-reason the whole wiki for a small edit — this is what stops a prose-only edit from
  triggering a costly empty run (the delta-set is empty → near-zero cost).
- If the wiki is dirty **only** because of working-tree edits with no new candidates and no structural
  delta (e.g. a typo fix), say so and run lint + MOC reconcile only.
- Edge case — committed, prose-looking edits that secretly added causal content cannot be detected
  cheaply. If the only signal is changed files with no structural delta, **nudge the user**: "no
  structural deltas since the last compile; if you added new causal relationships you want synthesized,
  name the pages and I'll build from those." Don't silently skip; don't blindly full-reason either.

Otherwise continue.

---

## STEP 1 — Read the schema + the backlog

- Read the wiki's `CLAUDE.md` (Causal-chain page format, Lint workflow, Model selection, Hard rules).
- Collect every `Causal-chain candidate` block in `log.md` since the last compile/causal-chain entry.
- List existing pages: `find wiki -name '*.md' -exec basename {} .md \; | sort` (so link targets and
  duplicates are known before building).

## STEP 2 — Triage candidates (build only the warranted ones)

Most logged candidates do **not** warrant a standalone page. Build a dedicated `causal-chain` page
only when a chain is:
- **central + recurring** (the same cascade is logged across multiple sources), OR
- **branching** (a decision/fork with two outcomes) or has a **feedback loop**, OR
- **distinctive teaching content** worth its own page.

Do **not** build a page for a candidate that is:
- already fully captured by `What causes this` / `What this causes` bullets on a concept page, or
- a sub-3-link fragment (a 2-node reciprocal loop is just a bidirectional edge — keep it inline), or
- a duplicate of an existing chain.

Record the triage decision for each candidate in the log (built / folded-into-X / kept-inline).

## STEP 3 — Build the warranted causal-chain pages

Follow the schema's **Causal-chain page format** exactly: frontmatter (`type: causal-chain`, real
`sources:`, `last_updated` from `date "+%Y-%m-%d %H:%M:%S"`), Mermaid flowchart **and** ASCII
fallback, the canonical **Links table** (every edge has an explicit direction token and a Source),
Node index, `## Loop` only for cyclic chains. Source every edge with `raw/NNNN_…/article.md (slide N)`
drawn from the already-source-grounded concept-page bullets — **no fabricated quotes**; mark any
LLM-supplied bridge `EXTERNAL` with a citation. Verify every `[[target]]` exists or is an intentional
forward link.

## STEP 4 — Wire the new pages in

- Add each new chain to `index.md` under **Causal Chains**.
- Add **inbound** Related links from the most relevant concept pages so no chain is an orphan (≥2 in).
- Resolve any `Opus-pass candidate` / `causal-chain candidate` pending notes left in concept pages —
  point them at the built page (or record the deliberate decision to keep a chain inline).

## STEP 5 — Full lint pass

Run the schema's **Lint workflow** in full: orphans, missing pages, near-miss slugs, stale
pending-pointers, contradictions (apply the contradiction protocol), causal-chain gaps, missing
direction labels, EXTERNAL-unverified links, stale sources, broken asset links, **unreferenced source
images** (open flagged images per Hard Rule 9 — decide decorative vs dropped-illustrative), thin
pages, missing cross-references. Fix what is fixable; log the rest.

## STEP 6 — Regenerate the MOC

`python "~/.claude/skills/home-page-moc.py" --root .` (the `/home-page-moc` skill).
Parse its `RESULT:{…}` line.

## STEP 7 — Log + commit

- Append two `log.md` entries (append-only): `## [ts] causal-chain | compile pass (…)` and
  `## [ts] lint | full lint pass (…)`, recording the model that ran, the triage decisions, and
  every lint finding/fix.
- Commit and push following your project's normal git practice. If the wiki tracks raw binaries with
  Git LFS and this commit added **new** ones, run `git lfs push --all origin` first; a chains+lint+MOC
  compile is normally text-only, so a plain `git push` suffices.

## STEP 8 — Report

Tell the user: chains built (and total), lint findings/fixes, MOC page count, and the commit hash.
