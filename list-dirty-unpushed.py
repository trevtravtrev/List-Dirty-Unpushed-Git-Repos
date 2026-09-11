#!/usr/bin/env python3
"""list-dirty-unpushed - list the git repos in a folder that have dirty
files or unpushed commits (read-only check).

For every immediate subdirectory that contains a .git entry, reports the
current branch, dirty file count (incl. untracked), unpushed commit count,
and days since the last commit. Sorts worst-first and hides fully clean
repos unless --all is given.

Strictly read-only: only runs rev-parse / status / rev-list / log, with
GIT_OPTIONAL_LOCKS=0 so even optional index refresh is skipped. Never
crashes on broken repos; those get an [error: ...] note instead.

Usage:
    python list-dirty-unpushed.py [--dir PATH] [--all] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

MAX_WORKERS = 8     # parallel repo checks; Windows git is slow
GIT_TIMEOUT = 20    # seconds per git invocation
NOTE_MAX = 80       # max chars kept from a git error message

_env_cache = None


def _env() -> dict:
    """Environment for git calls: no credential prompts, no index writes."""
    global _env_cache
    if _env_cache is None:
        _env_cache = dict(os.environ)
        _env_cache["GIT_TERMINAL_PROMPT"] = "0"
        _env_cache["GIT_OPTIONAL_LOCKS"] = "0"
    return _env_cache


def _git(cwd: str, *args: str) -> tuple[int, str, str]:
    """Run a read-only git command. Returns (rc, stdout, stderr) as text."""
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_env(),
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"git timed out after {GIT_TIMEOUT}s"
    except OSError as e:
        return 127, "", f"could not run git: {e.strerror or e}"


def _note(stderr: str, fallback: str) -> str:
    """First non-empty stderr line, truncated; or a fallback message."""
    for line in (stderr or "").splitlines():
        line = line.strip()
        if line:
            return (line[: NOTE_MAX] + "...") if len(line) > NOTE_MAX else line
    return fallback


def sweep_repo(path: str) -> dict:
    """Gather status of one repo. Never raises; problems become error notes."""
    r: dict = {
        "name": os.path.basename(os.path.normpath(path)),
        "branch": None,
        "dirty": None,
        "unpushed": None,
        "last_commit_days": None,
        "error": None,
    }

    def note(msg: str) -> None:
        if r["error"] is None:
            r["error"] = msg

    try:
        # 1. Current branch; detached HEAD -> short SHA.
        head_ref = None
        rc, out, err = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0 and out.strip():
            head_ref = out.strip()
            if head_ref == "HEAD":  # detached
                rc2, out2, _ = _git(path, "rev-parse", "--short=7", "HEAD")
                r["branch"] = out2.strip() if rc2 == 0 else "detached"
            else:
                r["branch"] = head_ref
        else:
            note(_note(err, "no HEAD (empty or broken repo)"))

        # 2. Dirty count (modified + staged + untracked), one line each.
        rc, out, err = _git(path, "status", "--porcelain")
        if rc == 0:
            r["dirty"] = len([ln for ln in out.splitlines() if ln.strip()])
        else:
            note(_note(err, "git status failed"))

        # 3. Unpushed: prefer @{u}; fall back to origin/<branch> if it
        #    exists; else the literal "no-upstream".
        if head_ref is not None:
            if head_ref == "HEAD":  # detached: no branch upstream to compare
                r["unpushed"] = "no-upstream"
            else:
                rc, _, _ = _git(path, "rev-parse", "--verify", "--quiet", "@{u}")
                if rc == 0:
                    rc, out, err = _git(path, "rev-list", "--count", "@{u}..HEAD")
                    if rc == 0 and out.strip().isdigit():
                        r["unpushed"] = int(out.strip())
                    else:
                        note(_note(err, "rev-list @{u}..HEAD failed"))
                else:
                    rc, _, _ = _git(
                        path, "rev-parse", "--verify", "--quiet",
                        f"refs/remotes/origin/{head_ref}",
                    )
                    if rc == 0:
                        rc, out, err = _git(
                            path, "rev-list", "--count", f"origin/{head_ref}..HEAD",
                        )
                        if rc == 0 and out.strip().isdigit():
                            r["unpushed"] = int(out.strip())
                        else:
                            note(_note(err, "rev-list origin/<branch>..HEAD failed"))
                    else:
                        r["unpushed"] = "no-upstream"

        # 4. Days since last commit on the current branch.
        rc, out, err = _git(path, "log", "-1", "--format=%ct")
        if rc == 0 and out.strip().isdigit():
            r["last_commit_days"] = max(0, int((time.time() - int(out.strip())) // 86400))
        else:
            note(_note(err, "no commits yet"))
    except Exception as e:  # last-resort guard: never crash the sweep
        if r["error"] is None:
            r["error"] = f"unexpected: {type(e).__name__}: {e}"
    return r


def _has_work(r: dict) -> bool:
    if (r["dirty"] or 0) > 0:
        return True
    return isinstance(r["unpushed"], int) and r["unpushed"] > 0


def _sort_key(r: dict) -> tuple:
    # Work repos first, then broken repos, then clean; within each group by
    # days-since-last-commit descending (unknown days sort last), then name.
    if _has_work(r):
        group = 0
    elif r["error"]:
        group = 1
    else:
        group = 2
    days = r["last_commit_days"]
    rank = -days if days is not None else 10**9
    return (group, rank, r["name"])


def _fmt_repo(r: dict) -> str:
    line = (
        f"{r['name']}  "
        f"branch={r['branch'] or '?'}  "
        f"dirty={'?' if r['dirty'] is None else r['dirty']}  "
        f"unpushed={'?' if r['unpushed'] is None else r['unpushed']}  "
        f"last={'?' if r['last_commit_days'] is None else str(r['last_commit_days']) + 'd'}"
    )
    if r["error"]:
        line += f"  [error: {r['error']}]"
    return line


def main(argv=None) -> int:
    # Keep console output robust regardless of the Windows code page.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        prog="list-dirty-unpushed",
        description="Sweep a folder of git repos (read-only) and report "
                    "dangling work: dirty files, unpushed commits, stale branches.",
    )
    ap.add_argument(
        "--dir",
        default=os.path.join(os.path.expanduser("~"), "Documents", "GitHub"),
        # NOTE: '%%' is the argparse %-escape; a bare '%' elsewhere in this
        # string would break --help.
        help="folder to sweep (default: %%USERPROFILE%%\\Documents\\GitHub)",
    )
    ap.add_argument("--all", action="store_true",
                    help="include fully clean repos (default: hide them)")
    ap.add_argument("--json", action="store_true",
                    help="print a JSON array instead of text lines")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.dir):
        print(f"list-dirty-unpushed: directory not found: {args.dir}", file=sys.stderr)
        return 2

    try:
        entries = sorted(os.listdir(args.dir))
    except OSError as e:
        print(f"list-dirty-unpushed: cannot read directory: {e.strerror or e}", file=sys.stderr)
        return 2

    paths = []
    for entry in entries:
        p = os.path.join(args.dir, entry)
        # .git may be a directory (normal repo) or a file (worktree/submodule);
        # lexists also catches a dangling symlink.
        if os.path.isdir(p) and os.path.lexists(os.path.join(p, ".git")):
            paths.append(p)

    if paths:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            results = list(pool.map(sweep_repo, paths))
    else:
        results = []

    results.sort(key=_sort_key)
    shown = results if args.all else [r for r in results if r["error"] or _has_work(r)]

    if args.json:
        print(json.dumps(shown, ensure_ascii=False))
        return 0

    for r in shown:
        print(_fmt_repo(r))

    total = len(results)
    n_dirty = sum(1 for r in results if (r["dirty"] or 0) > 0)
    n_unpushed = sum(1 for r in results if isinstance(r["unpushed"], int) and r["unpushed"] > 0)
    n_error = sum(1 for r in results if r["error"])
    n_clean = sum(
        1 for r in results
        if not r["error"] and (r["dirty"] or 0) == 0
        and not (isinstance(r["unpushed"], int) and r["unpushed"] > 0)
    )
    n_work = sum(1 for r in results if _has_work(r))

    line1 = f"total={total}  dirty={n_dirty}  unpushed={n_unpushed}  clean={n_clean}"
    if n_error:
        line1 += f"  errors={n_error}"
    print(line1)
    if total:
        print(f"{n_work} of {total} repos have dangling work")
    else:
        print("no git repos found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
