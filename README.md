<div align="center">

<img src="icon.png" width="96" alt="Blip">

# Blip voices

Voices for [Blip](https://github.com/DoubleV840/blip), the plugin that makes Claude Code talk like an RPG character.

**[blip.ivwi.fr](https://blip.ivwi.fr)** · [Share your voice](https://github.com/DoubleV840/blip-voices/issues/new?template=submit-voice.yml)

</div>

## Use a voice

In Claude Code: `/blip voice` (menu) or `/blip voice <name>`.

## Share yours

1. One short sound, under half a second, that you made yourself. Sounds only, no videos.
2. Drop it on [blip.ivwi.fr](https://blip.ivwi.fr/#share), whatever its format (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`, `.aiff`…): you hear it as Blip will, and save it as a `.wav`.
3. Drag that `.wav` into the [form](https://github.com/DoubleV840/blip-voices/issues/new?template=submit-voice.yml). A `.mp3` or `.wav` you already have can go straight there.

It is checked automatically and, if it passes, goes live within minutes on the site and in everyone's `/blip voice` menu. A voice that three people [report](https://github.com/DoubleV840/blip-voices/issues/new?template=report-voice.yml) is removed, everywhere. Changed your mind about yours? [Remove it](https://github.com/DoubleV840/blip-voices/issues/new?template=remove-my-voice.yml): only the account that shared it can, and it goes at once.

<details>
<summary><b>For maintainers</b></summary>
<br>

- **Submissions publish themselves** ([publish-voice](.github/workflows/publish-voice.yml)) when they pass: words checked against [`scripts/blocklist.txt`](scripts/blocklist.txt) and the English and French [LDNOOBW](https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words) lists, a sound and never a video, an account at least a week old, three voices a day per person. The sound is made uniform (mono, 16-bit, 22050 Hz, trimmed, at most 0.3 s, levelled). An offensive submission is wiped, closed and locked; an unfit one is told what to fix.
- **Reports remove voices** ([report](.github/workflows/report.yml)): three reports from different people (accounts at least a week old), or one from a maintainer. A removed voice leaves the site, the menus, and every machine that installed it. You are notified of every report as the repository's owner.
- **Remove a voice yourself**: Actions → *Remove a voice* → Run workflow, or report it. Authors remove their own with the *Remove my voice* form. To bring one back, revert its removal commit and take its name out of `removed.json`.
- On GitHub, Settings → Moderation options → *Interaction limits* can keep brand-new accounts out for a while.
- By hand: `python3 scripts/add_voice.py --name bloop --author someone --theme cute --description "a wet bloop" bloop.mp3`, or `--remove bloop`.

</details>

<sub>Code: MIT. Voices: CC0.</sub>
