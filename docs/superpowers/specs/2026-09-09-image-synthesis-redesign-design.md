# Image texture synthesis redesign — position-indexed guide texture

> **Status:** implemented and kept.
> Measured results (seam MSE, a new "guide fidelity"
> metric, and direct visual comparison) confirmed the design for `value_noise`, `voronoi`, and
> `reaction_diffusion`; `attractor` kept its original mechanism as planned in §3 point 5.
> See the
> 2026-09-09 CHANGELOG.md entry ("Image disguise scores gap-row patches against the texture's true
> content") for the full evidence, and TODO.md's completed-items table (D13 done, D3 closed as
> superseded).

## 1. Problem

TODO D13 in `TODO.md` asked whether the image disguise
(`core/sources/synthesis.py`) could generate a whole canvas that reads as one
continuous image, instead of a patchwork of independently-chosen 8x8 patches.
Investigating it surfaced two distinct causes, confirmed by direct visual
inspection (see below), not just the already-documented one:

1. **A real alignment bug, not a design trade-off.**
   `DEFAULT_TEXTURE_SIZE=64` with `DEFAULT_PATCH_SIZE=8` gives a texture that
   is only 8 patches wide, but `DEFAULT_CANVAS_WIDTH=16` renders 16 patches
   per row.
`_seed_index` (`core/sources/synthesis.py:94-95`) walks the patch
   library as a flat, modulo-wrapped 1-D list, so every seed row actually
   concatenates two unrelated texture rows side by side.
Confirmed visually:
   rendering with the mismatched sizes shows a sharp vertical seam straight
   down the middle of every row, including seed rows (the ones meant to be
   "known-good" reference content, carrying no secret bits at all).
   Regenerating with a 128px texture (so texture-width-in-patches equals
   `canvas_width`) makes the seam disappear completely.
2. **The already-documented local-only gap-row problem.**
`_candidate_weights`
   only scores a candidate patch against its immediate neighbors (the seed
   rows directly above/below, and the already-placed gap patch to the left)
   — never against anything resembling "what should actually be here."
   Large-scale structure (Voronoi's flat cells, reaction-diffusion's
   continuous tubes) doesn't survive because there is no signal that spans
   more than one patch.
The reverted `OVERLAP` experiment (widen the comparison
   window) already showed that tweaking this local-only cost function
   further does not help — see `memory/rejected-ideas.md`.

## 2. Hard constraints (unchanged)

- Exact bit-for-bit invertibility: `decode()` must recover the original
  ciphertext using only the same public source texture both ends already
  regenerate from a shared seed.
Nothing added here may weaken that.
- The arithmetic coder (`core/sources/arithmetic.py`) is unmodified.
Every
  encoding decision stays a step producing a `(candidate, weight)` list,
  consuming some bits via `candidate_ranges`/`common_leading_bits`, exactly
  as today.
- `decode()` identifies which patch was chosen via `PatchLibrary.index_of`
  (exact byte match).
Any new cost term must be a pure function of position
  and the shared seed — never of secret data — so decode can recompute the
  identical candidate/weight list independently, the same way it already
  does for the existing edge-cost term.

## 3. Design

**Unifying principle:** every row of the canvas — seed or gap — corresponds
to a real, specific row of one continuous, periodic source texture.
Seed
rows already render that row's true content (today, via a buggy index).
Gap
rows currently have no notion of "what should really be here" at all.
Give
them one, using the same texture already used for seed rows and the patch
palette — no second texture, no extra generation cost.

1. **Alignment fix (foundation).**
   Set `DEFAULT_TEXTURE_SIZE` to the product of `DEFAULT_CANVAS_WIDTH` and
   `DEFAULT_PATCH_SIZE` (128, not 64), so the source texture is exactly as
   wide, in patches, as the canvas.
2. **Make the texture periodic in both directions**, so it covers a canvas
   of any height (payload length varies, and is not known upfront) by
   tiling, rather than by generating an oversized texture speculatively or
   regenerating mid-encode:
   - `reaction_diffusion`: no change needed.
Confirmed by direct 2x2-tile
     test: its Laplacian already uses `np.roll`, i.e. the simulation domain
     is already toroidal, so any generated texture is already exactly
     self-tileable.
   - `voronoi`: confirmed by the same tile test to show a hard seam (cell
     assignment doesn't wrap).
Fix: compute nearest-cell distance against the
     periodic images of each seed point (the standard toroidal-Voronoi
     technique), not just their raw coordinates.
   - `value_noise`: confirmed to show a subtler seam (interpolation grid
     isn't wrapped).
Fix: index the coarse grid modulo its size instead of
     padding it.
   - `attractor`: confirmed to have no exploitable 2-D positional
     continuity at all — it's a sparse density histogram of a chaotic
     orbit, not a spatially-generated field.
No periodicity work attempted;
     see the fallback in §3 point 5.
3. **Replace `seed_ordinal`-based row indexing with a direct
   `row % texture_height_in_patches` lookup.**
Every canvas row, seed or
   gap, maps onto a real row of the periodic texture.
This closes the
   alignment bug directly rather than special-casing around it, and removes
   the `seed_ordinal` threading from `encode`/`decode` entirely.
4. **Extend `_candidate_weights`** with a new cost term: squared pixel
   difference against the *true* patch that exists at this exact
   `(row, col)` in the guide texture, summed with the existing left-neighbor
   edge-continuity term.
The current above/below-seed-row comparison is
   subsumed by this (comparing directly to the true patch at this position
   is a strictly more direct signal than comparing only to its neighbors'
   edges).
Still pure integer arithmetic, still a pure function of position
   and the shared seed — decode recomputes it identically.
5. **Fallback for `attractor`.**
Keeps today's local-edge-only cost function
   unchanged (no guide-texture term), since it has no exploitable positional
   structure and was not one of the two flavors known to fragment.
This is
   the explicit fallback path if a universal mechanism doesn't extend to a
   given flavor, applied here to exactly the one flavor the investigation
   found it doesn't fit.

## 4. What does not change

- The arithmetic coder, the wire format, the `ChunkEncoding` interface, and
  the four texture flavor identifiers.
- `value_noise` and `attractor`'s *appearance* is not expected to change
  much — both were already adequate under the local-only cost function; the
  goal is fixing `voronoi` and `reaction_diffusion` (plus the seed-row seam,
  which affects all four equally) without regressing the two that were
  already fine.

## 5. Measurement and rollback plan

Same independent metric the `OVERLAP` experiment used: actual seam MSE at
patch boundaries in the rendered canvas, fixed non-random input, measured
before and after, per flavor.
Additionally:

- Full round-trip correctness (`encode` then `decode` recovers the exact
  original bytes) for all four flavors, at several payload sizes, including
  ones that span multiple tiled periods of the texture.
- Direct visual comparison (upscaled PNG, nearest-neighbor, same method used
  earlier this session) of before/after canvases per flavor.
- If a flavor's seam MSE gets worse, or round-trip correctness breaks and
  can't be fixed quickly, that flavor reverts to its current behavior
  (mirroring the `attractor` fallback already planned) and the outcome gets
  recorded in `memory/rejected-ideas.md`, the same way `OVERLAP` was.
