# List Dirty & Unpushed Git Repos

A read-only sweep of a folder of git repos. Shows at a glance which repos have
**dangling work** — uncommitted changes, unpushed commits — and how stale each
one is.

## What it reports

For every immediate subfolder containing a `.git` entry (anything else is
skipped silently):

| Column     | Meaning |
| ---------- | ------- |
| `NAME`     | Folder name (bold, truncated past 30 chars) |
| `BRANCH`   | Current branch — a detached `HEAD` shows a short SHA |
| `DIRTY`    | Modified + staged + untracked file count (`git status --porcelain`) — red when > 0 |
| `UNPUSHED` | Commits ahead of upstream (`@{u}..HEAD`); if no upstream is set, falls back to `origin/<branch>..HEAD`; otherwise `no-upstream` — yellow when > 0 |
| `LAST`     | Days since the last commit on that branch — yellow at 30+ days, red at 90+ |

Repos sort worst-first (dirty/unpushed first, then oldest). A broken repo
never crashes the sweep — it just gets an `[error: ...]` note.

## Usage

```bat
:: double-click the .bat (the window stays open so you can read it), or:
list-dirty-unpushed.bat
list-dirty-unpushed.bat --all
list-dirty-unpushed.bat --dir D:\MyRepos
list-dirty-unpushed.bat --json
```

```bash
# straight from a terminal:
python list-dirty-unpushed.py --all
python list-dirty-unpushed.py --dir /path/to/repos --json
```

| Flag       | Meaning |
| ---------- | ------- |
| `--dir P`  | Folder to sweep (default: `%USERPROFILE%\Documents\GitHub`) |
| `--all`    | Also show fully clean repos (hidden by default) |
| `--json`   | Machine-readable output: a one-line JSON array |

## Example output

```
folder: C:\Users\you\Documents\GitHub
NAME             BRANCH    DIRTY      UNPUSHED   LAST
api-server       main          3             2     0d
web-app          dev           0      no-upstream     6d
old-prototype    main          0      no-upstream   131d
abandoned-thing  ?             ?             ?      ?  [error: fatal: not a git repository]
----------------------------------------------------
total 4   dirty 1   unpushed 1   clean 0   broken 1
2 of 4 repos have dangling work
```

Colors appear only in a real terminal; they turn off automatically when
output is piped or when `NO_COLOR` is set. Force either way with
`REPOSWEEP_COLOR=always` or `REPOSWEEP_COLOR=never`.

## Guarantees

- **Strictly read-only.** Only `git rev-parse`, `git status`, `git rev-list`,
  and `git log` are ever run — with `GIT_OPTIONAL_LOCKS=0`, so even an
  optional index refresh is skipped. Nothing is ever changed, fetched, or pushed.
- **Never crashes.** Empty repos, broken `.git` directories, and permission
  errors become `[error: ...]` notes; the sweep continues.
- **Fast on Windows.** Up to 8 repos are checked in parallel, with a 20-second
  timeout per git call so one hung repo can't stall the sweep.

## Requirements

- Python 3.9+ (standard library only — no dependencies)
- `git` on `PATH` (Git for Windows works out of the box)
