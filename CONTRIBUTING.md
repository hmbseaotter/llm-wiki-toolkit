# Contributing

Thanks for your interest in **llm-wiki-toolkit** — the Claude Code skills that build and maintain an
LLM wiki, companion to [compounding-llm-wiki](https://github.com/hmbseaotter/compounding-llm-wiki).
Contributions are welcome under one bar: keep it simple, cross-platform, and consistent with the
wiki schema the skills serve.

> **Command note:** commands here use the **Windows** form `pip` / `python`. On **macOS / Linux** use
> `pip3` / `python3`.

## Ways to contribute
- **Open an issue** for a bug, an unclear doc, or a proposed skill/engine change — ideally before a
  large PR, so we can agree on scope.
- **Send a PR** for fixes, doc improvements, a new skill, or an engine improvement.

## How a skill is structured
Each skill is a Markdown file in `skills/` (`<name>.md`) describing the workflow the agent follows.
Skills that do deterministic heavy lifting pair the `.md` with a Python **engine** (`<name>.py`) so
the mechanical work runs as plain code, not tokens. Keep engines **standard-library where possible**
— PyMuPDF and markdownify are the only accepted third-party deps (see `requirements.txt`).

## Setup & testing
- Install the skills: **Windows (PowerShell)** `./install.ps1` · **macOS / Linux** `./install.sh`
- Engine deps: `pip install -r requirements.txt`
- **Test a change by running the affected skill end to end** against a sample document and confirming
  the output (e.g. `/pdf-to-images` on a sample PDF, `/wiki-compile` on a small wiki).

## Conventions
- **Cross-platform:** ship installer behavior in both `install.ps1` (Windows) and `install.sh`
  (macOS/Linux); keep the two in sync.
- **Stay in lockstep with the schema.** These skills produce content for the `compounding-llm-wiki`
  schema. A change to page format, ingest, or the MOC must match that repo's `CLAUDE.md` / `schema/` —
  update both, or open paired issues.
- **Deterministic over tokens:** push mechanical work (parsing, rasterizing, formatting) into the
  Python engines; reserve the agent for judgment.

## Pull requests
- Keep changes **focused** — one skill/concern per PR.
- Clear commit messages (subject + a short "why").
- Update `README.md` (the skills table + prerequisites) when you add or change a skill.

## License
By contributing, you agree your contributions are licensed under the repo's [MIT License](LICENSE).
