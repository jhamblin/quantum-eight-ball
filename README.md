# Quantum Magic 8-Ball

A Magic 8-Ball, but the "magic" is Grover's search algorithm running on
AWS Braket. Ask a question, shake the ball, and a genuinely quantum
process picks and then reveals your answer. Runs identically against
Braket's free local simulator or a managed AWS simulator/QPU — same
circuits, same code, just a different `--device` flag.

This is a companion project to a [Bell-state "hello world"](../bell)
for Braket; that one introduces qubits, kets, and gates from scratch.
This README is self-contained, but moves faster through those basics
to spend most of its length on Grover's algorithm itself.

## 1. The concept

A real Magic 8-Ball contains a 20-sided die floating in dark fluid. You
ask a question, shake it, and the die tumbles to a random face that's
already hidden inside the ball before you look — you're not causing
the answer to exist, you're revealing one that was already fixed the
moment the die settled.

This program mirrors that two-step structure exactly, using 8 possible
answers instead of 20 (so the state fits in `2³ = 8` basis states —
one satisfying reason "eight ball" and "3 qubits" go well together):

1. **Shake.** A quantum coin-flip circuit (`H` on each of 3 qubits,
   then measure) picks one of the 8 answers uniformly at random. This
   is the die settling — a real physical random process, not a
   pseudorandom number generator.
2. **Reveal.** **Grover's algorithm** is used to search the 8
   possibilities for that specific hidden answer, amplifying its
   measurement probability from an unhelpful `1/8 = 12.5%` up to
   roughly `94%`, so that measuring the circuit reveals it.

Step 2 is the actual point of this project: it's a small, concrete,
verifiable demonstration of Grover's algorithm, using the hidden
answer from step 1 as the "needle" Grover has to find in the
"haystack" of 8 possibilities.

## 2. Quantum basics, quickly

*(Full derivations of this section are in the [Bell-state
README](../bell/README.md#1-the-quantum-mechanics-from-scratch); this
is the condensed version needed for what follows.)*

A qubit's state is a unit vector in ℂ², written `|ψ⟩ = α|0⟩ + β|1⟩`,
where `|α|²` and `|β|²` are the probabilities of measuring `0` and
`1`. `n` qubits together live in a `2ⁿ`-dimensional space built from
the **tensor product** `⊗` of the individual qubit spaces; the basis
states are all `n`-bit strings, e.g. for `n=3`: `|000⟩, |001⟩, ...,
|111⟩`. A **gate** is a unitary matrix acting on this vector by matrix
multiplication.

The **Hadamard gate** `H = 1/√2 [[1,1],[1,-1]]` maps `|0⟩ ↦
1/√2(|0⟩+|1⟩)`. Applying `H` to all 3 qubits starting from `|000⟩`
gives the **uniform superposition** over all 8 basis states:

```
H⊗H⊗H |000⟩ = 1/√8 (|000⟩ + |001⟩ + |010⟩ + ... + |111⟩)
```

every one of the 8 states with equal amplitude `1/√8` — measuring
this gives each of the 8 outcomes with equal probability `1/8`. This
is exactly the "shake" step: run this circuit with 1 shot and read off
whichever 3-bit string you measure as the hidden answer's index.

## 3. Grover's algorithm

### 3.1 The problem it solves

You have `N` items (here `N=8`, indexed by 3-bit strings) and a
**black-box oracle** that can tell you whether a given item is "the
marked one" `w` — but you can't just peek at `w` directly, only query
the oracle. Classically, finding `w` by querying one item at a time
takes `N/2` queries on average, `N` in the worst case. **Grover's
algorithm finds it in about `√N` oracle queries** — a quadratic
speedup that's also *provably optimal* (no quantum algorithm can do
better than `Θ(√N)` for this problem).

In this program, "the marked item" is the hidden answer chosen by the
shake step, and the oracle is built from that specific 3-bit string —
see §3.3. This is a slightly artificial setup (the code technically
"knows" `w` in order to build the oracle), but it's the standard way
to demonstrate and test a Grover implementation: build an oracle for a
*known* target, then verify Grover actually finds it.

### 3.2 The algorithm, at a glance

```
1. |s⟩ = H⊗ⁿ|0...0⟩                      (uniform superposition)
2. Repeat r times:
     a. Apply the oracle Uf                (flip the sign of |w⟩)
     b. Apply the diffuser D                (invert amplitudes about their mean)
3. Measure. With high probability, the result is w.
```

Each `(oracle, diffuser)` pair is called a **Grover iteration**. `r`
is chosen based on `N` (see §3.4) — too few iterations undershoots,
too many overshoots, because the amplitude on `|w⟩` doesn't increase
monotonically forever; it oscillates.

### 3.3 The oracle: a sign flip, made concrete

The oracle is the unitary:

```
Uf = I - 2|w⟩⟨w|
```

which does `Uf|w⟩ = -|w⟩` and `Uf|x⟩ = |x⟩` for every `x ≠ w`. Note
what this *doesn't* do: it doesn't change any measurement probability
by itself (`|-1|² = |1|² = 1`) — a flipped sign is invisible if you
measured right away. It only matters once the diffuser (§3.4) uses
that sign difference to move amplitude around.

**Building it from gates**, for a concrete example target `w = 101`:

1. Apply `X` to every qubit where `w`'s bit is `0` (here, just qubit
   1): this maps `|101⟩ ↦ |111⟩`, and — because applying a fixed set
   of `X` gates is a bijection — maps every *other* 3-bit string to
   something other than `|111⟩`.
2. Apply a **controlled-controlled-Z (CCZ)**, which flips the sign of
   `|111⟩` only: `2|111⟩⟨111| - I`.
3. Undo the same `X` gates from step 1.

The net effect: only the state that got mapped to `|111⟩` in step 1
(i.e. only `|101⟩`) picks up a sign flip; every other state is
`X`'d away from `|111⟩`, passes through the CCZ untouched, then `X`'d
back to itself. That's exactly `Uf` for `w = 101`. [`eight_ball.py`](eight_ball.py)'s
`oracle()` function implements precisely these three steps for
whatever 3-bit target string the shake step produced.

**Building CCZ itself** — Braket's SDK has a built-in Toffoli
(controlled-controlled-**X**, `circuit.ccnot(...)`) but no built-in
controlled-controlled-**Z**. The two are related by the single-qubit
identity `Z = H·X·H`: sandwiching the Toffoli's target qubit with `H`
gates turns its controlled-`X` into a controlled-`Z`:

```
CCZ(q0,q1,q2) = H(q2) · CCNOT(q0,q1,q2) · H(q2)
```

This is the `ccz()` helper function in `eight_ball.py`, and it's the
only 3-qubit gate the whole program needs (both the oracle and the
diffuser below are built from it).

### 3.4 The diffuser: inversion about the mean

The diffuser is:

```
D = H⊗ⁿ (2|0...0⟩⟨0...0| - I) H⊗ⁿ
```

i.e. conjugate a "flip the sign of `|0...0⟩`" operation by `H⊗ⁿ` on
both sides. The inner piece is built exactly like the oracle in §3.3
(with target `000`, which needs no `X` gates at all — CCZ directly),
so as a circuit: `H` on every qubit, `X` on every qubit, `CCZ`, `X` on
every qubit, `H` on every qubit.

**What this operator actually does to the amplitudes**, worked out
algebraically: for any state `|ψ⟩ = Σₓ cₓ|x⟩`, write `⟨s|ψ⟩` where
`|s⟩` is the uniform superposition `1/√N Σₓ|x⟩`:

```
⟨s|ψ⟩ = (1/√N) Σₓ cₓ = √N · mean(c)
```

so applying `D = 2|s⟩⟨s| - I`:

```
D|ψ⟩ = 2⟨s|ψ⟩|s⟩ - |ψ⟩
```

and looking at one component `x` of this (using `|s⟩`'s `x`-th entry,
`1/√N`):

```
cₓ' = 2 · (√N · mean(c)) · (1/√N) - cₓ = 2·mean(c) - cₓ
```

**Every amplitude gets reflected about the average of all the
amplitudes.** That's "inversion about the mean" — not a metaphor, the
literal arithmetic each amplitude undergoes.

**Worked numeric example — one full Grover iteration on `N=8`,
`w=101`.** Start from the uniform state: every `cₓ = 1/√8 ≈ 0.3536`.

*After the oracle* (only `w`'s amplitude flips sign): 7 entries are
still `+0.3536`, and 1 (the target's) is `-0.3536`. Mean:

```
mean(c) = (7 × 0.3536 + 1 × (-0.3536)) / 8 = (6 × 0.3536) / 8 ≈ 0.2652
```

*After the diffuser* (`cₓ' = 2·mean(c) - cₓ`):

- Every non-target entry (`cₓ = 0.3536`):
  `cₓ' = 2(0.2652) - 0.3536 ≈ 0.1768`
- The target entry (`cₓ = -0.3536`):
  `cₓ' = 2(0.2652) - (-0.3536) ≈ 0.8839`

Check normalization: `7×(0.1768)² + (0.8839)² ≈ 0.2188 + 0.7813 ≈
1.000` ✓. The probability of measuring `w` after this single
iteration is `(0.8839)² ≈ 78.1%` — up from the `1/8 = 12.5%` you
started with, after just one oracle+diffuser pair. A second iteration
pushes it higher still (§3.5).

### 3.5 How many iterations, and how likely is success?

**Geometric picture.** Split the state space into `|w⟩` and `|s'⟩`
(the equal superposition of the other `N-1` states). The initial
uniform state sits at angle `θ` from `|s'⟩`, where:

```
sin(θ) = 1/√N        (for one marked item)
```

Each Grover iteration (oracle then diffuser) is a **rotation by `2θ`**
within the 2D plane spanned by `|w⟩` and `|s'⟩`, always rotating
*toward* `|w⟩`. After `k` iterations the state sits at angle
`(2k+1)θ` from `|s'⟩`, so the probability of measuring `w` is:

```
P(k) = sin²((2k+1)θ)
```

This is maximized when `(2k+1)θ ≈ π/2`, giving the standard formula
for the optimal iteration count:

```
r = round(π/(4θ) - 1/2)
```

which is `optimal_iterations()` in `eight_ball.py`.

**Plugging in `N=8`:** `θ = arcsin(1/√8) ≈ 0.3614 rad (20.7°)`, so
`r = round(π/(4×0.3614) - 0.5) = round(1.721) = 2` — matching what the
script computes and uses by default. The probabilities at a few values
of `k` (all `sin²((2k+1)θ)`), compared against what `eight_ball.py`
actually measured over 1000 shots in testing:

| `k` (iterations) | predicted `P(k)` | measured (1000 shots) |
|---|---|---|
| 0 (no amplification) | 12.5% | 13.4% |
| 1 | 78.1% | — |
| **2 (optimal, the default)** | **94.6%** | **93.8%** |
| 3 (overshoot) | 32.9% | 31.3% |
| 4 (further overshoot) | 1.2% | — |

Iteration count is *not* "more is better" — it's a rotation that
overshoots past `|w⟩` if you keep going, exactly like over-rotating
past a target angle. `--iterations 0` and `--iterations 3` in
`eight_ball.py` are there specifically so you can reproduce the
under/over-amplified rows above yourself.

## 4. The code

[`eight_ball.py`](eight_ball.py) implements every piece above:

- `shake(device)` — the `H⊗3` + 1-shot-measurement "coin flip" from
  §2, picking the hidden answer.
- `oracle(target_bits)` — §3.3's `X`-sandwiched `CCZ`, built for
  whichever 3-bit string `shake()` returned.
- `diffuser()` — §3.4's `H`/`X`-sandwiched `CCZ` (target `000`).
- `ccz(circuit, q0, q1, q2)` — the `H·CCNOT·H` identity both of the
  above are built from.
- `optimal_iterations(n_items)` — §3.5's `round(π/(4θ) - 1/2)`.
- `build_grover_circuit(target_bits, iterations)` — `H⊗3` once, then
  `oracle` + `diffuser` repeated `iterations` times.
- `main()` — ties it together: shake, build and run the Grover
  circuit, print the full measurement histogram, and report the
  most-measured answer plus how often it matched the hidden one.

The 8 answers and their 3-bit indices (`ANSWERS` in `eight_ball.py`):

| index | bits | answer |
|---|---|---|
| 0 | `000` | It is certain |
| 1 | `001` | Without a doubt |
| 2 | `010` | You may rely on it |
| 3 | `011` | Ask again later |
| 4 | `100` | Cannot predict now |
| 5 | `101` | Don't count on it |
| 6 | `110` | My sources say no |
| 7 | `111` | Outlook not so good |

Note that your question's text has no effect on the physics — exactly
like a real 8-ball, the answer comes from the shake, not from what you
asked. `--question` is there purely so the output can echo it back.

## 5. Setup

Requires Python 3.9+ (tested with 3.9).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. Running locally (no AWS account needed)

```bash
python eight_ball.py "Will this project work?"
```

This uses Braket's built-in local simulator (no credentials, no cost)
and the default (optimal, `r=2`) number of Grover iterations, over
1000 shots so you can see the full amplified distribution, e.g.:

```
🎱 You asked: "Will this project work?"

Shaking the ball (quantum coin-flip picks a hidden answer)...
Hidden answer: 101 -> "Don't count on it" (kept secret until revealed below)

Running 1000 shot(s) on <LocalSimulator>...

Measurement counts:
  000: 5
  001: 9
  010: 8
  011: 7
  100: 9
  101: 938  <- hidden answer
  110: 16
  111: 8

🎱 The ball reveals: "Don't count on it"
(hidden answer measured 938/1000 = 93.8% of shots)
```

For a single, traditional "just give me one answer" reading:

```bash
python eight_ball.py --shots 1
```

To see the unamplified baseline or an overshot distribution from
§3.5's table:

```bash
python eight_ball.py --iterations 0   # ~12.5% each, uniformly random
python eight_ball.py --iterations 3   # amplified past the peak, ~33%
```

## 7. Running on AWS Braket

### 7.1 One-time AWS setup

1. Configure AWS credentials for a role/user with Braket permissions
   (`aws configure`, or an `AWS_PROFILE`/`AWS_ACCESS_KEY_ID` env var —
   anything the `boto3` credential chain picks up).
2. Braket needs an S3 bucket (same region as the device) for task
   results. The default bucket `amazon-braket-<region>-<account-id>`
   is created/used automatically; set a region if you haven't:
   ```bash
   export AWS_DEFAULT_REGION=us-east-1
   ```

### 7.2 Managed simulators

```bash
python eight_ball.py --device sv1
```

`sv1` (state-vector) is the standard choice for a circuit this small.
`dm1` (density matrix, supports noise models) and `tn1` (tensor
network) are also available. These are billed per task/shot — see
[Braket pricing](https://aws.amazon.com/braket/pricing/); SV1 is
inexpensive but not free.

### 7.3 Real quantum hardware (QPU)

```bash
python eight_ball.py --device qpu --qpu-arn "arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1" --shots 100
```

Check the [Braket console device
list](https://console.aws.amazon.com/braket/home#/devices) for
currently available QPU ARNs, regions, and pricing — **QPU tasks cost
real money per shot, billed even for a small `--shots` count.** Real
hardware is noisy, so expect the hidden answer's share of measurements
to land somewhat below the ~94.6% noiseless prediction, and the other
7 outcomes to be a bit more than perfectly flat — that's physical gate
and readout error, not a bug in the circuit.

## 8. Extending this

The real toy has 20 answers, not 8. Doing that properly would need
`n=5` qubits (`2⁵=32` states, since 20 isn't a power of 2), assigning
20 of the 32 basis states to real answers and treating the other 12 as
invalid outcomes to re-shake on, and a multi-marked-item oracle (the
"shake" step would need to reject invalid draws and retry, since it's
no longer uniform over exactly the valid answers). The Grover math for
multiple marked items `M` is a straightforward generalization of §3.5:
`sin(θ) = √(M/N)` instead of `√(1/N)`, with the same rotation and
iteration-count reasoning otherwise unchanged.
