# Knowledge base & Obsidian

Local Agents Studio keeps a **shared knowledge vault**: a plain folder of Markdown
files that accumulates over time so your agents (and you) can build on past work
instead of starting from scratch every run.

## How it works

- **Location:** `data/knowledge/` by default. Override with the
  `AGENTS_KNOWLEDGE` environment variable — point it straight at an existing
  Obsidian/Logseq vault to merge the two.
- **Auto-archiving:** every time a team run finishes, its final deliverable is
  written as a note under `team-outputs/` with YAML frontmatter
  (`title`, `created`, `tags`, `team`, `run_id`) and `[[wikilinks]]`.
- **Agent access:** give any agent the **`knowledge`** tool and it gains three
  functions:
  - `knowledge_search(query)` — token-based search over all notes
  - `knowledge_read(path)` — read a full note
  - `knowledge_write(title, content)` — save a new note (lands in `notes/`)
  So an agent can look up prior findings before working and record durable
  results after. A good pattern: put `knowledge` on your first (research) agent
  and instruct it to "search the knowledge base first."
- **Browsing:** the **Knowledge** page lists and searches notes and renders them,
  with the frontmatter shown as a metadata strip.

## Using Obsidian (the short answer)

**You do not need any integration.** The vault is just standard Markdown, so:

1. Open Obsidian → *Open folder as vault* → select `data/knowledge/`
   (or wherever `AGENTS_KNOWLEDGE` points).
2. That's it. Notes, tags, `[[wikilinks]]` and graph view all work. New agent
   output appears in Obsidian the moment a run finishes.

### Is Obsidian free / local / no-login?

Yes for exactly this use case. Obsidian is **free for personal use**, stores
everything in **local Markdown files**, and needs **no account** to use a local
vault. The only paid parts are optional add-on services you don't need here:
*Sync* (end-to-end encrypted cloud sync) and *Publish* (public websites). Skip
those and Obsidian is fully local and free.

### Fully open-source alternatives (no subscription, no login, local)

If you'd rather avoid Obsidian's closed-source core entirely, point the same
folder at any of these — they all read plain Markdown:

| Tool | License | Notes |
|------|---------|-------|
| **Logseq** | AGPL-3.0 (open source) | Closest Obsidian-like experience; Markdown + outliner, local graph, backlinks. Best pick. |
| **Foam** | MIT (open source) | Runs *inside VS Code*; wikilinks, backlinks, graph. Great if you live in an editor. |
| **SilverBullet** | MIT | Self-hosted web notebook over a Markdown folder. |
| **Trilium Notes** | AGPL-3.0 | Powerful, but uses its own store rather than a flat Markdown folder. |
| **Joplin** | MIT | Markdown notes with optional self-hosted sync; import/export rather than live-folder. |

**Recommendation:** for a drop-in, open-source, Obsidian-like view of this vault,
use **Logseq** (point it at the folder) or **Foam** (open the folder in VS Code).
Both are local-first, free, and need no login.

## Configuration

```bash
# Merge the vault into your real Obsidian vault:
AGENTS_KNOWLEDGE="$HOME/ObsidianVault/agents" ./run.sh
```

In Docker, mount a host folder so the vault lives outside the container:

```yaml
# docker-compose.yml → app service
volumes:
  - ./knowledge:/app/data/knowledge      # or an absolute host path
```
