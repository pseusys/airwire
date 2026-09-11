# Image texture synthesis: smooth canvas blending (graph-cut seams + border compositing)

> **Status:** implemented and kept, with one pivot mid-implementation: graph-cut seam-finding and
> Poisson blending (§5's original phase 2 plan) were scoped and rejected once re-measuring the
> core-region safety margin showed a 1px overlap band leaves neither technique room to show its
> real advantage -- see `memory/rejected-ideas.md`'s new entry.
> Shipped plain linear feathering
> instead, same core/border architecture, confirmed via an isolated visual comparison to
> meaningfully soften `value_noise`/`voronoi`; `reaction_diffusion`'s change is negligible,
> consistent with its much tighter margin.
> See the 2026-09-10 CHANGELOG.md entry for the full
> evidence.
> Ported to `web-demo/` the same day, verified live in a browser -- see the
> CHANGELOG.md entry's "Ported to `web-demo/`" paragraph.

## 1. Problem

The scattered-anchor redesign (2026-09-09) removed the periodic row-banding artifact, but each gap
cell is still an independently-scored discrete choice among a small candidate palette, so
individual patches can still visibly mismatch their neighbors -- confirmed by generating real
sample images via `poetry poe demo` and inspecting them directly.
The user wants the canvas to
read as one continuous image rather than a grid of discrete tiles, and asked for literature-backed
approaches rather than a naive "leave gaps and fill with gradient" scheme (which wastes canvas
space on non-bit-carrying filler).

## 2. Research

Real, established techniques for making patch-based texture synthesis seams invisible:
graph-cut
seam placement (Kwatra et al., "GraphCut Textures: Image and Video Synthesis Using Graph Cuts"),
Poisson/gradient-domain blending (Perez, Gangnet, Blake, "Poisson Image Editing"), and classic
min-cost-seam quilting (Efros & Freeman, "Image Quilting for Texture Synthesis and Transfer" --
already this project's own cited prior art via the `OVERLAP` rejected-ideas.md entry).

## 3. Hard constraint and the actual unlock

`core/sources/arithmetic.py`'s coder is unmodified; every step stays a `(candidate, weight)` list,
secret bits pick an index.
The blocker for any blending: decode currently identifies which patch
was placed via `PatchLibrary.index_of`, an **exact** byte-for-byte match against rendered pixels --
blending changes pixel values, which breaks that.

**The unlock, refined from the first pass:** rather than fuzzy-matching an entire patch (which
needs a safety margin across every pixel), blending is confined to a thin border band near each
patch's edges.
Decode matches only the **core** (interior, minus the blended border) exactly
against the library, unchanged in spirit from today's mechanism -- just over a smaller footprint.
This keeps today's fail-closed tamper detection fully intact on the interior of every patch, and
bounds exactly how far any pixel can move (only ever within the border band).

## 4. Measured: safety margin varies hugely by flavor

Minimum pairwise squared-pixel distance between any two distinct candidates in each flavor's
default (stride=`patch_size`) library, fixed seed:

| Flavor | Library size | Min RMS distance (per pixel-channel, out of 255) |
| --- | --- | --- |
| `value_noise` | 256 | ~18 |
| `voronoi` | 256 | ~5 |
| `reaction_diffusion` | 168 | ~0.07 (!) |

`reaction_diffusion` already has two candidates differing by a single color unit in a single
pixel -- today's exact-byte dedup only removes byte-identical duplicates, not near-duplicates, and
this flavor is mostly two-tone, so near-duplicates are common.
No blending is safe there without
first widening what counts as "distinct."

## 5. Design

### Phase 1: widened dedup (minimum-distance candidate library)

Same mechanism as `_anchor_mask`'s dart-throwing, applied to patch selection: walk stride-spaced
candidates in order, accept a candidate only if it's at least `MIN_CANDIDATE_DISTANCE` (squared
pixel distance) from *every* already-accepted candidate, reject (merge) otherwise.

Fully safe and
independently measurable on its own: encode still renders the exact, literal content of whichever
library patch was chosen, so today's exact-match decode keeps working completely unchanged --
nothing about rendered pixels changes in this phase.
`PatchLibrary` also needs to remember each
accepted patch's source texture offset (not just its content), which phase 2 needs for re-cropping
an extended footprint at render time.

Expected trade-off, to be measured not assumed: `reaction_diffusion`'s library (168, many
near-duplicates) shrinks the most once genuinely-close candidates merge -- fewer distinct
candidates per gap cell means fewer bits per cell, so this flavor's compression efficiency will
measurably worsen.
`value_noise` should barely shrink (already well-separated).

### Phase 2: graph-cut seam + border compositing

1. After the entire index grid is decided (today's coder/selection loop, completely unchanged), a
   separate rendering pass re-crops each chosen candidate **larger** than `patch_size` (extended by
   `SEAM_OVERLAP` pixels per side, using the source offset phase 1 now tracks), giving adjacent
   patches real pixel overlap to seam through -- today's patches are non-overlapping tiles with no
   overlap to work with otherwise.
2. For each patch-to-patch adjacency, find a minimum-cost seam through the shared overlap strip via
   dynamic programming (cheapest cumulative-color-difference path, Kwatra-style), then composite
   each side of the seam from its own patch.
3. **Anchors stay pixel-for-pixel exact, always** -- only gap patches are touched, and only within
   their own boundary band.
This keeps the "ground truth" backbone of the whole image fully intact
   (every other gap cell's position-guided scoring still targets real, untouched content), and
   anchor decoding needs no change.
4. Decode extracts each gap cell's core (interior, minus the blended border) and exact-matches it
   against the library's corresponding core signature.
The phase 1 minimum-distance guarantee must
   be **re-verified specifically over this smaller core region** (a subset of a well-separated
   patch is usually still well-separated, but that's a measurement, not an assumption).

**Fallback, if the seam DP or gradient blending proves too complex to get right reliably:** the
same core/border architecture survives -- only the border-filling step changes, from "optimal
seam plus gradient blend" to plain linear feathering across the band.
Nothing else in the design
changes.

## 6. What does not change

The arithmetic coder, the wire format, `attractor`'s row-alternating mechanism (out of scope --
already has no positional structure to exploit; this whole redesign is about the three
position-guided flavors), the anchor-mask/scattered-layout mechanism from the prior redesign.

## 7. Measurement and rollback plan

Same methodology as both prior experiments this session:

- Phase 1 alone: round-trip correctness unchanged (still exact-match, unblended); library size and
  effective bits-per-cell before/after, per flavor.
- Phase 2: round-trip correctness with the core-only exact match; the re-verified core-region
  minimum-distance margin; direct visual comparison (upscaled PNG, before/after) specifically
  checking whether patch boundaries actually become less visible; a wall-clock cost check (seam DP
  and any gradient blending run once per adjacency, per message).
- If a technique doesn't hold up (correctness breaks, margin is too thin, or it doesn't look
  meaningfully better), fall back per the plan above, and record the outcome in
  `memory/rejected-ideas.md`, same as the prior `OVERLAP` and overlapping-candidate findings.
