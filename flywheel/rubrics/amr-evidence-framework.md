---
title: "Position: Anthropomorphic Misalignment Research Needs Stronger Evidence"
source: arXiv 2606.07612v1 (Gupta, Nutter, Stante, Krause, Tramèr, Fluri, Chen, Hedström)
purpose: reusable rubric for grading the evidential strength of a misalignment claim
vendored_from: lab-notes-jarvis / notes/literature/amr-stronger-evidence-framework.md
note: flywheel's built-in critique rubric; override via [critique] rubric_file
---

# AMR Evidence Framework — a rubric for critiquing misalignment research

A position paper that does two jobs: (1) argues a large slice of alignment work
over-claims relative to its evidence, and (2) hands you a **diagnostic apparatus**
to grade any such paper. This note extracts (2) as a clean, reusable rubric —
the spine of a "read papers at scale and report what evidence they actually
yield" pipeline. The companion worked example is
the AMR deception-probes critique.

**AMR (Anthropomorphic Misalignment Research)** = "a family of alignment-oriented
studies that investigate safety-relevant failure modes in AI described through
human-like characteristics, motivations, intentions, or emotions" — deception,
scheming, self-preservation, sycophancy, situational awareness, emergent
misalignment. The anthropomorphic label (a model "wants", "schemes", "lies") is
a *claim about an internal state*, and the central thesis is that the evidence
usually offered (behavioral outputs) cannot license that claim.

**Central position:** *the evidence required scales with the kind of claim you
make.* Most papers make L3-flavored claims (intent, mechanism) on L1 evidence
(behavior under one setting). The fix is not "do more" but "claim less, or
measure more" — match the rung to the ladder.

---

## The evidence ladder (L1 → L3)

The load-bearing idea. Each rung is a *claim type* with a canonical schema; you
grade a paper by the highest rung its methods actually support, then check
whether its prose claims a higher rung.

| Rung | Name | Canonical claim | What it takes to earn it |
|------|------|-----------------|--------------------------|
| **L1** | **Behavioral** | "under setting `S` and evaluator `E`, behavior `B` occurs at rate `p`." | A dataset, an operational definition, a scorer. Documents an output pattern. **Says nothing about why.** |
| **L2** | **Functional** | "in deployment-plausible context `C`, behavior `B` reliably induces downstream effect `E`." | Show the behavior *does something* safety-relevant downstream, across contexts — without attributing intent. |
| **L3** | **Causal-mechanistic** | "internal structure `M` causes `B`" (intent, a represented goal, a mechanism). | Interventions (ablation / steering / fine-tuning), alternative-explanation testing. Correlation is not enough. |

Rule of thumb (their **R12**): *match claims to evidence levels; downgrade any
claim the evidence doesn't reach.* "The model is deceptive" is L3 language; a
probe AUROC is L1 evidence.

---

## The 4-stage pipeline + 12 recommendations (R1–R12)

Every AMR paper moves through four stages. Failures compound downstream, so the
rubric is staged. Each recommendation is a checklist item; a paper "passes" a
stage only if it satisfies the stage's R's *at the evidence level it claims*.

**S1 — Target Behavior Framing**
- **R1** Scope the technical definition with clear measurement criteria *and explicit exclusions* (what does NOT count as the behavior).
- **R2** Declare the intended evidence level (L1/L2/L3) upfront.
- **R3** Ground anthropomorphic terms ("deception", "wants") in observable criteria — not vibes.

**S2 — Data Construction & Operationalization**
- **R4** Support generalization with sufficient scale; justify dataset size against the effect magnitude claimed.
- **R5** Ensure distributional diversity and add surface-feature controls (wordings, domains, formats) so the construct isn't a surface artifact.

**S3 — Experimental Design**
- **R6** Measure scorer reliability; prefer human scoring with inter-rater reliability over LLM-only grading (and audit the LLM judge).
- **R7** Measure general capability (MMLU, MT-Bench, …) to isolate the intervention from capability shifts / forgetting.
- **R8** Ablate sufficiently — prompt paraphrases, model scales, temperatures, aggregation choices — and report uncertainty.
- **R9** Test plausible alternative explanations with negative controls and discriminant-validity checks.

**S4 — Causal & Mechanistic Attribution**
- **R10** Generate interventionist evidence (ablation / steering / fine-tuning) with transparent failure reporting.
- **R11** State mechanistic hypotheses as testable claims with explicit falsification conditions.
- **R12** Match conclusions to evidence levels; downgrade unsupported claims.

---

## The nine recurring failure modes (C1–C9)

These are the *symptoms* you scan for — the things that, when present, knock a
paper's earned rung below its claimed rung. Mapped to the stage they bite.

| # | Failure mode | Stage | Tell |
|---|--------------|-------|------|
| **C1** | Anthropomorphic concepts **underspecified** | S1 | No formal grounding → metric is undefined. |
| **C2** | Concepts **hard to measure** | S1/S2 | Proxies track prompt cues / training incentives, not "stable convictions". |
| **C3** | Datasets **small & low-diversity** | S2 | ~50 queries, sometimes <10; repetitive building blocks. |
| **C4** | Definition issues **carry into dataset design** | S2 | Different definitions → incompatible datasets for the "same" phenomenon. |
| **C5** | Design choices **insufficiently ablated** | S3 | Token selection / aggregation / scoring fixed at one config, no sensitivity test. |
| **C6** | **Unreliable LLM judges** are standard | S3 | Stochastic, temperature/phrasing-sensitive, systematic framing bias. |
| **C7** | **Non-target mechanisms unmeasured** | S3 | No control separating the phenomenon from instruction ambiguity / task-completion drive / forgetting. |
| **C8** | **Spurious correlations** limit causal attribution | S3/S4 | Probe/metric fires on vocabulary, personas, framing — not the construct. |
| **C9** | Mechanistic methods **overstate functional relevance** | S4 | Predict-control gap: a feature predicts without causing; recovers a statistical regularity, not a causal lever. |

---

## The diagnostic checklist (Appendix B), as a scan

Operational form — one line per stage, answerable yes/no/partial against a paper:

- **S1** — Is the target behavior defined with measurement criteria *and exclusions*? Is the evidence level declared? Are anthropomorphic terms grounded in observables? *(R1–R3; guards C1–C2)*
- **S2** — Is dataset size justified against the claimed effect? Is there distributional diversity + surface-feature controls? Is construct validity audited? *(R4–R5; guards C3–C4)*
- **S3** — Is scorer reliability measured (human + LLM audit)? Are capability benchmarks reported? Are ablations run across paraphrase/scale/temperature? Are alternative explanations tested with negative controls? *(R6–R9; guards C5–C8)*
- **S4** — Is there interventionist evidence (ablation/steering/fine-tuning)? Are mechanistic hypotheses falsifiable? Do conclusions match the evidence level? *(R10–R12; guards C9)*

**Verdict shape** (what the rubric outputs): *the paper claims rung Lx; its
methods earn rung Ly (≤ x); the gap is driven by failure modes {Ci…}; to close
it, satisfy {Rj…}.* That tuple — **claimed rung, earned rung, the C-gap, the
R-fix** — is the unit of "what evidence does this paper actually yield."

---

## Papers the authors themselves run through it (for calibration)

- **Deception — Goldowsky-Dill et al. 2025** (linear deception probes): probes
  fire on sarcasm / role-play / recitation → C8; earns **L1**, not the L3 the
  "detects deception" framing implies. *(worked in full in the AMR deception-probes critique.)*
- **Deception — Huang et al. 2025 (DeceptionBench):** 97.1% claimed human
  agreement, but audit found 18% of scenarios lacked ground truth → C4/C6.
- **Emergent misalignment — Betley / Turner / Soligo / Zhang / Afonin et al.:**
  ~tens of queries, AI-generated low-diversity data → C3; and a benign OOD
  fine-tune (innocuous aesthetics / scatology) reproduces ~5% "EM" → C7
  (capability shift confound, not a mechanism).
- **Shutdown resistance — Schlatter et al. 2026:** "self-preservation"
  re-explained by Rajamanoharan & Nanda as instruction ambiguity + task-completion
  incentive → C7.
- **Situational awareness — Phuong 2025 vs Laine 2024:** incompatible
  operationalizations (agentic Linux tasks vs QA) for the "same" construct → C4.

## Why it matters here

- This is a **graders' rubric**, not just a polemic — the (claimed rung, earned
  rung, C-gap, R-fix) tuple is directly automatable as a per-paper structured
  output, which is the at-scale-triage use case.
- The ladder cleanly separates **"a behavior was observed" (cheap, L1)** from
  **"a disposition/mechanism exists" (expensive, L3)** — the exact line our own
  organism work polices (the want-generalization NULL was an L3 claim failing on
  L1/L2 evidence; cf. goal-directed model organisms), so the framework doubles as
  a self-audit checklist for our experiments.
- C7 (benign capability-shift confound) and C9 (predict ≠ control) are recurring
  hazards in our EM-distillation and eNTK/subliminal work — worth pre-registering
  the relevant negative controls before, not after.
