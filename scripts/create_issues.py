#!/usr/bin/env python3
"""Create GitHub issues from tickets.json via the gh CLI.

Usage:
    python3 scripts/create_issues.py tickets.json --dry-run
    python3 scripts/create_issues.py tickets.json

tickets.json: [{"id": "T1", "title": "...", "body": "...",
                "labels": ["agent:claude", "area:be", "P0"], "depends_on": []}, ...]

Creates missing labels, creates issues in dependency order, and rewrites
T-ids in "Depends on" into real #numbers. Needs `gh auth login` first.
"""
import json
import subprocess
import sys

LABEL_COLORS = {
    "agent:claude": "d97757", "agent:codex": "10a37f",
    "human:dev": "5319e7", "human:ux": "fbca04", "human:biz": "0e8a16",
    "P0": "b60205", "P1": "d93f0b", "contract": "000000",
}


def gh(args, dry):
    if dry:
        print("  $ gh " + " ".join(repr(a) if " " in a else a for a in args))
        return ""
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout.strip()


def topo_order(tickets):
    by_id = {t["id"]: t for t in tickets}
    done, order = set(), []

    def visit(tid, stack=()):
        if tid in done:
            return
        if tid in stack:
            sys.exit(f"Dependency cycle: {' -> '.join(stack + (tid,))}")
        for dep in by_id[tid].get("depends_on", []):
            if dep not in by_id:
                sys.exit(f"{tid} depends on unknown ticket {dep}")
            visit(dep, stack + (tid,))
        done.add(tid)
        order.append(by_id[tid])

    for t in tickets:
        visit(t["id"])
    return order


def ensure_labels(tickets, dry):
    wanted = {label for t in tickets for label in t.get("labels", [])}
    existing = set()
    if not dry:
        existing = {l["name"] for l in json.loads(gh(["label", "list", "--limit", "300", "--json", "name"], dry))}
    for label in sorted(wanted - existing):
        color = LABEL_COLORS.get(label, "c5def5")
        gh(["label", "create", label, "--color", color, "--force"], dry)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path, dry = sys.argv[1], "--dry-run" in sys.argv
    with open(path, encoding="utf-8") as f:
        tickets = json.load(f)

    for t in tickets:
        owners = [l for l in t.get("labels", []) if l.split(":")[0] in ("agent", "human")]
        if len(owners) != 1:
            sys.exit(f"{t['id']} must have exactly one owner label, has {owners}")

    ensure_labels(tickets, dry)
    numbers = {}
    for t in topo_order(tickets):
        body = t.get("body", "")
        deps = [f"#{numbers[d]}" if d in numbers else d for d in t.get("depends_on", [])]
        if deps:
            body += "\n\n**Depends on:** " + ", ".join(deps)
        args = ["issue", "create", "--title", f"[{t['id']}] {t['title']}", "--body", body]
        for label in t.get("labels", []):
            args += ["--label", label]
        url = gh(args, dry)
        numbers[t["id"]] = int(url.rstrip("/").rsplit("/", 1)[-1]) if url else f"<{t['id']}>"
        print(f"{t['id']:>4} -> {url or '(dry-run)'}  [{', '.join(t.get('labels', []))}]")

    if not dry:
        with open("tickets.map.json", "w", encoding="utf-8") as f:
            json.dump(numbers, f, indent=2)
        print("Saved T-id -> issue number map to tickets.map.json")


if __name__ == "__main__":
    main()
