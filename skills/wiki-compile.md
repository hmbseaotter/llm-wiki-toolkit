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
   - **unapplied resolutions**: `python tools/structure_qa.py` reporting `unapplied-resolution` — a
     human resolved a contradiction and the decision never reached the page prose. This one is *always*
     dirty-making and must never be scoped away: nothing else in the system will ever chase it (see
     STEP 5).
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

## STEP 5 — Lint pass (scoped per the STEP 2 triage)

Run the schema's **Lint workflow**, honouring its **Scope** rule (incremental by default — see the
schema's `### Scope` subsection). The split matters: the cheap checks are cheap enough to run over
everything every time, while the expensive ones are what a full-wiki sweep would waste model budget
on, so they follow the delta instead.

- **Deterministic checks, repo-wide** — run the wiki's own QA cores FIRST if it ships them, rather
  than hand-rolling the equivalent greps (they are stdlib-only, take no context, and their output is
  the same one any pipeline and pre-commit gate act on, so the lint can never disagree with the
  automation):

  ```bash
  python tools/structure_qa.py       # duplicate slugs, index parity both ways, stale pending-pointers,
                                     # broken image links, out-of-vocabulary direction tokens
  python tools/contradiction_qa.py   # open contradictions by severity + the soft/scope aging report
  ```

  Both are optional — skip whichever is absent (older wikis may ship neither). Then cover what they do
  not: orphans, near-miss slugs, EXTERNAL-unverified links, stale sources, **unreferenced source
  images** (open flagged images per Hard Rule 9 — decide decorative vs dropped-illustrative).

  **A structural finding needs a home.** A wiki with no ingest pipeline has no email channel at all,
  so anything `structure_qa` reports must be fixed in this pass or written into the `log.md` lint
  entry as explicitly OPEN with the reason — never mentioned in passing. In one wiki a duplicate slug
  sat unseen for 14 days because it was reported to `log.md` and nowhere else.
- **PENDING contradiction assessments — repo-wide, never scoped, and yours alone to write.** Where a
  wiki's ingest step runs on a cheaper model, that model should only DETECT a conflict: record both
  claims verbatim with a *provisional* severity and leave
  `LLM assessment: PENDING — … awaiting <opus model> review`. The schema routes the assessment to the
  reasoning model because its value depends on reasoning quality. So:

  ```bash
  grep -rn "LLM assessment: PENDING" wiki/
  ```

  Write a real assessment for every hit, then **confirm or OVERRIDE the provisional severity** against
  the schema's test (`hard` only when the two claims cannot both be true; two studies disagreeing is
  `soft`), and set `Last reviewed: <your model>, <ts>`. An escalation to `hard` blocks an automated
  commit and summons the user — that is correct, and is the whole reason this step exists. A PENDING
  assessment anywhere in the wiki is unfinished work, so this one ignores the delta scoping below.
- **Unapplied resolutions — repo-wide, never scoped, and the highest-value work in this step.** When a
  human resolves a contradiction (through a control panel, or by hand), typically only the
  `Status: Resolved — <note>` line is written: no prose is edited and no model is called. But the note is
  routinely a *directive* ("disregard that figure", "mark this as an error", "this framing should be
  primary"). And the instant `Status:` stops being `Unresolved`, the block leaves the commit gate, the
  aging report and any nag or review queue simultaneously — `Resolved` is a **terminal state**, so an
  unapplied resolution is chased by nothing else, ever.

  ```bash
  python tools/structure_qa.py    # reports these as `unapplied-resolution`
  ```

  For each hit, follow **Applying a resolution** in the wiki's `schema/contradictions.md`: read the note
  as an instruction addressed to the page text, edit the *body* so it obeys (never `raw/` — Hard Rule 1;
  a resolution corrects the wiki's rendering of a source, never the source), leave the contradiction
  block itself intact as the permanent record, and write the `Applied:` record with one `·` entry per
  edit, each anchored to its **section heading** and carrying the verbatim `−`/`+` text. Where nothing
  needed changing, write `Applied: none required — <why>` — "nothing was needed" and "nobody looked" must
  never be indistinguishable. Never let the edit silently settle a *different* open contradiction
  (Hard Rule 7).

  Two reasons this cannot be deferred or scoped: `## Contradictions flagged` sits at the **bottom** of
  every page, so a reader who stops after "How it works" never learns the human's decision was made; and
  when this check was first written, a real corpus was found to have **no application record on any of
  its 15 resolved contradictions** — one page had spent weeks teaching the exact framing the human had
  explicitly demoted.
- **Reasoning-heavy checks, scoped to the STEP 2 delta** (the changed set + its 1st/2nd-degree
  `[[wikilink]]` neighbours): contradictions already assessed (re-check only if the delta touches
  them), causal-chain gaps, thin pages, missing cross-references. Run these **across the whole wiki
  only** when the user asked for a full lint, or at a milestone such as just after a large bootstrap
  ingest.

Fix what is fixable; log the rest, recording which scope ran.

## STEP 6 — Regenerate the MOC

`python "~/.claude/skills/home-page-moc.py" --root .` (the `/home-page-moc` skill).
Parse its `RESULT:{…}` line.

## STEP 7 — Log + commit

- Append two `log.md` entries (append-only): `## [ts] causal-chain | compile pass (…)` and
  `## [ts] lint | lint pass (scope: incremental|full) (…)`, recording the model that ran, the scope
  and triage decisions, and every lint finding/fix.
- Commit and push following your project's normal git practice. If the wiki tracks raw binaries with
  Git LFS and this commit added **new** ones, run `git lfs push --all origin` first; a chains+lint+MOC
  compile is normally text-only, so a plain `git push` suffices.

## STEP 8 — Report

Tell the user: chains built (and total), lint findings/fixes, MOC page count, and the commit hash.
