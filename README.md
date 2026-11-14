<div align="center">

<img src="icon.png" width="96" alt="Blip">

# Blip voices

Voices for [Blip](https://github.com/DoubleV840/blip), the plugin that makes Claude Code talk like an RPG character.

**[blip.ivwi.fr](https://blip.ivwi.fr)** · [Share your voice](https://blip.ivwi.fr/#share)

</div>

## Use a voice

In Claude Code: `/blip voice` (menu) or `/blip voice <name>`.

## Share yours

1. One short sound, under half a second, that you made yourself. Sounds only, no videos.
2. Drop it on [blip.ivwi.fr](https://blip.ivwi.fr/#share), whatever its format (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`, `.aiff`…): you hear it as Blip will.
3. Give it a name and a theme, and share it. No account needed: a progress bar follows it until it is live, in about a minute.

Rather use GitHub? Save the `.wav` the site makes and drag it into the [form](https://github.com/DoubleV840/blip-voices/issues/new?template=submit-voice.yml); a `.mp3` or `.wav` you already have can go straight there.

It is checked automatically and, if it passes, goes live on the site and in everyone's `/blip voice` menu. A voice that three people [report](https://github.com/DoubleV840/blip-voices/issues/new?template=report-voice.yml) is removed, everywhere. Changed your mind about yours? Shared from the site, its card has a *remove* link in the browser you shared it from; shared from GitHub, [remove it](https://github.com/DoubleV840/blip-voices/issues/new?template=remove-my-voice.yml) there (only the account that shared it can).

<details>
<summary><b>For maintainers</b></summary>
<br>

- **Submissions publish themselves** ([publish-voice](.github/workflows/publish-voice.yml)) when they pass: words checked against [`scripts/blocklist.txt`](scripts/blocklist.txt) and the English and French [LDNOOBW](https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words) lists, a sound and never a video, an account at least a week old, three voices a day per person. The sound is made uniform (mono, 16-bit, 22050 Hz, trimmed, at most 0.3 s, levelled). An offensive submission is wiped, closed and locked; an unfit one is told what to fix.
- **Voices shared from the site** go through the Cloudflare Worker in [`likes/`](likes/worker.js), which keeps them in D1 and starts [site-voice](.github/workflows/site-voice.yml): the same checks (words, sound), then published, each step told back to the Worker so the site shows a progress bar. The Worker only believes that workflow (a token GitHub signs for it, OIDC). Three voices a day per person (a salted hash of their address), thirty a day for everyone. Its `GITHUB_TOKEN` secret is a fine-grained token for this repository with only *Actions: read and write*; should it expire, the site says sharing is down and points to the GitHub form.
- **Reports remove voices** ([report](.github/workflows/report.yml)): three reports from different people (accounts at least a week old), or one from a maintainer. A removed voice leaves the site, the menus, and every machine that installed it. You are notified of every report as the repository's owner.
- **Remove a voice yourself**: Actions → *Remove a voice* → Run workflow, or report it. Authors remove their own with the *Remove my voice* form. To bring one back, revert its removal commit and take its name out of `removed.json`.
- On GitHub, Settings → Moderation options → *Interaction limits* can keep brand-new accounts out for a while.
- By hand: `python3 scripts/add_voice.py --name bloop --author someone --theme cute --description "a wet bloop" bloop.mp3`, or `--remove bloop`.

</details>

<sub>Code: MIT. Voices: CC0.</sub>
