<!-- Profile shortlist. Layout stays hand-edited; marked regions are refreshed by GitHub Actions. -->

# Profile shortlist

[Working components](#working) · [Mockups & setup pending](#mockups) · [Blog layouts](#real-posts)

Original numbers are kept so we can keep referring to them. Everything is visible—no expanding sections.

<a id="working"></a>

# Working components

These components already render or refresh successfully. GitHub Actions updates the marked regions using public GitHub data and your RSS. Assets are repository-hosted; Komarev is the only separate widget service. Sample introduction copy is still yours to edit.

## 01 · Animated typing introduction

**Outlined Iosevka · sample copy.** Whole characters appear one at a time, pause, then erase one at a time. Separate light/dark lettering follows GitHub's selected theme. The glyphs are paths, so GitHub cannot substitute another font. Editable source: [`typing-iosevka.source.svg`](./profile-showcase/typing-iosevka.source.svg).

<!-- profile:typing:start -->
<a href="./profile-showcase/generated/typing-iosevka-dark.f9e360945313.svg#gh-dark-mode-only">
  <img src="./profile-showcase/generated/typing-iosevka-dark.f9e360945313.svg" alt="Typing introduction — outlined Iosevka">
</a>
<a href="./profile-showcase/generated/typing-iosevka-light.f7fdbaaf1430.svg#gh-light-mode-only">
  <img src="./profile-showcase/generated/typing-iosevka-light.f7fdbaaf1430.svg" alt="Typing introduction — outlined Iosevka">
</a>
<!-- profile:typing:end -->

## 03 · Your terminal styling

Rosé Pine Moon, your two-line Fish/Starship prompt and branch symbol, no title bar or window buttons, and a steady beam cursor.

![Undecorated Rosé Pine Moon terminal with Cosipa's two-line Starship prompt](./profile-showcase/terminal-rose-pine.svg)

<sub>Styling recreation, not a screenshot. Uses the installed IosevkaTerm Nerd Font from your Kitty/Foot setup. Glyphs are rendered as paths so font fallback cannot change the image.</sub>

## 07 · Live GitHub badges

**Public GitHub data, rendered locally.** Rounded ends, subtle shading, and text shadows matching the other flat badges.

<!-- profile:github-badges:start -->
[![followers](./profile-showcase/generated/followers.5af084097a3f.svg)](https://github.com/Cosipa?tab=followers)
[![stars](./profile-showcase/generated/stars.e7f81e54e52f.svg)](https://github.com/Cosipa/cosipa/stargazers)
[![updated](./profile-showcase/generated/updated.f79310bf7dc9.svg)](https://github.com/Cosipa/cosipa/commits)
[![repos](./profile-showcase/generated/repos.d5972ff650f6.svg)](https://github.com/Cosipa?tab=repositories)
<!-- profile:github-badges:end -->

## 18 · PGP + profile views

<!-- profile:pgp:start -->
[![PGP key](./profile-showcase/generated/pgp.d5297abf483e.svg)](https://github.com/Cosipa.gpg)
<!-- profile:pgp:end -->
[![Profile views](https://komarev.com/ghpvc/?username=Cosipa&style=flat&color=313131&label=views)](https://github.com/Cosipa)

<sub>The key ID is from the primary public key served by your GitHub `.gpg` URL. Views are approximate image requests, not unique visitors.</sub>

## 09 · Public stats card

**Your public contribution data, with explicit calendar-year dates.** Commit contributions are GitHub-eligible public commits, not every Git commit on every branch. Any published private total is labeled contributions, never commits.

<!-- profile:stats:start -->
<a href="./profile-showcase/generated/stats-dark.713c756026a7.svg#gh-dark-mode-only">
  <img src="./profile-showcase/generated/stats-dark.713c756026a7.svg" alt="Cosipa&#x27;s public GitHub contribution statistics" width="467">
</a>
<a href="./profile-showcase/generated/stats-light.5e3c4a4270bf.svg#gh-light-mode-only">
  <img src="./profile-showcase/generated/stats-light.5e3c4a4270bf.svg" alt="Cosipa&#x27;s public GitHub contribution statistics" width="467">
</a>
<!-- profile:stats:end -->

<sub>Original simple layout, GitHub-native light/dark backgrounds, and blue accents. Missing data is not presented as zero.</sub>

[Local generator](./scripts/update_profile.py) · [Counting definitions](./PROFILE_SETUP.md#counting-definitions)

## 12 · Contribution timeline

**Your publicly visible contributions over an explicit 365-day window.** The headline is checked against the sum of the daily counts. A blue/green line and shaded area show weekly totals; the green dot marks the busiest week.

<!-- profile:timeline:start -->
<a href="./profile-showcase/generated/timeline-dark.e8722b8fc2b1.svg#gh-dark-mode-only">
  <img src="./profile-showcase/generated/timeline-dark.e8722b8fc2b1.svg" alt="Cosipa&#x27;s 365-day contribution timeline">
</a>
<a href="./profile-showcase/generated/timeline-light.ded74fbfe42a.svg#gh-light-mode-only">
  <img src="./profile-showcase/generated/timeline-light.ded74fbfe42a.svg" alt="Cosipa&#x27;s 365-day contribution timeline">
</a>
<!-- profile:timeline:end -->

<sub>Publicly published private activity may be included in the graph. Light/dark variants follow GitHub's selected theme, even when it differs from your browser/OS preference.</sub>

[GitHub's own contribution calendar](https://github.com/users/Cosipa/contributions)

## 14 · Contribution snake

**Your contribution grid.** A pink snake over the normal GitHub green contribution cells, with GitHub-native light/dark backgrounds. The pinned Action generates the animation; the local renderer applies the palette from `profile.toml`.

<!-- profile:snake:start -->
<a href="./profile-showcase/generated/snake-dark.a206315f4fc5.svg#gh-dark-mode-only">
  <img src="./profile-showcase/generated/snake-dark.a206315f4fc5.svg" alt="Cosipa&#x27;s contribution snake" width="1000">
</a>
<a href="./profile-showcase/generated/snake-light.59a1d16f1a34.svg#gh-light-mode-only">
  <img src="./profile-showcase/generated/snake-light.59a1d16f1a34.svg" alt="Cosipa&#x27;s contribution snake" width="1000">
</a>
<!-- profile:snake:end -->

[Generator](https://github.com/Platane/snk)

## 24 · Open pull requests and issues

**Actual public activity, refreshed by Actions.** Up to 12 open items only, using locally stored status badges. Not an instant status check.

<!-- profile:activity:start -->
| Status | Repository | Title |
| :-- | :-- | :-- |
| ![PR open](./profile-showcase/static/badge-pr-open.svg) | `NixOS/nixpkgs` | [zap: install desktop icons](https://github.com/NixOS/nixpkgs/pull/585770) · #585770 |
| ![PR open](./profile-showcase/static/badge-pr-open.svg) | `NixOS/nixpkgs` | [fido2-manage: update to 0.2.2](https://github.com/NixOS/nixpkgs/pull/585745) · #585745 |
| ![PR open](./profile-showcase/static/badge-pr-open.svg) | `NixOS/nixpkgs` | [iproute2: 7.2.0 \-&gt; 7.3.0](https://github.com/NixOS/nixpkgs/pull/585573) · #585573 |
| ![issue open](./profile-showcase/static/badge-issue-open.svg) | `maxdorninger/MediaManager` | [\[BUG\] Prowlarr magnet redirect is discarded before Transmission grab](https://github.com/maxdorninger/MediaManager/issues/574) · #574 |
<!-- profile:activity:end -->

<a id="real-posts"></a>

## 47 · Compact magazine rows

**Live writing · cosipa.dev.** Actions refreshes this and both excerpt alternatives from [your RSS feed](https://cosipa.dev/rss), retaining exact titles, dates, and first-sentence excerpts. No rewritten headlines or generated article images.

<!-- profile:posts47:start -->
<table>
<tr>
<td width="20%" valign="top">October 18, 2026</td>
<td valign="top">

**[A user in the Docker group can become root](https://cosipa.dev/posts/docker-group-security-risk/)**

> This is a well-known (very old) Docker security risk, that everybody knows exists, yet
> sometimes we underestimate the impact of it.

</td>
</tr>
<tr>
<td width="20%" valign="top">August 5, 2026</td>
<td valign="top">

**[How to setup a pull-through Docker registry](https://cosipa.dev/posts/docker-registry-cache-setup/)**

> A pull-through Docker registry is basically just a cached proxy to DockerHub, instead
> of having your servers pulling images from DockerHub directly, they could pull them
> from your own registry.

</td>
</tr>
<tr>
<td width="20%" valign="top">July 25, 2026</td>
<td valign="top">

**[How to speed up Linux disk encryption](https://cosipa.dev/posts/full-disk-encryption-tweaks/)**

> What is dm-crypt: Device-Mapper’s crypt provides transparent encryption of block
> devices using the kernel crypto API.

</td>
</tr>
</table>
<!-- profile:posts47:end -->

## 48 · Quieter excerpt layouts

Both alternatives below are already automated. Choose 47, 48A, or 48B for the final README.

### 48A · Ordinary blockquotes

<!-- profile:posts48a:start -->
> **[A user in the Docker group can become root](https://cosipa.dev/posts/docker-group-security-risk/)** · <sub>Oct 18, 2026</sub>
>
> This is a well-known (very old) Docker security risk, that everybody knows exists, yet
> sometimes we underestimate the impact of it.

<!-- -->

> **[How to setup a pull-through Docker registry](https://cosipa.dev/posts/docker-registry-cache-setup/)** · <sub>Aug 05, 2026</sub>
>
> A pull-through Docker registry is basically just a cached proxy to DockerHub, instead
> of having your servers pulling images from DockerHub directly, they could pull them
> from your own registry.

<!-- -->

> **[How to speed up Linux disk encryption](https://cosipa.dev/posts/full-disk-encryption-tweaks/)** · <sub>Jul 25, 2026</sub>
>
> What is dm-crypt: Device-Mapper’s crypt provides transparent encryption of block
> devices using the kernel crypto API.
<!-- profile:posts48a:end -->

### 48B · Unframed excerpts

<!-- profile:posts48b:start -->
**[A user in the Docker group can become root](https://cosipa.dev/posts/docker-group-security-risk/)** · <sub>Oct 18, 2026</sub>

This is a well-known (very old) Docker security risk, that everybody knows exists, yet
sometimes we underestimate the impact of it.

---

**[How to setup a pull-through Docker registry](https://cosipa.dev/posts/docker-registry-cache-setup/)** · <sub>Aug 05, 2026</sub>

A pull-through Docker registry is basically just a cached proxy to DockerHub, instead
of having your servers pulling images from DockerHub directly, they could pull them
from your own registry.

---

**[How to speed up Linux disk encryption](https://cosipa.dev/posts/full-disk-encryption-tweaks/)** · <sub>Jul 25, 2026</sub>

What is dm-crypt: Device-Mapper’s crypt provides transparent encryption of block
devices using the kernel crypto API.
<!-- profile:posts48b:end -->

---

<a id="mockups"></a>

# Mockups & setup pending

These are **not finished personal content**. Some are visual mockups; others have working rendering but still need your content or configuration. They are kept separate from the working data above.

## 04 · Native avatar + a centered intro

**Live avatar · introduction copy still a mockup.**

<p align="center">
  <img src="https://github.com/Cosipa.png?size=160" alt="Cosipa's GitHub avatar" width="96" height="96">
</p>
<h3 align="center">Cosipa</h3>
<p align="center">A short sentence about what you build, what you care about, and why someone should stick around.</p>
<p align="center">
  <a href="https://github.com/Cosipa?tab=repositories">Projects</a> ·
  <a href="https://github.com/Cosipa?tab=stars">Things I find interesting</a> ·
  <a href="https://cosipa.dev/">Writing</a>
</p>

## 05 · Flat tool badges

**Sample stack, not an inventory of your skills.** The assets work; the list still needs your selection.

![Linux](./profile-showcase/static/badge-linux.svg)
![NixOS](./profile-showcase/static/badge-nixos.svg)
![Neovim](./profile-showcase/static/badge-neovim.svg)
![Rust](./profile-showcase/static/badge-rust.svg)
![Python](./profile-showcase/static/badge-python.svg)

## 17 · Metrics panels

**Unimplemented · upstream demos, not your account.** Metrics was explicitly excluded from the earlier Actions implementation because you planned to configure it yourself. That includes the achievement wall: no personal Metrics output or Metrics workflow has been configured here. These images are examples, not evidence of your stats or achievements.

[![Metrics example: classic profile dashboard](https://raw.githubusercontent.com/lowlighter/metrics/examples/metrics.classic.svg)](https://github.com/lowlighter/metrics)

### Achievement wall · not configured

![Metrics example: achievements, not Cosipa's achievements](https://raw.githubusercontent.com/lowlighter/metrics/examples/metrics.plugin.achievements.compact.svg)

## 19 · Repository preview card

**Placeholder.** No featured repository is selected yet.

<!-- profile:repository-placeholder:start -->
<a href="./profile-showcase/generated/repository-placeholder-dark.a543fce88cf0.svg#gh-dark-mode-only">
  <img src="./profile-showcase/generated/repository-placeholder-dark.a543fce88cf0.svg" alt="Repository preview placeholder" width="400">
</a>
<a href="./profile-showcase/generated/repository-placeholder-light.35e31349540e.svg#gh-light-mode-only">
  <img src="./profile-showcase/generated/repository-placeholder-light.35e31349540e.svg" alt="Repository preview placeholder" width="400">
</a>
<!-- profile:repository-placeholder:end -->

## 21 · Two-column project gallery

**Illustrative copy, not actual project descriptions.**

<table>
<tr>
<td width="50%" valign="top">

### 🛠️ The useful thing

One sentence explaining the problem it solves, not just the language it's written in.

![CLI](./profile-showcase/static/badge-cli.svg)
![Local first](./profile-showcase/static/badge-local-first.svg)

[Source](https://github.com/Cosipa?tab=repositories)

</td>
<td width="50%" valign="top">

### 🧪 The weird experiment

The one that exists because you wanted to understand how something works.

![Experiment](./profile-showcase/static/badge-experiment.svg)
![Work in progress](./profile-showcase/static/badge-work-in-progress.svg)

[Source](https://github.com/Cosipa?tab=repositories)

</td>
</tr>
</table>

## 22 · Release board

**Mockup · fictional projects and versions.**

| Project | Latest | What's new |
| :-- | :-- | :-- |
| `sidequest` | ![Demo version 1.4.0](./profile-showcase/static/badge-demo-version-1-4-0.svg) | Startup is no longer a coffee break. |
| `tiny-parser` | ![Demo version 0.8.2](./profile-showcase/static/badge-demo-version-0-8-2.svg) | Error messages now attempt to help. |
| `homelab-notes` | ![Demo rolling release](./profile-showcase/static/badge-demo-rolling-release.svg) | Another diagram of the same server. |

## 37 · Your own quote card

**Working renderer · temporary demo quotes.** The entries in [`quotes.txt`](./quotes.txt) are explicitly labelled placeholders, not real quotations or your words. Replace them with your own content; the workflow selects one each UTC day and renders both themes. An empty file shows an explicit setup notice.

<!-- profile:quote:start -->
<a href="./quotes.txt#gh-dark-mode-only">
  <img src="./profile-showcase/generated/quote-dark.7d44fde44d16.svg" alt="Quote card from quotes.txt">
</a>
<a href="./quotes.txt#gh-light-mode-only">
  <img src="./profile-showcase/generated/quote-light.26f3343b7b77.svg" alt="Quote card from quotes.txt">
</a>
<!-- profile:quote:end -->

<!-- profile:footer:start -->
![Decorative waving footer](./profile-showcase/static/footer-wave.svg)
<!-- profile:footer:end -->
