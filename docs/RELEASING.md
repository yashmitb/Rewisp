# Releasing — two channels

Rewisp has two update channels, controlled entirely by GitHub's `prerelease`
flag (the standard pattern). The client (`UpdateChecker.swift`) picks where to
look:

| Channel | Who | Endpoint | Sees |
|---|---|---|---|
| **Stable** (default) | everyone | `/releases/latest` | newest **non**-prerelease |
| **Developer** (opt-in) | testers who turn it on in **Settings → Help → Developer updates** | `/releases` | newest by semver, **including** prereleases |

Version comparison is semver-aware: `0.28.0-dev.1 < 0.28.0`. So a dev tester is
offered `-dev.N` builds first and then rolls onto the plain stable build
automatically once it ships (a release outranks every `-dev.N` of the same core).

## Dev (pre-release) build — testers only

```
scripts/release_dev.sh 0.28.0-dev.1 ["notes"]
```

Builds a DMG whose bundle version carries the `-dev.N` suffix (via
`REWISP_VERSION`), then cuts a **`--prerelease`** GitHub release with only the
versioned DMG. Stable users are untouched — `/releases/latest` and the
landing-page download link skip prereleases. Bump `-dev.2`, `-dev.3`, … for each
iteration.

## Public build — everyone

Run the normal release flow (`updateandpush`): bump to a plain `0.28.0`, cut a
**non**-prerelease release with both `Rewisp-0.28.0.dmg` and the stable-name
`Rewisp.dmg`. That becomes `/releases/latest` for everyone, and dev testers move
onto it automatically.

## Bootstrap note

The developer channel only exists in builds that contain this feature (v0.27.2+).
A tester on an older build must update to a build that has the toggle **once**
(via a normal stable update, or by installing a dev DMG by hand) before the
channel switch appears.

## Guardrails

- Never upload the stable-name `Rewisp.dmg` to a prerelease — it's the stable
  channel's fixed-name anchor and the landing-page link.
- Keep one prerelease label (`-dev.N`) and only bump the number, so builds order
  numerically and never hit semver's ASCII-ordering of mixed labels.
