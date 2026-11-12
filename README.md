<div align="center">

<img src="icon.png" width="96" alt="Blip">

# Blip voices

Voices for [Blip](https://github.com/DoubleV840/blip), the plugin that makes Claude Code talk like an RPG character.

**[blip.ivwi.fr](https://blip.ivwi.fr)** · [Share your voice](https://github.com/DoubleV840/blip-voices/issues/new?template=submit-voice.yml)

</div>

## Use a voice

In Claude Code: `/blip voice` (menu) or `/blip voice <name>`.

## Share yours

1. One short sound, under half a second, that you made yourself: `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`…
2. Zip it.
3. Drop it in the [form](https://github.com/DoubleV840/blip-voices/issues/new?template=submit-voice.yml).

Once a maintainer approves it, it goes live on the site and in everyone's `/blip voice` menu.

<details>
<summary><b>For maintainers</b></summary>
<br>

- Label a submission `approved`: [the workflow](.github/workflows/add-voice.yml) converts the sound with ffmpeg, makes it uniform (mono, 16-bit, 22050 Hz, trimmed, at most 0.3 s, levelled), adds it to `voices/` and `catalog.json`, and closes the issue. If it can't, it says why on the issue.
- By hand: `python3 scripts/add_voice.py --name bloop --author someone --description "a wet bloop" bloop.mp3`

</details>

<sub>Code: MIT. Voices: CC0.</sub>
