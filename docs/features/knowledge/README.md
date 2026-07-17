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
- `POST /api/knowledge/note {title, content, folder?}` → `{path}` — title and
  content required. Saved to `<folder>/YYYY-MM-DD-<slugified-title>.md`
  (folder defaults to `notes`, sanitized to word chars, `/`, space, dash)
  with frontmatter `title`, `created`, `tags: [manual]`, `source: manual`.
- `DELETE /api/knowledge/note?path=<rel>` → `{ok}` — removes the file and
  prunes now-empty parent folders. 404 if missing/escaping.
- `GET /api/knowledge/folders` → `{folders: [{name, notes}]}` — top-level
  sub-vaults with note counts (`name: ""` = root-level notes).
- `DELETE /api/knowledge/folder?path=<name>` → `{ok, deleted}` — removes a
  whole sub-vault recursively: the **"forget this topic"** operation.
  Refuses the vault root and any escaping path.
- `POST /api/knowledge/move {path, folder}` → `{ok, path}` — files a note
  into a (possibly new) sub-vault; `folder: ""` moves to root. Collisions get
  the `-2` suffix treatment.
- `GET /api/knowledge/graph` → `{nodes: [{id, title, folder, ghost}],
  edges: [{from, to}]}` — the Obsidian-style graph. Edges come from
  `[[wikilinks]]` in note bodies, resolved against titles, filename stems and
  date-stripped stems (case-insensitive + slugged). Links to notes that don't
  exist become `ghost: true` nodes with `id: "ghost:<slug>"`, exactly like
  Obsidian's faded ghost nodes.

  **Rendering (v2, hard-won):** `VaultGraph` in `Knowledge.jsx` gives
  *unlinked* notes deterministic per-folder sunflower clusters arranged on a
  ring — do NOT force-simulate them; that was tried twice and repulsion
  blasted them into the canvas walls both times. Only the linked subgraph is
  force-simulated, centered (rep 380, spring 0.03, gravity 0.022). Hover
  highlights a node + neighbors and reveals labels (hubs deg≥2 labeled
  always); colors come from live CSS variables so dark mode works.

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

- **Deletes are real disk deletes with no undo** — `DELETE /note` and
  especially `DELETE /folder` remove Markdown files permanently. The UI
  confirms with the note count, but there is no trash can. (Added 2026-07-16;
  before that there was no delete at all.) There is still no in-app *edit* —
  a note's content is changed by hand on disk or in Obsidian.
- **Sub-vault = top-level folder, by convention.** `folders()` and the UI's
  grouping/coloring only look at the FIRST path segment; `project-x/decisions`
  nests fine on disk but groups and deletes as `project-x` in the UI.
- **`knowledge_write`'s `folder` arg is agent-facing** — agents are told to
  file notes by topic, so expect new sub-vaults to appear from runs. There is
  deliberately no agent-facing delete: forgetting is a human decision made in
  the UI.
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
