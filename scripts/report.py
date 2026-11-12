#!/usr/bin/env python3
"""Handles a report: counts who reported a community voice, and says when to
remove it.

In the workflow, with ISSUE_BODY, ISSUE_NUMBER, AUTHOR and ASSOCIATION in the
environment and gh signed in. Prints `key=value` lines: action (remove, count
or ignore), name, count, and issues, the reports of that voice to close.

A voice goes at once when a maintainer reports it, and otherwise once
REPORTS_NEEDED different people have, each with a GitHub account at least
MIN_ACCOUNT_DAYS old, so that throwaway accounts do not count.
"""

import datetime
import json
import os
import subprocess

from add_voice import MIN_ACCOUNT_DAYS, NAME, VOICES, fields_of

REPORTS_NEEDED = 3
MAINTAINERS = {"OWNER", "MEMBER", "COLLABORATOR"}


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def reported(body):
    """The voice a report names, as typed or as `/blip voice <name>`."""
    voice = fields_of(body).get("voice", "").strip().lower()
    return voice.removeprefix("/blip voice ").strip().strip("`")


def is_old_enough(login):
    created = json.loads(gh("api", f"users/{login}"))["created_at"]
    born = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
    return datetime.datetime.now(datetime.timezone.utc) - born >= datetime.timedelta(days=MIN_ACCOUNT_DAYS)


def main():
    name = reported(os.environ.get("ISSUE_BODY", ""))
    if not NAME.match(name) or not (VOICES / name).is_dir():
        print(f"action=ignore\nname={name if NAME.match(name) else ''}")
        return

    repo = os.environ["GITHUB_REPOSITORY"]
    issues = json.loads(gh("issue", "list", "--repo", repo, "--state", "all", "--limit", "1000", "--json", "number,author,title,body"))
    reports = [i for i in issues if i["title"].startswith("Report") and reported(i["body"]) == name]
    # The report that started this run, should the list not have it yet.
    reports.append({"number": int(os.environ["ISSUE_NUMBER"]), "author": {"login": os.environ["AUTHOR"]}})

    reporters = {r["author"]["login"] for r in reports}
    counted = {login for login in reporters if is_old_enough(login)}
    is_maintainer = os.environ.get("ASSOCIATION", "") in MAINTAINERS
    action = "remove" if is_maintainer or len(counted) >= REPORTS_NEEDED else "count"
    numbers = " ".join(sorted({str(r["number"]) for r in reports}))
    print(f"action={action}\nname={name}\ncount={len(counted)}\nissues={numbers}")


if __name__ == "__main__":
    main()
