"""Record fixed bugs as closed issues on the public GitHub repo.

Each entry in the JSON file becomes an issue with the problem in the body,
then a closing comment saying how it was fixed, then it is closed as
completed. Idempotent by title: an issue that already exists is left alone,
or closed with the comment if it is still open.

    python scripts/log-fixed-issues.py open --title T --problem P [--area A] [--label bug]
    python scripts/log-fixed-issues.py close NUMBER --fix F --fixed-in COMMIT
    python scripts/log-fixed-issues.py issues/2026-10-02.json [--repo owner/name] [--dry-run]

Open an issue when the bug is found and close it when its fix is pushed.
The JSON form is for backfilling a batch.

Entry shape:

    {"title": "...", "problem": "...", "fix": "...", "fixed_in": "v2.5.0",
     "labels": ["bug"], "area": "builder"}

The token comes from GITHUB_TOKEN, else from `git credential fill`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


def token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if t:
        return t
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    sys.exit("no GitHub token, set GITHUB_TOKEN or store a credential for github.com")


def call(method: str, path: str, tok: str, body: dict | None = None) -> dict | list:
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            # secondary rate limit on bursts of writes, back off and retry
            if e.code in (403, 429) and attempt < 3:
                time.sleep(20 * (attempt + 1))
                continue
            raise SystemExit(f"{method} {path} -> {e.code} {e.read()[:300]!r}")
    return {}


def existing_titles(repo: str, tok: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    page = 1
    while True:
        rows = call(
            "GET", f"/repos/{repo}/issues?state=all&per_page=100&page={page}", tok
        )
        if not rows:
            break
        for r in rows:
            if "pull_request" not in r:
                found[r["title"].strip()] = r
        page += 1
    return found


def body_for(e: dict) -> str:
    parts = [e["problem"].strip()]
    if e.get("area"):
        parts.append(f"Area: {e['area']}")
    return "\n\n".join(parts)


def closing_for(e: dict) -> str:
    where = f" Fixed in {e['fixed_in']}." if e.get("fixed_in") else ""
    return f"{e['fix'].strip()}{where}"


def open_one(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="log-fixed-issues.py open")
    ap.add_argument("--title", required=True)
    ap.add_argument("--problem", required=True)
    ap.add_argument("--area", default="")
    ap.add_argument("--label", action="append", default=[])
    ap.add_argument("--repo", default="sarkar4777/abenix")
    a = ap.parse_args(argv)
    tok = token()
    have = existing_titles(a.repo, tok).get(a.title.strip())
    if have:
        print(f"#{have['number']} already exists ({have['state']}): {a.title}")
        return
    issue = call(
        "POST",
        f"/repos/{a.repo}/issues",
        tok,
        {
            "title": a.title.strip(),
            "body": body_for({"problem": a.problem, "area": a.area}),
            "labels": a.label or ["bug"],
        },
    )
    print(f"#{issue['number']} opened: {a.title}")


def close_one(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="log-fixed-issues.py close")
    ap.add_argument("number", type=int)
    ap.add_argument("--fix", required=True)
    ap.add_argument("--fixed-in", default="")
    ap.add_argument("--repo", default="sarkar4777/abenix")
    a = ap.parse_args(argv)
    tok = token()
    issue = call("GET", f"/repos/{a.repo}/issues/{a.number}", tok)
    if issue.get("state") == "closed":
        print(f"#{a.number} already closed")
        return
    call(
        "POST",
        f"/repos/{a.repo}/issues/{a.number}/comments",
        tok,
        {"body": closing_for({"fix": a.fix, "fixed_in": a.fixed_in})},
    )
    call(
        "PATCH",
        f"/repos/{a.repo}/issues/{a.number}",
        tok,
        {"state": "closed", "state_reason": "completed"},
    )
    print(f"#{a.number} closed: {issue.get('title')}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "open":
        return open_one(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "close":
        return close_one(sys.argv[2:])
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--repo", default="sarkar4777/abenix")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    entries = json.loads(open(args.file, encoding="utf-8").read())
    tok = token()
    have = existing_titles(args.repo, tok)
    created = closed = skipped = 0
    for e in entries:
        title = e["title"].strip()
        issue = have.get(title)
        if issue and issue["state"] == "closed":
            skipped += 1
            continue
        if args.dry_run:
            print(f"would {'close' if issue else 'create and close'}: {title}")
            continue
        if not issue:
            issue = call(
                "POST",
                f"/repos/{args.repo}/issues",
                tok,
                {
                    "title": title,
                    "body": body_for(e),
                    "labels": e.get("labels") or ["bug"],
                },
            )
            created += 1
            time.sleep(1.5)
        call(
            "POST",
            f"/repos/{args.repo}/issues/{issue['number']}/comments",
            tok,
            {"body": closing_for(e)},
        )
        call(
            "PATCH",
            f"/repos/{args.repo}/issues/{issue['number']}",
            tok,
            {"state": "closed", "state_reason": "completed"},
        )
        closed += 1
        print(f"#{issue['number']} closed: {title}")
        time.sleep(1.5)
    print(f"created {created}, closed {closed}, already closed {skipped}")


if __name__ == "__main__":
    main()
