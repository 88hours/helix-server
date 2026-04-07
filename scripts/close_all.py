"""
Close all open issues and pull requests, and delete all branches (except the
default branch) in a GitHub repository.

Usage:
    python scripts/close_all.py owner/repo

The script reads GITHUB_TOKEN from the environment (or a .env file in the
repo root).  PRs are closed first (they are also issues, so closing the PR
via the pulls API is enough — the corresponding issue entry closes too).

Dry-run mode prints what would be closed/deleted without making any changes:
    python scripts/close_all.py owner/repo --dry-run
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Load .env if python-dotenv is available, otherwise fall back to manual parse
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        return
    except ImportError:
        pass
    # Manual fallback: parse KEY=value lines
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#")[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _paginate(url: str, token: str, params=None) -> list:
    """Fetch all pages from a GitHub list endpoint."""
    results = []
    params = {**(params or {}), "per_page": 100, "page": 1}
    while True:
        resp = requests.get(url, headers=_headers(token), params=params)
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        results.extend(page)
        if len(page) < 100:
            break
        params["page"] += 1
        time.sleep(0.1)  # stay well under rate limits
    return results


def close_prs(repo: str, token: str, dry_run: bool) -> int:
    """Close all open pull requests. Returns count closed."""
    url = f"https://api.github.com/repos/{repo}/pulls"
    prs = _paginate(url, token, {"state": "open"})
    for pr in prs:
        number = pr["number"]
        title = pr["title"]
        if dry_run:
            print(f"  [dry-run] would close PR #{number}: {title}")
        else:
            resp = requests.patch(
                f"https://api.github.com/repos/{repo}/pulls/{number}",
                headers=_headers(token),
                json={"state": "closed"},
            )
            resp.raise_for_status()
            print(f"  closed PR #{number}: {title}")
            time.sleep(0.1)
    return len(prs)


def close_issues(repo: str, token: str, dry_run: bool) -> int:
    """Close all open issues (excluding PRs, which are handled separately)."""
    url = f"https://api.github.com/repos/{repo}/issues"
    all_issues = _paginate(url, token, {"state": "open"})
    # GitHub returns PRs as issues — filter them out
    issues = [i for i in all_issues if "pull_request" not in i]
    for issue in issues:
        number = issue["number"]
        title = issue["title"]
        if dry_run:
            print(f"  [dry-run] would close issue #{number}: {title}")
        else:
            resp = requests.patch(
                f"https://api.github.com/repos/{repo}/issues/{number}",
                headers=_headers(token),
                json={"state": "closed"},
            )
            if resp.status_code == 403:
                print(f"  skipped issue #{number} (forbidden — token lacks issues:write)")
                continue
            resp.raise_for_status()
            print(f"  closed issue #{number}: {title}")
            time.sleep(0.1)
    return len(issues)


def delete_branches(repo: str, token: str, dry_run: bool) -> int:
    """Delete all branches except the default branch. Returns count deleted."""
    # Get default branch name
    resp = requests.get(f"https://api.github.com/repos/{repo}", headers=_headers(token))
    resp.raise_for_status()
    default_branch = resp.json()["default_branch"]

    url = f"https://api.github.com/repos/{repo}/branches"
    branches = _paginate(url, token)
    deleted = 0
    for branch in branches:
        name = branch["name"]
        if name == default_branch:
            continue
        if dry_run:
            print(f"  [dry-run] would delete branch: {name}")
        else:
            resp = requests.delete(
                f"https://api.github.com/repos/{repo}/git/refs/heads/{name}",
                headers=_headers(token),
            )
            if resp.status_code == 403:
                print(f"  skipped branch (forbidden): {name}")
                continue
            if resp.status_code == 422:
                print(f"  skipped branch (protected): {name}")
                continue
            resp.raise_for_status()
            print(f"  deleted branch: {name}")
            time.sleep(0.1)
        deleted += 1
    return deleted


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Close all open PRs and issues in a GitHub repo.")
    parser.add_argument("repo", help="Repository in owner/name format, e.g. acme/backend")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be closed without making changes")
    parser.add_argument("--token", help="GitHub token to use (overrides GITHUB_TOKEN env var)")
    args = parser.parse_args()

    if args.repo.count("/") != 1:
        print(f"error: repo must be in owner/name format, got: {args.repo!r}", file=sys.stderr)
        sys.exit(1)

    _load_dotenv()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("error: GITHUB_TOKEN not set (or pass --token)", file=sys.stderr)
        sys.exit(1)

    dry = args.dry_run
    prefix = "[dry-run] " if dry else ""
    print(f"{prefix}Closing all open PRs and issues in {args.repo}…\n")

    print("Pull requests:")
    pr_count = close_prs(args.repo, token, dry)
    print(f"  → {pr_count} PR(s) {'would be ' if dry else ''}closed\n")

    print("Issues:")
    issue_count = close_issues(args.repo, token, dry)
    print(f"  → {issue_count} issue(s) {'would be ' if dry else ''}closed\n")

    print("Branches:")
    branch_count = delete_branches(args.repo, token, dry)
    print(f"  → {branch_count} branch(es) {'would be ' if dry else ''}deleted\n")

    print(f"Done. {pr_count + issue_count + branch_count} item(s) total.")


if __name__ == "__main__":
    main()
