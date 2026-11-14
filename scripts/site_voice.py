#!/usr/bin/env python3
"""Talks with the site's Worker (likes/worker.js) for site-voice.yml: fetches
a voice shared from the site, and tells the site how far it is.

    python3 scripts/site_voice.py fetch ID DIR    # submission.json + sound.wav in DIR
    python3 scripts/site_voice.py status ID publishing
    python3 scripts/site_voice.py status ID live --name NAME --version VERSION
    python3 scripts/site_voice.py status ID refused --reason "why"

Fetching it tells the site it is being checked. The Worker believes these
calls because of the token they show: one GitHub signs for this repository's
site-voice workflow (OIDC), asked for with the ACTIONS_ID_TOKEN_REQUEST_*
variables the job's `id-token: write` permission sets.
"""

import argparse
import base64
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

WORKER = os.environ.get("BLIP_WORKER", "https://blip-likes.ivwi.workers.dev")
AUDIENCE = "blip-likes"
ID = re.compile(r"^[0-9a-f-]{36}$")


def token():
    """A token GitHub signs for this run of the workflow, for the Worker."""
    url = f"{os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']}&audience={urllib.parse.quote(AUDIENCE)}"
    request = urllib.request.Request(url, headers={"Authorization": f"bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["value"]


def call(path, body=None):
    request = urllib.request.Request(
        f"{WORKER}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json", "User-Agent": "blip-voices"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch(id, folder):
    submission = call(f"/voices/{id}/submission")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sound.wav").write_bytes(base64.b64decode(submission.pop("wav")))
    (folder / "submission.json").write_text(json.dumps(submission, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    fetching = commands.add_parser("fetch")
    fetching.add_argument("id")
    fetching.add_argument("folder", type=Path)
    status = commands.add_parser("status")
    status.add_argument("id")
    status.add_argument("status", choices=["publishing", "live", "refused"])
    status.add_argument("--reason", default="")
    status.add_argument("--name", default="")
    status.add_argument("--version", default="")
    args = parser.parse_args()

    if not ID.match(args.id):
        parser.error("the id is the one the Worker gave")
    if args.command == "fetch":
        fetch(args.id, args.folder)
    else:
        call(f"/voices/{args.id}/status", {"status": args.status, "reason": args.reason, "name": args.name, "version": args.version})


if __name__ == "__main__":
    main()
