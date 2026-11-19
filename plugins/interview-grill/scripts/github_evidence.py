#!/usr/bin/env python3
"""Collect authorship + code facts about a candidate's public GitHub repos. Read-only; never runs repo code.

usage: github_evidence.py <github-user | github-user/repo | url> [...] [--login USER] [--max-repos 5] [--max-mb 50] [--keep DIR]
Needs the `gh` CLI (logged in) and `git`. Prints Markdown. Secret findings show file:line and kind, never the value.
"""
import argparse, base64, collections, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

CODE = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".cs", ".php", ".rb", ".kt", ".swift", ".sql", ".ipynb")
SKIP = re.compile(r"(node_modules|vendor|dist|build|\.min\.|package-lock|yarn\.lock|\.lock$|/migrations/|__pycache__)")
TRIVIAL = re.compile(r"(typo|readme|initial commit|add files via upload|update\b|first commit|^commit$)", re.I)
SECRETS = [
    ("hard-coded password/secret/token", re.compile(r"""(?i)(pass(word|wd)?|secret|api[_-]?key|token)\w*\s*[:=]\s*['"](?!https?://)[^'"\s]{8,}['"]""")),
    ("Gmail-style app password", re.compile(r"""['"]([a-z]{4} ){3}[a-z]{4}['"]""")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("OpenAI/Anthropic-style key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
]


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or f"gh api {path} failed")
    return json.loads(r.stdout)


def scan(path, text, hits):
    for i, ln in enumerate(text.splitlines(), 1):
        for kind, rx in SECRETS:
            if rx.search(ln):
                hits.append(f"{path}:{i} ({kind})")


def parse(t):
    t = re.sub(r"^https?://(www\.)?github\.com/", "", t.strip()).removesuffix(".git").strip("/")
    p = t.split("/")
    return (p[0], p[1] if len(p) > 1 else None)


def analyse(owner, repo, login, max_mb, keep):
    m = gh(f"repos/{owner}/{repo}")
    full = m["full_name"]
    print(f"\n## {full}\n")
    print(f"- fork: **{m['fork']}**" + (f" (of {m['parent']['full_name']})" if m["fork"] else ""))
    print(f"- language: {m['language']} | size: {m['size']//1024} MB | created {m['created_at'][:10]} | last push {m['pushed_at'][:10]}")
    print(f"- description: {m['description'] or '(none)'}")
    commits = []
    for page in (1, 2, 3):
        try:
            commits += gh(f"repos/{full}/commits?per_page=100&page={page}")
        except RuntimeError:
            break
    flags = []
    if m["fork"]:
        flags.append("fork: check the CV does not say 'built' for someone else's project")
    if not commits:
        print("- no commits readable")
        return
    mine = [c for c in commits if (c.get("author") or {}).get("login", "").lower() == login.lower()]
    emails = {c["commit"]["author"]["email"] for c in mine}
    others = collections.Counter((c.get("author") or {}).get("login") or c["commit"]["author"]["name"] for c in commits)
    nm = [c for c in mine if len(c["parents"]) < 2]
    share = len(mine) / len(commits)
    dates = sorted(c["commit"]["author"]["date"][:10] for c in mine) or ["-"]
    print(f"- commits read: {len(commits)} (max 300) | by {login}: **{len(mine)} ({share:.0%})** | first/last: {dates[0]} / {dates[-1]}")
    print("- authors: " + ", ".join(f"{k} {v}" for k, v in others.most_common(6)))
    if len(commits) >= 20 and share < 0.2:
        flags.append(f"candidate wrote only {share:.0%} of commits: ask what exactly they built")
    if len(commits) <= 3:
        flags.append("history is 1-3 commits (bulk upload): authorship cannot be checked from history, probe by asking")
    if mine and sum(bool(TRIVIAL.search(c["commit"]["message"].split("\n")[0])) for c in mine) / len(mine) > 0.8:
        flags.append("almost all of the candidate's commits are trivial (readme/typo/update/initial)")
    print("- candidate commit titles: " + " | ".join(c["commit"]["message"].split("\n")[0][:50] for c in mine[:6]))

    tree = gh(f"repos/{full}/git/trees/HEAD?recursive=1").get("tree", [])
    blobs = [t for t in tree if t["type"] == "blob"]
    big = [t for t in blobs if t.get("size", 0) > 5_000_000]
    if big:
        flags.append(f"{len(big)} file(s) over 5 MB committed (weights/videos): " + ", ".join(Path(t['path']).name for t in big[:4]))
    if not any(re.search(r"(^|/)(tests?|__tests__)(/|_)|test_|\.test\.|\.spec\.", t["path"]) for t in blobs):
        flags.append("no tests found")
    src = [t for t in blobs if t["path"].endswith(CODE) and not SKIP.search(t["path"])]

    if m["size"] <= max_mb * 1024:
        d = Path(keep or tempfile.mkdtemp(prefix="ig-")) / repo
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "-q", "--no-recurse-submodules", m["clone_url"], str(d)], check=True)
        lines, mine_lines, per_file = 0, 0, {}
        for t in src[:400]:
            r = subprocess.run(["git", "-C", str(d), "blame", "-w", "--line-porcelain", "--", t["path"]], capture_output=True, text=True, errors="ignore")
            n = c = 0
            for ln in r.stdout.splitlines():
                if ln.startswith("author-mail "):
                    n += 1
                    c += ln.split(" ", 1)[1].strip("<>") in emails
            lines, mine_lines = lines + n, mine_lines + c
            if c:
                per_file[t["path"]] = (c, n)
        print(f"- source lines blamed to candidate: **{mine_lines} of {lines} ({(mine_lines/lines if lines else 0):.0%})**")
        if lines and mine_lines / lines < 0.2 and len(commits) > 3:
            flags.append(f"candidate owns only {mine_lines/lines:.0%} of current source lines")
        print("- files they wrote most (candidate lines / file lines):")
        for p, (c, n) in sorted(per_file.items(), key=lambda x: -x[1][0])[:10]:
            print(f"  - `{p}` {c}/{n}")
        hits = []
        for t in blobs:
            if t.get("size", 0) > 200_000 or SKIP.search(t["path"]) or t["path"].lower().endswith((".png", ".jpg", ".pdf", ".mp4", ".pth", ".pt", ".lock")):
                continue
            try:
                scan(t["path"], (d / t["path"]).read_text(errors="ignore"), hits)
            except OSError:
                pass
        if hits:
            flags.append("possible secrets committed (values NOT shown; tell the candidate to revoke): " + "; ".join(hits[:8]))
        print(f"- clone: `{d}` (read-only; delete it when done)" if keep else "- (clone deleted after analysis; use --keep DIR to read files)")
        if not keep:
            shutil.rmtree(d.parent, ignore_errors=True)
    else:
        print(f"- repo is {m['size']//1024} MB: not cloned. Source files to fetch with `gh api repos/{full}/contents/<path> --jq .content | base64 -d`:")
        hits = []
        for t in sorted(src, key=lambda t: t["size"])[:40]:
            print(f"  - `{t['path']}` ({t['size']} B)")
            try:  # secret scan on the 40 smallest source files, read through the API
                scan(t["path"], base64.b64decode(gh(f"repos/{full}/git/blobs/{t['sha']}")["content"]).decode(errors="ignore"), hits)
            except RuntimeError:
                pass
        if hits:
            flags.append("possible secrets committed in the files scanned (values NOT shown; tell the candidate to revoke): " + "; ".join(hits[:8]))
    print("\n**Flags (ask about them, never accuse):**" if flags else "\n**Flags:** none")
    for f in flags:
        print(f"- {f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--login")
    ap.add_argument("--max-repos", type=int, default=5)
    ap.add_argument("--max-mb", type=int, default=50)
    ap.add_argument("--keep")
    a = ap.parse_args()
    for t in a.targets:
        owner, repo = parse(t)
        login = a.login or owner
        u = gh(f"users/{owner}")
        print(f"# {u['login']} ({u.get('name') or '-'}) | public repos: {u['public_repos']} | account created {u['created_at'][:10]} | followers {u['followers']}")
        repos = [repo] if repo else [r["name"] for r in gh(f"users/{owner}/repos?per_page=100&sort=pushed") if r["size"] > 0][: a.max_repos]
        for r in repos:
            try:
                analyse(owner, r, login, a.max_mb, a.keep)
            except Exception as e:  # one bad repo must not stop the rest
                print(f"\n## {owner}/{r}\n- could not analyse: {e}")


if __name__ == "__main__":
    sys.exit(main())
