# Codex CLI

The detected local executable is the Codex app's installed CLI; the verified version
on 2026-09-18 was `0.155.0-alpha.2.6`. `codex login status` reported ChatGPT login.
Triad records only the authentication category; it does not read vendor auth files.

Settings provides Login, Logout, Refresh and installation instructions.
Logging out affects the vendor's shared local login, so the UI asks before logout.
Inherited API credential variables are removed from subprocess environments.

The installed CLI supports noninteractive `exec`, JSONL, output schema, ephemeral
sessions, explicit cwd, sandbox selection and ignoring user configuration/rules.
These options are useful vendor controls but are not proof of Triad's required
outer isolation. Native inference/README acceptance is therefore **not implemented**;
Test reports `OuterBoundaryUnavailable`, never a synthetic success.

Official references: [CLI reference](https://developers.openai.com/codex/cli/reference)
and [authentication](https://developers.openai.com/codex/auth).
