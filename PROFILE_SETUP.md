# Profile automation

The existing `test.md` layout is hand-maintained. Only content between
`<!-- profile:NAME:start -->` / `<!-- profile:NAME:end -->` markers is generated.
The terminal image is unchanged. `README.md` is not an output.

`test.md` separates **Working components** from **Mockups & setup pending**.
The latter includes Metrics/achievements (not configured), project placeholders,
sample intro/tool copy, and quotes awaiting your content. Blog alternatives 47,
48A, and 48B are automated; the old cards and TIP-callout alternatives are removed.

## What runs

`.github/workflows/profile.yml` runs every six hours, on relevant pushes to
`main`, or manually from **Actions → Refresh profile → Run workflow**.

1. Check out the repository and install the exact Python version in `.python-version`.
2. Run the offline unit tests.
3. When the profile repository is public, run the SHA-pinned `Platane/snk/svg-only`
   Action for **Cosipa's** contribution grid. It is deferred in a private preview
   repository so that its repository token cannot accidentally expose non-public activity.
4. Fetch public GitHub API data, the unauthenticated public contribution calendar,
   and `https://cosipa.dev/rss` using Python's standard library.
5. Generate local SVGs and refresh only the marked Markdown blocks. Apply the
   Rosé Pine Moon / Dawn palettes from `profile.toml` to stats, timeline, and snake.
   Snake backgrounds and contrasting rose heads are themed locally, including
   cached animations when the Action cannot produce a fresh one.
6. Commit changed generated files using GitHub's built-in `GITHUB_TOKEN`.

No PAT, package installation, separate account, or rendering server is needed.
Metrics is intentionally **not** installed; its two upstream demo images remain
labeled as demos for you to configure separately.

The only separately hosted widget is **Komarev**. GitHub serves the avatar,
PGP key, upstream Metrics examples, and all local assets. Your blog supplies RSS.
Static tool badges and the footer wave are vendored SVG snapshots; source URLs
and SHA-256 checksums are in `profile-showcase/static/provenance.json`. Those hosts
are not queried by the workflow or by visitors. Locally generated badges use the
same rounded clipping, subtle gradient, and text-shadow treatment as Shields flat.
The decorative header wave is removed.

The typing introduction is a local SVG exported with **outlined IosevkaTerm Nerd
Font** glyphs. Merely specifying a font family does not make that font available
inside a GitHub image. Outlining prevents fallback without adding a font/tool
installation to Actions. Its animation is preserved.

Generated SVG filenames include their content hash. Updating data changes the
image URL to avoid displaying an older image through GitHub's cache. The
workflow removes obsolete generated hashes, not hand-maintained assets.

## Initial activation

Push the implementation, then let **Refresh profile** finish. The repository
must allow Actions and the workflow's `contents: write` permission. Protected
branches/rulesets that disallow bot commits require an explicit exception or a
future pull-request publishing setup; the workflow never force-pushes.

Until the first authenticated run, stats show an explicit pending notice,
**not** fabricated zeros or the old third-party commit count. The snake is also
pending until this profile repository is public and its Action succeeds. The
built-in token is automatically supplied in Actions; do not create or paste a
PAT for this setup. Public-only stats exclude private repositories even if the
token can read this preview repository. Its own stars/update badges say
“unavailable” when that repository's metadata is not public.

Source failures retain the last successful component in `.profile-data/public.json`
and produce a workflow warning/summary. Empty or invalid RSS cannot erase posts.
Stats display the date through which their cached data is valid. If an old
calendar year's data survives a failure after January 1, it is not mislabeled as
the new year's total. Scheduled workflows may be delayed and GitHub may disable
schedules in inactive public repositories; manual runs still work.

## Counting definitions

- **Public commit contributions:** commit contributions in explicitly public
  repositories returned by GitHub's contribution API, from January 1 at 00:00 UTC
  through the request time. These are GitHub-profile-eligible commits, not every
  Git commit on every branch. No inferred or search-index-based commit total.
- **Public PRs, issues, and reviews:** the same explicit calendar-year window.
  Their repository breakdowns are filtered to public repositories too; the token's
  ability to read this preview repository cannot inflate the public counters.
- **Published restricted contributions:** GitHub's `restrictedContributionsCount`,
  only when it exposes a positive anonymized total. This covers **all contribution
  types** in private repositories inaccessible to this token, not necessarily
  every private contribution and never a private commit count. Zero cannot
  distinguish hidden activity from none, so the card says “Not published / none.”
  No private repository names, messages, or identities are requested or saved.
- **Timeline:** exactly 365 UTC calendar dates ending today, read **without a
  token** from the public GitHub calendar so privacy settings are respected. The
  public grid's headline is checked against all its daily cells; our total is then
  summed over the exact 365 dates. GitHub rounds its own grid to weeks, so its
  headline can include a few extra days. Missing days are never zero-filled.
  Private activity is included only when GitHub publishes it. A GitHub markup
  change fails safely, retaining the last successful graph.
- **Activity table:** the 12 most recently updated open public PRs/issues found
  through explicit `is:public is:open` searches. Closed items are excluded.
- **Views:** Komarev's approximate image requests, not unique visitors. An Actions
  workflow cannot independently count visits to your GitHub profile.

GitHub's own contribution eligibility and public visibility rules still apply.
A truncated API response is treated as a failure rather than an incomplete total.

## Edit your content

- `profile.toml`: username, light/dark palettes, feed URL, displayed post counts,
  and public PGP fingerprint. Each palette includes five snake contribution
  levels in `dots`; `rose` colours its head. The tool-badge stack is still demo copy.
- `profile-showcase/typing-iosevka.source.svg`: editable typing-introduction copy.
  After changing it, export with the exact **IosevkaTerm Nerd Font** installed:
  ```sh
  inkscape profile-showcase/typing-iosevka.source.svg --export-text-to-path \
    --export-plain-svg --export-filename=profile-showcase/static/typing-iosevka.svg
  sha256sum profile-showcase/static/typing-iosevka.svg
  ```
  Update its SHA-256 in `profile-showcase/static/provenance.json`, then run the
  offline generator. Font outlining is a one-time authoring step, not a workflow
  dependency. Ensure the exported SVG retains animation and has no `<text>` nodes.
- `quotes.txt`: one quote per line; optional attribution after a literal **TAB**.
  Blank lines and lines starting with `#` are ignored. Selection is deterministic
  for a UTC day. There are no supplied/random quotes or invented attributions.
  An empty file shows an explicit configuration notice.
- Blog titles and dates come from RSS. Excerpts are contiguous first sentences of
  the first paragraph, with HTML converted to text and whitespace normalized.
  There are no rewritten titles, generated summaries, or article images.
- Project cards/gallery/release rows remain explicitly labeled placeholders.
- Edit prose and layout outside the generated markers normally. Do not remove or
  duplicate markers. The generator fails instead of guessing where to write.

## Local checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/update_profile.py --check
python3 scripts/update_profile.py --offline
```

`--check` does not write files or use the network. `--offline` regenerates from
cached public data only. To refresh RSS/public REST data locally:

```sh
python3 scripts/update_profile.py
```

Without `GITHUB_TOKEN`, GraphQL contribution data is retained from the cache or
shown as pending. The scheduled workflow supplies its own token automatically.
Network errors do not turn missing data into zero counts.

## Updates and Renovate

All Actions are pinned to reviewed commit SHAs, with release-version comments;
Python is pinned to an exact patch version. There are no third-party Python
packages. `renovate.json` manages GitHub Actions pins and `.python-version`, opens
PRs instead of auto-merging, and waits three days after ordinary releases.

**The config alone does not start a bot.** If Renovate is not already enabled,
install/approve the Renovate GitHub App for this repository. This uses your
existing GitHub account; this repository does not store a Renovate PAT. The bot
will then open onboarding/dependency PRs. No GitHub CLI or App authorization is
performed by these scripts.

PR validation is a separate read-only workflow with no publishing steps. Public
feed/API text is escaped as data; it is never interpolated into shell commands.
