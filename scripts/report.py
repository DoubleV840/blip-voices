#!/usr/bin/env python3
"""Handles a report: counts who reported a community voice, and says when to
remove it. Handles a removal too, asked by whoever shared the voice.

In the workflow, with ISSUE_BODY, ISSUE_NUMBER, AUTHOR and ASSOCIATION in the
environment and gh signed in. Prints `key=value` lines: action (remove, count,
refuse or ignore), name, count, and issues, the reports of that voice to close.

A voice goes at once when a maintainer reports it, and otherwise once
REPORTS_NEEDED different people have, each with a GitHub account at least
MIN_ACCOUNT_DAYS old, so that throwaway accounts do not count. Its author, or
a maintainer, removes it at once with the "Remove my voice" form.
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


def is_removal(body):
    return "voice to remove" in fields_of(body)


def reported(body):
    """The voice a report or a removal names, as typed or as `/blip voice <name>`."""
    fields = fields_of(body)
    voice = fields.get("voice to remove" if is_removal(body) else "voice", "").strip().strip("`").lower()
    return voice.removeprefix("/blip voice ").strip()


def author_of(name):
    """The GitHub account that shared a voice; none for a voice shared from
    the site, whose author is only a name (its sharer removes it from there)."""
    meta = json.loads((VOICES / name / "voice.json").read_text())
    return "" if meta.get("source") == "site" else meta.get("author", "")


def is_old_enough(login):
    created = json.loads(gh("api", f"users/{login}"))["created_at"]
    born = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
    return datetime.datetime.now(datetime.timezone.utc) - born >= datetime.timedelta(days=MIN_ACCOUNT_DAYS)


def main():
    body = os.environ.get("ISSUE_BODY", "")
    name = reported(body)
    if not NAME.match(name) or not (VOICES / name).is_dir():
        print(f"action=ignore\nname={name if NAME.match(name) else ''}")
        return

    repo = os.environ["GITHUB_REPOSITORY"]
    issues = json.loads(gh("issue", "list", "--repo", repo, "--state", "all", "--limit", "1000", "--json", "number,author,title,body"))
    reports = [i for i in issues if i["title"].startswith("Report") and reported(i["body"]) == name]
    # The report that started this run, should the list not have it yet.
    reports.append({"number": int(os.environ["ISSUE_NUMBER"]), "author": {"login": os.environ["AUTHOR"]}})

    numbers = " ".join(sorted({str(r["number"]) for r in reports}))
    is_maintainer = os.environ.get("ASSOCIATION", "") in MAINTAINERS

    if is_removal(body):
        author = author_of(name)
        is_own = bool(author) and os.environ["AUTHOR"].lower() == author.lower()
        print(f"action={'remove' if is_own or is_maintainer else 'refuse'}\nname={name}\nissues={numbers}")
        return

    reporters = {r["author"]["login"] for r in reports}
    counted = {login for login in reporters if is_old_enough(login)}
    action = "remove" if is_maintainer or len(counted) >= REPORTS_NEEDED else "count"
    print(f"action={action}\nname={name}\ncount={len(counted)}\nissues={numbers}")


if __name__ == "__main__":
    main()
