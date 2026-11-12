<div align="center">

<img src="icon.png" width="96" alt="Blip">

# Blip voices

Voices for [Blip](https://github.com/DoubleV840/blip), the plugin that makes Claude Code talk like an RPG character.

**[blip.ivwi.fr](https://blip.ivwi.fr)** · [Share your voice](https://github.com/DoubleV840/blip-voices/issues/new?template=submit-voice.yml)

</div>

## Use a voice

In Claude Code: `/blip voice` (menu) or `/blip voice <name>`.

## Share yours

1. One short sound, under half a second, that you made yourself: `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`… Sounds only, no videos.
2. Zip it.
3. Drop it in the [form](https://github.com/DoubleV840/blip-voices/issues/new?template=submit-voice.yml).

Once a maintainer approves it, it goes live on the site and in everyone's `/blip voice` menu.

<details>
<summary><b>For maintainers</b></summary>
<br>

- **Every submission is checked at once** ([check-voice](.github/workflows/check-voice.yml)): its words against [`scripts/blocklist.txt`](scripts/blocklist.txt) and the English and French [LDNOOBW](https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words) lists, its file (a sound, never a video), its sound. An offensive one is wiped, closed and locked; an unfit one is told what to fix; past three open submissions, a person's next ones are closed.
- **Nothing goes live until you listen to it** and label it `approved`: [add-voice](.github/workflows/add-voice.yml) makes it uniform (mono, 16-bit, 22050 Hz, trimmed, at most 0.3 s, levelled), publishes it and closes the issue.
- **Remove a voice**: Actions → *Remove a voice* → Run workflow. It leaves the site and the menus, and Blip deletes it from every machine that installed it.
- **Reports** come through the *Report a voice* form, linked from each community voice on the site.
- On GitHub, Settings → Moderation options → *Interaction limits* can keep brand-new accounts out for a while.
- By hand: `python3 scripts/add_voice.py --name bloop --author someone --theme cute --description "a wet bloop" bloop.mp3`, or `--remove bloop`.

</details>

<sub>Code: MIT. Voices: CC0.</sub>
