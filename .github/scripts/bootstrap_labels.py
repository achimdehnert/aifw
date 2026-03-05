#!/usr/bin/env python3
"""Usage: python .github/scripts/bootstrap_labels.py --repo owner/repo --token $GITHUB_TOKEN"""
import argparse, requests

LABELS = [
    {"name": "bug",           "color": "d73a4a", "description": "Fehler"},
    {"name": "enhancement",   "color": "a2eeef", "description": "Neue Funktion"},
    {"name": "task",          "color": "e4e669", "description": "Technische Aufgabe"},
    {"name": "use-case",      "color": "0075ca", "description": "Use Case"},
    {"name": "adr",           "color": "7057ff", "description": "Architecture Decision"},
    {"name": "triage",        "color": "e99695", "description": "Neu, nicht bewertet"},
    {"name": "wontfix",       "color": "ffffff", "description": "Nicht umgesetzt"},
    {"name": "blocked",       "color": "ee0701", "description": "Blockiert"},
    {"name": "documentation", "color": "0075ca", "description": "Dokumentation"},
    {"name": "security",      "color": "ee0701", "description": "Sicherheitsrelevant"},
    {"name": "dependencies",  "color": "0366d6", "description": "Dependency Update"},
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {args.token}", "Accept": "application/vnd.github+json"})
    existing = {l["name"] for l in session.get(f"https://api.github.com/repos/{args.repo}/labels", params={"per_page": 100}).json()}
    for label in LABELS:
        if label["name"] in existing:
            session.patch(f"https://api.github.com/repos/{args.repo}/labels/{requests.utils.quote(label['name'])}", json=label)
            print(f"updated: {label['name']}")
        else:
            session.post(f"https://api.github.com/repos/{args.repo}/labels", json=label)
            print(f"created: {label['name']}")

if __name__ == "__main__":
    main()
