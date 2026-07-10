# Knowledge
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

A shared **knowledge vault**: a plain folder of Markdown files with YAML
frontmatter and `[[wikilinks]]` that accumulates over time so agents (and
you) can build on past work. It's deliberately dumb — the folder *is* a
valid Obsidian/Logseq/Foam vault, no integration code needed. Every finished
team run auto-archives its deliverable here; agents with the `knowledge`
tool can search/read/write notes mid-run.

## Key files

| Path | Role |
|------|------|
| `knowledge.py` | Vault I/O: `write_note`, `export_run`, `list_notes`, `read_note`, `search`, `stats`. Frontmatter generation, path safety, slugging. |
| `app.py` | `GET /api/knowledge`, `GET/POST /api/knowledge/note`. |
| `tools.py` | `knowledge_search`/`knowledge_read`/`knowledge_write` — the agent-facing "knowledge" tool bundle (thin wrappers around `knowledge.py`; see `docs/features/skills-tools/` for how bundles/tools are wired). |
| `runmanager.py` | Calls `knowledge.export_run(...)` (best-effort) right after a run finishes. |
| `frontend/src/pages/Knowledge.jsx` | Vault browser: search/list, note reader with frontmatter strip, "New note" modal. |

## API

- `GET /api/knowledge?q=<query>` — if `q` is given, returns search results;
  otherwise the full note list.
  - No search: `{stats: {dir, count, bytes}, notes: [{path, title, tags,
    size, modified}]}`.
  - With search: `{stats, results: [{path, title, snippet}]}`.
- `GET /api/knowledge/note?path=<vault-relative path>` → `{path, content}`
  (raw Markdown, frontmatter included). 404 if the path doesn't exist or
  resolves outside the vault.
- `POST /api/knowledge/note {title, content}` → `{path}` — both fields
  required (non-empty after strip). Saved to
  `notes/YYYY-MM-DD-<slugified-title>.md` with frontmatter `title`,
  `created`, `tags: [manual]`, `source: manual`.

There is **no update/delete API for notes** — see Gotchas.

## How it works

- **Location**: `data/knowledge/` by default; override with `AGENTS_KNOWLEDGE`
  to point straight at an existing Obsidian/Logseq vault and merge the two.
- **Auto-archiving**: `runmanager._execute` calls `knowledge.export_run(
  run_id, team_name, task, final)` right after a run's `final` is computed
  (wrapped in try/except — a knowledge-export failure never fails the run).
  The note is saved under `team-outputs/YYYY-MM-DD-<task-slug>.md` with
  frontmatter `title`, `created`, `tags: [team-output, <team-slug>]`, `team`,
  `run_id`, `source: team-run`, and body text containing an **intentionally
  unresolved** `[[Team Name]]` wikilink — create that note yourself in
  Obsidian and its backlinks/graph view collects every output that team ever
  produced.
- **Frontmatter safety**: `_yaml_str`/`_frontmatter` **quote any value that
  isn't a bare word or number** — this specifically fixes titles containing
  `:` or `#`, which would otherwise break Obsidian's properties panel
  (`title: Task: foo bar` is invalid bare YAML; `title: "Task: foo bar"` is
  fine). Tags are always **slug-normalized** (`_slug`: lowercased,
  non-alphanumeric runs collapsed to `-`, capped at 60 chars) because
  Obsidian tags can't contain spaces.
- **Path safety**: `_safe_path` resolves every vault-relative path via
  `os.path.realpath` and rejects anything that would escape `KNOWLEDGE_DIR`;
  `.md` is auto-appended if missing. `_unique_path` appends `-2`, `-3`, …
  instead of overwriting on a filename collision.
- **Search** (`knowledge.search`): tokenizes the query (split on
  non-alphanumeric runs, terms >1 char), and for every note scores it by
  *(number of distinct query terms matched in title or body)* + *(+1 per
  term also found in the title)* + *(+1 flat bonus if the note is **not**
  under `team-outputs/`)* — **curated notes deliberately outrank
  auto-exported run outputs**, so agents don't keep resurfacing their own
  (possibly wrong) past deliverables ahead of hand-written knowledge. Results
  sort by *(all-terms-matched flag, score)* descending. This is a **linear
  scan** over every note's full text on every call — no index (see
  `CLAUDE.md`'s known gaps: consider SQLite FTS5 if the vault grows large).
- **Reading Obsidian/Logseq/Foam vaults**: no integration needed — open
  `data/knowledge/` (or wherever `AGENTS_KNOWLEDGE` points) as a folder in
  any of those tools. Notes, tags, `[[wikilinks]]`, and graph view all work
  immediately; new agent output appears the moment a run finishes.

## Gotchas

- **No update/delete API.** Once written (manually via `POST
  /api/knowledge/note`, or automatically by a run), a note can only be
  edited by hand on disk — `Knowledge.jsx` has no edit or delete button, and
  `app.py` exposes no `PUT`/`DELETE` for notes.
- **Search is a full linear scan**, re-reading every note's content on every
  query — fine for hundreds of notes, will get slow as the vault grows (this
  is a known, accepted gap, not an oversight).
- `team-outputs/` notes are **down-ranked, not filtered** — an agent's own
  past output can still surface first if it matches the query terms better
  than anything else; the `+1` bonus only breaks near-ties in favor of
  curated notes.
- `export_run` silently no-ops if `final` is empty/whitespace-only — a run
  that produced no usable final content leaves **no** knowledge trace and no
  error either.
- The `[[Team Name]]` wikilink in every auto-archived note is intentionally
  left unresolved. It is not a bug that the note doesn't exist; create it by
  hand in Obsidian if you want that backlink graph to be meaningful.
- Frontmatter values are quoted defensively based on a regex
  (`[\w-]+` passes through bare) — anything with punctuation, including a
  colon in a task description used as a title, gets wrapped in quotes with
  `\`/`"` escaped. Don't hand-roll frontmatter elsewhere in the codebase
  without the same escaping or you'll reintroduce the bug this fixed.

## How to verify

1. Run any seeded team to completion, then `GET /api/knowledge` and confirm
   a new note appears under `team-outputs/` with `title`, `created`, `tags`,
   `team`, `run_id`, `source` in its frontmatter (open the raw file to check
   quoting on a task with a colon in it).
2. Open the note in the **Knowledge** page and confirm the frontmatter strip
   and rendered Markdown body match the run's final deliverable.
3. `POST /api/knowledge/note` with a title/content containing a word unique
   to it, then `GET /api/knowledge?q=<that word>` and confirm it ranks above
   any `team-outputs/` note that happens to contain the same word.
4. Point `AGENTS_KNOWLEDGE` at a scratch folder, restart, run a team, and
   open that folder in Obsidian or Logseq — confirm frontmatter/tags/
   wikilinks render correctly with no import step.
5. Give an agent the `knowledge` tool, run a task that instructs it to
   search first, and confirm `tool_call`/`tool_result` events show
   `knowledge_search` (and `knowledge_read`/`knowledge_write` if applicable)
   firing.
