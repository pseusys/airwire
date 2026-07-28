# Research Proposal - *airwave*

### A channel-agnostic adaptive transport for encrypted data over unknown lossy channels - physical *or* semantic

> **Status:** research framing / proposal (v0). No implementation intended yet.
> **Working codename:** *airwave* - the exploratory sibling of the [airwire](../README.md) messaging product.
> **Core thesis:** *one core, many heads.* A single adaptive transport engine, swappable renderers.
> **Bibliography:** [`references.bib`](./references.bib)

---

## 1. Abstract

Imagine there's a channel we neither understand in advance nor get to choose and we have to exchange data over it.
In this research we attempt to create a transport engine that assumes nothing about the medium.
It probes whatever degrees of freedom the channel offers, measures how much capacity and reliability each one actually has, settles on an encoding both endpoints can sustain, and then streams encrypted, error-corrected data, re-adapting when conditions drift.

The engine consists of two parts: the *core* is responsible for encoding management, while a swappable *head* really communicates with the channel.
The core emits an abstract vector of features; the head turns that vector into a signal in some medium and reads it back again.
Bytes stay on the core's side of the boundary and the medium stays on the head's, so neither has to know anything about the other.
That separation is what the rest of the proposal builds on: one core, many heads.

The first concrete target, and the hardest, is audio over an unknown channel.
In practice the medium could be a clean VoIP path, a narrowband and lossy cellular or PSTN voice codec, or an open-air loudspeaker-room-microphone link.
These vary by orders of magnitude in fidelity and in the kind of distortion they impose.
A classic modem would be told up front which one it faces; ours is not.
Audio is where we build and validate the core ([system architecture](#5-system-architecture), [transmission protocol](#6-protocol-phases--mechanisms) and [evaluation methodology](#7-evaluation-methodology)).

Since the feature/head boundary says nothing about physics, the same engine also drives heads whose "channel" is not a medium at all but a lossy transform of meaning: a [platform that recompresses an image, say, or a language model that paraphrases text](#55-head-taxonomy--roadmap).
These semantic channels are the least explored part of the space, and we think the most novel.
They also close the loop with the near-term [airwire](../README.md) product, whose text- and image-steganography encoders turn out to be nothing more than the first heads on this same core.

## 2. Motivation & problem statement

Existing "data over audio" systems each hard-code an assumption about their channel:

- **Voiceband modems** (V.21 → V.34) assume a roughly linear ~300-3400 Hz telephone channel and probe *only* its frequency response and SNR to pick a rate `[ituv34]`.
- **Speech-codec modems** (GSM/AMR, eCall) assume a specific *vocoder* and reverse-engineer symbol codebooks that survive it `[amrdatamodem, ecallamr]`.
  There is no closed-form model of a vocoder as a data channel, so these are laboriously tuned per codec.
- **Data-over-sound** libraries (ggwave, chirp) assume an open-air acoustic path and fix a modulation profile (Normal/Fast/Robust/Ultrasonic) chosen *manually* by the operator `[ggwave, ubicomp2019dataoversound]`.

None of them starts from the complete ignorance of the underlying channel.
At the same time, the three audio targets are completely incompatible with each other and require correct choice made by the operator in advance.
A modulation that runs well over VoIP is mangled by an AMR vocoder, which was built to preserve speech and treats an arbitrary waveform as noise to throw away.
A tone scheme tuned for a quiet room falls apart the moment there is reverberation.

**The research question is therefore:** *can a single engine treat "the set of transmittable features, their capacities, and their reliabilities" as an unknown to be measured, and build an efficient, adaptive, encrypted link on top of whatever it finds - for the audio channel first, and then for channels that are not acoustic at all?*

**Starting from audio channels**
When it comes to audio channels specifically, there's one thing to keep in mind.
Telephone systems are deliberately built to preserve the things that carry meaning in human speech: pitch, loudness, formant structure, rhythm.
So as a first attempt, a set of features that survive telephone systems well can be chosen for the feature vector; moreover, it happens to line up with the eventual ML head, which renders those same features back into voice `[codec2, wavenet2016]`.
Later, a more abstract set of (potentially more orthogonal) features can be chosen, that in turn will be consumed by other ML or non-ML audio generation models, not only in telephone line conditions, but also in more reliable (VoIP channels) or less reliable (real, non-digital sounds) scenarios.

**Widening the scope**
Finally, nothing about the feature/head split is specific to audio.
A head only has to encode a feature vector into some carrier and decode it back, and the carrier can be any medium with degrees of freedom you can control and observe.
That includes semantic carriers, where the "channel" is a lossy transform applied to content rather than to a waveform.
An image posted to a social platform comes back recompressed; text handed to a language model comes back paraphrased, translated, or summarised.
If the engine can probe how badly a given transform mangles its carrier, and which features come through intact, then the same probing, negotiation, adaptation, and coding it uses on a bad phone line should carry data through a bad interpreter just as well.
This is the [least charted corner of the design](#55-head-taxonomy--roadmap), specifically because LLM research is out of both my expertise and resources right now.

## 3. Background & related work

| Theme | What we borrow | Key refs |
| --- | --- | --- |
| **Channel capacity** | Features are parallel sub-channels; allocate bits by water-filling over measured per-feature capacity | `shannon1948`, `coverthomas2006` |
| **Voiceband data** | In-band signalling with discrete robust symbols; AC-coupled tones survive speech equipment | `ituv21`, `dtmf_wikipedia`, `fsk_wikipedia` |
| **Startup negotiation** | V.8 CM/JM capability exchange; V.34 line probing → rate selection | `ituv8`, `ituv34` |
| **Data through speech codecs** | Speech-*like* symbols survive vocoders; motivates a prosodic feature set | `amrdatamodem`, `ecallamr`, `qamamrwb` |
| **Acoustic PHY** | Preamble chirp for sync; reference tones to learn room distortion; Reed-Solomon FEC | `ggwave`, `tiot2025acoustic`, `dsssofdm_sound` |
| **Runtime adaptation** | AMC/link adaptation; RL for tuning-free switch policies; congestion-control-style feedback | `amcreview`, `rl_linkadaptation`, `jacobson1988` |
| **Probing cost** | Pilot density vs. channel selectivity - the overhead-vs-accuracy trade | `pilotace_ofdm` |
| **Turn-taking** | RTS/CTS handshake for half-duplex reservation | `karn1990maca` |
| **Error correction** | Block FEC (Reed-Solomon) and rateless codes when reliability is unknown | `reedsolomon1960`, `luby2002lt` |
| **Neural (audio) head** | Vocoders / TTS with a mel-spectrogram "feature" bottleneck as the head boundary | `wavenet2016`, `tacotron2`, `codec2` |
| **Semantic channels** | Linguistic steganography; LLM watermarking and its (non-)robustness to paraphrase | `ziegler2019neurallingstego`, `kirchenbauer2023watermark`, `krishna2023paraphrase`, `kuditipudi2023robust` |
| **Covert framing** | VoIP steganography; unintended-channel exfiltration | `voipstego_survey`, `airhopper2014`, `sonic2024` |

**Where this sits.** Taken one at a time, most of these mechanisms are mature.
Probe-then-choose is the essence of cognitive radio and of V.34.
Runtime switching is ordinary AMC.
The idea that speech-like symbols can survive a vocoder is already deployed in the eCall in-band modem, and adaptive per-lane acoustic estimation already ships inside ggwave.
On the audio side, then, airwave is more a synthesis of known parts than a new mechanism, and it is worth being upfront about that.

**The gap.** What the literature does not offer is a protocol whose feature basis is itself discovered and renegotiated, kept separate from an interchangeable rendering head, and then reused across media that have little in common.
The novelty comes from two places.
The first is treating each feature's capacity and its resolve-cost as measured quantities the engine allocates over, rather than as fixed design constants.
The second is running that same engine over semantic channels such as image recompression or LLM paraphrase, where very little exists.
LLM watermarking already embeds a signal into generated text `[kirchenbauer2023watermark]` and paraphrase attacks already strip it back out `[krishna2023paraphrase]`, but no one has framed surviving a paraphrase as running an adaptive modem over a semantic channel.
Two caveats keep the claim honest.
The feature abstraction is shaped by its signal-processing origins (see §5.1 on resolve-cost), and in language the features are heavily coupled, which puts real strain on the parallel-sub-channel picture that keeps bit allocation clean.

## 4. Research questions & hypotheses

- **RQ1 - Feature discovery.**
  Can two endpoints reliably enumerate which features an unknown channel preserves, and estimate each feature's *capacity* (distinguishable states) and *resolve-cost* (minimum stable-transmission budget), within a bounded probing budget?
- **RQ2 - Efficient allocation.**
  Given per-feature `(capacity, resolve-cost, reliability)`, what scheduling of feature events maximises goodput?
  *Hypothesis:* a [water-filling allocation](https://en.wikipedia.org/wiki/Water-filling_algorithm) over the "bits-per-unit-carrier-per-feature" vector, with reliability-weighted redundancy, beats any single fixed encoding across the VoIP / codec / open-air spread.
- **RQ3 - Prosodic bias.**
  *Hypothesis:* a feature set drawn from speech prosody survives audio channels substantially better than arbitrary-waveform modulation at equal bitrate, because such channels are engineered to preserve exactly those features.
- **RQ4 - Head independence.**
  Can the same scheduler/feature stream drive an algorithmic head and an ML speech-imitating head with no protocol changes - i.e. is the feature array a genuinely meaning- and medium-agnostic waist?
- **RQ5 - Runtime adaptation.**
  How cheaply can the link detect degradation/improvement and switch encodings mid-stream without losing framing or requiring a full re-handshake?
- **RQ6 - Cross-medium reach (semantic channels).**
  Does the core survive the jump from a continuous physical medium to a discrete *semantic* transform?
  Specifically: can data be embedded so it survives an LLM paraphrasing/translating the carrier text (or a platform recompressing the carrier image), driven by the *same* probe -> negotiate -> adapt -> FEC engine?
  This is the highest-novelty and highest-risk thread.

## 5. System architecture

```
   bytes            feature events                 signal
 ┌────────┐   ┌────────────────────────┐   ┌───────────────────────┐
 │ crypto │──▶│   SCHEDULER (the core) │──▶│  HEAD (pluggable)     │──▶ ((( channel )))
 │ + FEC  │◀──│   bytes <-> events     │◀──│  features <-> carrier │◀── ((( channel )))
 └────────┘   └───────────┬────────────┘   └───────────────────────┘
                          │                  audio | image | text | ...
                 ┌────────▼─────────┐
                 │  channel model   │  per-feature (capacity,
                 │  (probe + track) │  resolve-cost, reliability)
                 └──────────────────┘
```

### 5.1 The feature abstraction

A **feature** is a controllable, channel-observable dimension of the carrier - for the audio head, of the audio signal (loudness, fundamental pitch, spectral centroid/tilt, tempo/segment duration, a formant ratio, an ultrasonic sub-band); for a semantic head, of the content (a synonym choice, a syntactic variant, a colour/DCT coefficient of a generated image).
Each feature is characterised by a measured triple:

- **capacity** - number of reliably distinguishable states (∝ its usable range / step size);
- **resolve-cost** - the carrier budget a state change consumes before the receiver can resolve it.
  For a streaming/physical head this is a *duration* (the original **estimation time**: pitch needs several cycles; loudness resolves fast; a codec's smoothing sets a floor).
  For a non-streaming *semantic* head (§5.5) it generalises to a *quantity of carrier* - e.g. tokens of text, or image area - rather than time.
- **reliability** - measured error/confusion rate for that feature on *this* channel, per side.

Features may be **orthogonal** (independently settable/observable) or **coupled** (changing one perturbs another - loudness affecting perceived pitch in audio; a word choice shifting every later word's context in language).
The channel model must estimate the coupling so the scheduler can avoid or exploit it.
Coupling is mild for physical audio features and *severe* for language, which is the main reason the semantic heads are hard (see §5.5, §9).
Features cross the scheduler↔head boundary as a **floating-point array**; the head owns their realisation, the scheduler owns only their symbolic use.

### 5.2 Scheduler (the core)

A meaning- and medium-agnostic engine that:

1. maps outgoing bytes → a timed stream of **events**, each event = a change to one or more feature values, sequenced to respect each feature's `resolve-cost`;
2. maps the incoming feature-value stream back → bytes;
3. holds the framing, the current **encoding agreement**, FEC, and the adaptation state machine.

The scheduler never produces or consumes a carrier.
This is the layer where capacity allocation (RQ2), error correction, and encoding switches live - identically for every head.

### 5.3 Head (pluggable)

Renders a feature array to a carrier and analyses an incoming carrier back to a feature array.
The head is the *only* medium-specific component; §5.5 enumerates the planned family.

### 5.4 Channel model (probe + track)

Owns the `(capacity, resolve-cost, reliability, coupling)` estimates per feature, produced by the probing subsystem (§6.1) and continuously refreshed by in-band pilots during transfer (`pilotace_ofdm`).
Its outputs are what the scheduler allocates over; nothing else in the core knows what medium is underneath.

### 5.5 Head taxonomy & roadmap

The core's value is that all of the following share one scheduler, one probing/negotiation flow, one FEC/crypto stack - differing *only* in the head.
They fall into two families.

| Family | Head | Features | "Channel" (what mangles them) | Status / novelty |
|---|---|---|---|---|
| **Physical (streaming)** | Algorithmic audio | pitch, loudness, spectral tilt, duration | VoIP / vocoder / room acoustics | Prototype; core validated here |
| | Neural-speech audio | same array → realistic voice `[wavenet2016, tacotron2]` | vocoder + covertness | Research; medium novelty |
| **Semantic (non-streaming)** | Image (airwire's head) | generated-image params / DCT coeffs | **platform recompression** (JPEG, resize) | Near-term product head; robust-stego is hard |
| | Text (airwire's Markov head) `[ziegler2019neurallingstego]` | synonym / syntactic choices | a messaging platform | Near-term product head |
| | **LLM-transform** | token / phrasing choices | **an LLM paraphrasing / translating / summarising the carrier** `[krishna2023paraphrase]` | **Research frontier; highest novelty** |

Physical heads keep `resolve-cost` as a hold-duration and enjoy weak coupling, so the parallel-feature model and water-filling apply cleanly.
Semantic heads redefine `resolve-cost` as consumed carrier (tokens, pixels), face strong coupling, and turn a one-shot transform (not a stream) into the "channel" - so the *engine* is reused but its assumptions are stressed.
The LLM-transform head is the sharp research target: LLM watermarking shows a signal *can* be embedded in generated text `[kirchenbauer2023watermark]` and paraphrase attacks show it is easily stripped `[krishna2023paraphrase]` - reframing "survive paraphrase" as *FEC + adaptation over a semantic channel* is the novel move.

> **A note on scope (see §9).** Supporting many heads reads well on paper and is a trap in practice.
> A proposal that touches five heads shallowly is weaker than one that takes a single hard head all the way.
> So the plan is deliberately narrow: build and prove the core against the audio head, ship the image and text heads as the near-term airwire product, and take exactly one semantic research head, the LLM-transform, as far as it will go.

## 6. Protocol phases & mechanisms

The engine must handle, for every head: **probing, capability agreement, transmission, error correction, encoding switching, and encryption/verification.**

1. **Probing (§6.1)** - heavy at startup, light and continuous at runtime.
2. **Capability agreement (§6.2)** - both sides converge on a shared, sustainable encoding.
3. **Transmission (§6.3)** - full- or half-duplex feature-event streaming with FEC.
4. **Adaptation (§6.4)** - detect degradation/improvement, renegotiate without a full restart.
5. **Security (§6.5)** - encryption, integrity, and authenticity over an unreliable link.

### 6.1 Channel probing

- **Startup probe** (may be expensive): sweep each candidate feature across its range and hold each state for varying budgets, so *both* sides estimate that feature's capacity, resolve-cost, and reliability - the acoustic analogue of V.34 line probing `[ituv34]` generalised from "frequency response" to "an arbitrary feature basis."
  Results are exchanged so both ends share one channel model.
  For a semantic head, the "probe" is instead sending known carriers through the transform and measuring which features survive (how many watermark bits survive a paraphrase, etc.).
- **Runtime probe** (cheap, continuous): interleave known pilot values into the stream to track drift; pilot density trades overhead against tracking accuracy `[pilotace_ofdm]`.

### 6.2 Encoding agreement & switching

A capability-negotiation handshake in the spirit of V.8 CM/JM `[ituv8]`: each side advertises the features it can render/observe and their measured triples; they intersect to a shared feature set and agree an allocation (which features carry data, how many states each, symbol budget, FEC rate).
**Switching** re-runs a lightweight version of this over the live link when the channel model crosses a threshold - a candidate for a learned policy to avoid hand-tuned thresholds `[rl_linkadaptation]`, framed like congestion control's feedback loop `[jacobson1988]`.

### 6.3 Transmission & duplexing

- **Full-duplex** where the channel allows simultaneous both-way carriers (VoIP): features may be feature-multiplexed per direction.
- **Half-duplex** otherwise (open-air, echo-prone; and inherently for one-shot semantic carriers): an RTS/CTS-style turn-taking handshake reserves the medium `[karn1990maca]`.

### 6.4 Error correction

Per-feature reliability is *unknown a priori and drifting*, which favours:

- reliability-weighted redundancy (spend more coding on low-reliability features);
- block FEC (Reed-Solomon, as in ggwave/chirp) `[reedsolomon1960, ggwave]` as a baseline;
- **rateless/fountain codes** `[luby2002lt]` when the achievable rate is uncertain, letting the receiver accumulate enough symbols rather than committing to a fixed code rate up front - especially apt for semantic heads, where "how many bits survive the transform" is only known empirically.

### 6.5 Encryption & verification

The link is assumed hostile and lossy.
We reuse airwire's asynchronous crypto stance - X25519 + XChaCha20-Poly1305 (see [README](../README.md#encryption)) - with framing chosen so authentication tags and key material survive FEC and re-sync after loss.
Integrity/authenticity must hold even when the feature stream is noisy, and (with the neural or LLM head) the ciphertext-bearing carrier should be plausibly benign `[voipstego_survey]`.

## 7. Evaluation methodology

- **Channel testbed (audio):** three reference channels - (a) a clean VoIP path, (b) a genuine narrowband speech codec (e.g. AMR/G.729) in the loop, (c) open-air loudspeaker→mic across varying rooms/distances/noise.
  Codec and acoustic impulse responses can be applied offline for reproducibility before hardware-in-the-loop tests.
- **Channel testbed (semantic):** carriers passed through real transforms - a set of image recompressors/resizers, and a panel of LLMs performing paraphrase/translation/summarisation `[krishna2023paraphrase]` - measuring surviving-feature capacity per transform.
- **Metrics:** goodput, bit/frame error rate post-FEC, startup probing latency, adaptation reaction time to injected degradation, overhead (probe/pilot/FEC fraction), and - for semantic heads - covertness (detector AUC) alongside recovery rate.
- **Baselines:** fixed ggwave profiles `[ggwave]`, a V.21-style FSK link `[ituv21]`, and an AMR-codebook modem `[amrdatamodem]` for audio; LLM watermarking `[kirchenbauer2023watermark]` for the semantic head.
  airwave's claim is being competitive *across* channels without manual reconfiguration, on one shared engine.
- **Ablations:** prosodic vs. arbitrary feature basis (RQ3); algorithmic vs. neural head (RQ4); static vs. adaptive encoding under a moving channel (RQ5); physical vs. semantic head on the same core (RQ6).

## 8. Phased plan

| Phase | Goal | Deliverable |
|---|---|---|
| **P0** | Formalise the feature & channel model; simulate capacity/resolve-cost trade-offs | Model + simulator, validation of RQ2 in sim |
| **P1** | Algorithmic audio head + scheduler over the clean VoIP channel | End-to-end link, no adaptation |
| **P2** | Probing + capability agreement; add the codec and open-air channels | Adaptive link across all three audio channels (RQ1, RQ3) |
| **P3** | Runtime adaptation & encoding switching under moving channels | Degradation/recovery evaluation (RQ5) |
| **P4** | Neural speech-imitating audio head against the same scheduler | Head-independence result + steganographic evaluation (RQ4) |
| **P5** | **Semantic head:** data that survives LLM paraphrase/translation on the same core | Cross-medium result, physical→semantic (RQ6); the novel thread |

## 9. Risks & open questions

- **Vocoder non-linearity:** speech codecs have no clean channel model `[amrdatamodem]`; feature reliability may only be knowable empirically, making probing essential rather than optional.
  The same is true, more sharply, of an LLM transform - so RQ2's water-filling is a *heuristic* on nonlinear/semantic channels.
- **Abstraction leakage & framework breadth:** the feature triple (esp. `resolve-cost`) is signal-shaped, carrying the core to discrete semantic channels needs it redefined as consumed carrier (e.g. as one feature change per unit of generation).
  Moreover, language's strong feature *coupling* may collapse the "many parallel features" model to effectively one or two usable dimensions - in which case the elegant abstraction buys nothing over a single robust encoding.
  Breadth is itself a trap: the algorithm should be better than competitors on one head, not worse on all of them.
- **Feature coupling & resolve-cost floors** may leave far less usable capacity than a naive per-feature sum suggests, on *any* head.
- **Probing cost vs. link lifetime:** an expensive startup probe is wasted on short messages - when is a cheaper, optimistic start with fast fallback better?
- **Neural-head latency/determinism** and whether analysis truly inverts synthesis to recover the feature array faithfully; likewise whether an LLM head can decode reliably without the exact model and under non-exactly-matching conditions.
- **Synchronisation** (framing, symbol timing) under reverberation and codec time-warping.

## 10. Relationship to airwire - one core, many heads

The original two-track split (product vs. research) is better understood as **one core with heads of different maturity**:

- **The core** - the probe / negotiate / adapt / FEC / crypto engine - is medium-agnostic and shared by everything below.
- **Near-term heads (airwire, buildable now):** the SMS **text** head (Markov / linguistic steganography `[ziegler2019neurallingstego]`) and the MMS **image** head.
  These are the [airwire](../README.md) product: encrypt/decrypt text and images under a pre-shared key, sent raw or disguised as benign content.
- **Research heads (airwave):** the **algorithmic audio** head (where the core is built and validated), then the **neural-speech** head, then the **LLM-transform** head - the novel frontier, where "survive an AI paraphrasing your text" becomes *FEC + adaptation over a semantic channel*.

Seen this way, airwire and airwave are not two projects.
They are two ends of one axis: the same engine, rendered by progressively stranger heads.
The neural and LLM heads are the point where the product's need for benign-looking cover and the research's ambition to work over any channel stop being separate goals and become a single problem.

## 11. References

See [`references.bib`](./references.bib).
Entries are grouped by theme and annotated with source links; foundational works are cited from standard publication data, web-sourced entries carry URLs.
