# Quantum Magic 8-Ball

A Magic 8-Ball, but the "magic" is Grover's search algorithm running on
AWS Braket. Ask a question, shake the ball, and a genuinely quantum
process picks and then reveals your answer. Runs identically against
Braket's free local simulator or a managed AWS simulator/QPU — same
circuits, same code, just a different `--device` flag. The number of
qubits (and therefore the number of possible answers) is a `--qubits`
flag, defaulting to 3 (8 answers).

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

This program mirrors that two-step structure, using `n` qubits and
`2ⁿ` possible answers (`--qubits n`, default `n=3` — 8 answers, one
satisfying reason "eight ball" and "3 qubits" go well together, and
the smallest circuit that still does real Grover amplification):

1. **Shake.** A quantum coin-flip circuit (`H` on each of `n` qubits,
   then measure) picks one of the `2ⁿ` answers uniformly at random.
   This is the die settling — a real physical random process, not a
   pseudorandom number generator.
2. **Reveal.** **Grover's algorithm** is used to search the `2ⁿ`
   possibilities for that specific hidden answer, amplifying its
   measurement probability from an unhelpful `1/2ⁿ` up to nearly 100%
   (the exact figure depends on `n` — see §3.6), so that measuring the
   circuit reveals it.

Step 2 is the actual point of this project: it's a small, concrete,
verifiable demonstration of Grover's algorithm, using the hidden
answer from step 1 as the "needle" Grover has to find in the
"haystack" of `2ⁿ` possibilities. Turning up `--qubits` doesn't change
what the program does, just how big a haystack Grover has to search —
it's a good way to see the algorithm's behavior (iteration count,
success probability, circuit size) scale with `N`.

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

You have `N` items (here `N=2ⁿ`, indexed by `n`-bit strings — `N=8`
with the default `--qubits 3`) and a
**black-box oracle** that can tell you whether a given item is "the
marked one" `w` — but you can't just peek at `w` directly, only query
the oracle. Classically, finding `w` by querying one item at a time
takes `N/2` queries on average, `N` in the worst case. **Grover's
algorithm finds it in about `√N` oracle queries** — a quadratic
speedup that's also *provably optimal* (no quantum algorithm can do
better than `Θ(√N)` for this problem).

In this program, "the marked item" is the hidden answer chosen by the
shake step, and the oracle is built from that specific `n`-bit string
— see §3.3. This is a slightly artificial setup (the code technically
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
is chosen based on `N` (see §3.6) — too few iterations undershoots,
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
measured right away. It only matters once the diffuser (§3.5) uses
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

This is the 3-qubit case; §3.4 generalizes it to any `n`.

### 3.4 Generalizing beyond 3 qubits: multi-controlled-Z with ancillas

The `n=3` oracle needed one 3-qubit gate, CCZ, built from Braket's
built-in 3-qubit Toffoli. For `n` qubits, the same construction needs
an `n`-qubit multi-controlled-Z (flip the sign of `|1...1⟩` across all
`n` qubits) — and there's no larger built-in Toffoli to lean on.
Braket only ever gives you 1- and 2-control gates natively
(`cnot`/`cz` and `ccnot`), on simulators and real devices alike, so
anything with more controls has to be *decomposed* into those.

**The trick: an ancilla "ladder."** An `n`-qubit multi-controlled-Z is
just an `(n-1)`-control, 1-target multi-controlled-**X** (call the
number of controls `k = n-1`), sandwiched by `H` on the target — the
same `Z = H·X·H` identity as before. For `k ≤ 2` controls, that's a
plain `CNOT`/`CCNOT`, exactly §3.3's case. For `k > 2`, borrow `k-2`
extra **ancilla qubits** (starting and ending at `|0⟩`) and AND the
controls together two at a time, chaining through the ancillas with
ordinary Toffolis:

```
Toffoli(control₀, control₁  -> ancilla₀)          ancilla₀ = c₀ ∧ c₁
Toffoli(control₂, ancilla₀  -> ancilla₁)          ancilla₁ = c₀ ∧ c₁ ∧ c₂
   ...
Toffoli(controlₖ₋₁, ancillaₖ₋₃ -> target)         target ⊕= AND of all k controls
```

Then run the *same* Toffolis again, in reverse, skipping only the last
one — Toffoli gates are their own inverse, so this "uncomputes" every
ancilla back to `|0⟩` without touching `target`, leaving the ancillas
clean for the next time this oracle or diffuser runs. The result:
`target` flips iff every control was `|1⟩`, using only 2-control
gates throughout, so this still runs on real hardware, not just
simulators — it's just a bigger circuit. This ladder needs
`max(0, k-2)` ancilla qubits for `k` controls; since the oracle/diffuser
here always have `k = n-1` controls, that's `max(0, n-3)` ancillas
total (`0` for `n≤3`, matching §3.3 exactly — `n=4` needs 1, `n=5`
needs 2, and the `n=8` case needs 5, for 13 qubits total).

`multi_controlled_x()` in `eight_ball.py` implements exactly this
ladder, and `phase_flip_all_ones()` wraps it with the `H`-sandwich to
turn it into the multi-controlled-Z that both `oracle()` and
`diffuser()` are built from — for any `n`, including `n=3` (where it
collapses back to the plain CCZ of §3.3, with zero ancillas).

### 3.5 The diffuser: inversion about the mean

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
pushes it higher still (§3.6).

### 3.6 How many iterations, and how likely is success?

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

**Scaling with `--qubits`.** Bigger `N` means a smaller starting angle
`θ`, so it takes more iterations to rotate up to `π/2` — but also lands
closer to it, since `r` is a discrete number of `2θ`-sized steps trying
to hit a continuous target. Both effects are visible in practice
(`optimal_iterations()`'s predictions vs. what `eight_ball.py` actually
measured, each run at the optimal `r`):

| `--qubits` | `N` | ancillas needed | optimal `r` | predicted `P(r)` | measured |
|---|---|---|---|---|---|
| 3 (default) | 8 | 0 | 2 | 94.6% | 93.8%–94.2% |
| 4 | 16 | 1 | 3 | 96.2% | 95.5% |
| 5 | 32 | 2 | 4 | 99.9% | 99.9% |
| 8 | 256 | 5 | 12 | ~99.99% | 100.0% (1000/1000) |

so larger `--qubits` values don't just search a bigger haystack, they
generally find the answer *more* reliably too, at the cost of a much
larger circuit (§3.4's ancilla ladder, and more Grover iterations).

## 4. The code

[`eight_ball.py`](eight_ball.py) implements every piece above, for any
`--qubits n`:

- `shake(device, qubits)` — the `H⊗n` + 1-shot-measurement "coin flip"
  from §2, picking the hidden answer.
- `multi_controlled_x(circuit, controls, target, ancillas)` — §3.4's
  ancilla ladder: a plain `CNOT`/`CCNOT` for ≤2 controls, the AND-chain
  construction for more.
- `phase_flip_all_ones(circuit, qubits, ancillas)` — the `H`-sandwich
  around `multi_controlled_x` that turns it into a multi-controlled-Z;
  this is the one piece both the oracle and the diffuser are built
  from (it's what `ccz` was in the fixed-3-qubit version).
- `oracle(target_bits, qubits, ancillas)` — §3.3's `X`-sandwiched
  phase flip, built for whichever `n`-bit string `shake()` returned.
- `diffuser(qubits, ancillas)` — §3.5's `H`/`X`-sandwiched phase flip
  (target `0...0`).
- `optimal_iterations(n_items)` — §3.6's `round(π/(4θ) - 1/2)`.
- `ancilla_count(n_controls)` — §3.4's `max(0, n_controls - 2)`.
- `build_grover_circuit(target_bits, iterations, qubits, ancillas)` —
  `H⊗n` once, then `oracle` + `diffuser` repeated `iterations` times.
- `get_answers(n_qubits)` — returns exactly `2ⁿ` answer strings (see
  below).
- `main()` — ties it together: work out how many ancillas `--qubits`
  needs, shake, build and run the Grover circuit, strip the ancilla
  bits back off each measured bitstring, print the full histogram, and
  report the most-measured answer plus how often it matched the hidden
  one.

**The answers.** `CURATED_ANSWERS` in `eight_ball.py` is a hand-written
list of 32 Magic-8-Ball-style phrases — enough to fully cover
`--qubits` up to 5 (`2⁵=32`). `get_answers(n_qubits)` returns the first
`2ⁿ` of those; the default `--qubits 3` uses exactly the first 8, in
this order:

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

Past 5 qubits (more than 32 answers needed) there's no more curated
flavor text, so `get_answers()` pads with generic placeholders like
`"Response #99 (uncharted qubit state)"` — the point past `--qubits 5`
is watching Grover's behavior scale (§3.6's table), not reading
clever phrases.

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

### 5.1 Running the tests

[`test_eight_ball.py`](test_eight_ball.py) codifies every check used to
verify the math in this README while building it: the ancilla-ladder
`multi_controlled_x()` against its full truth table (for every input
where the ancillas correctly start at `|0⟩`), the multi-controlled-Z
phase flip against the exact expected unitary diagonal, `optimal_iterations()`
against known values, `get_answers()`'s backward-compatible ordering
and padding, and — as a statistical check with a tolerance band, since
these are real measurement outcomes — the full oracle+diffuser circuit's
success probability against §3.6's `sin²((2r+1)θ)` formula at several
`--qubits` values, plus the exact under/optimal/overshoot table from
§3.6. Runs entirely on the local simulator; no AWS credentials needed.

```bash
pip install -r requirements-dev.txt
pytest
```

## 6. Running locally (no AWS account needed)

```bash
python eight_ball.py "Will this project work?"
```

This uses Braket's built-in local simulator (no credentials, no cost),
the default `--qubits 3` (8 answers), and the default (optimal, `r=2`)
number of Grover iterations, over 1000 shots so you can see the full
amplified distribution, e.g.:

```
🎱 You asked: "Will this project work?"

Shaking the ball (3-qubit coin-flip picks 1 of 8 hidden answers)...
[... shake circuit diagram: H on each of the 3 qubits ...]
Hidden answer: 010 -> "You may rely on it" (kept secret until revealed below)

Grover circuit (3 answer qubits = 3 total, 2 iteration(s)):
[... circuit diagram ...]

Running 1000 shot(s) on <LocalSimulator>...

Measurement counts:
  000: 7
  001: 3
  010: 942  <- hidden answer
  011: 9
  100: 10
  101: 13
  110: 9
  111: 7

🎱 The ball reveals: "You may rely on it"
(hidden answer measured 942/1000 = 94.2% of shots)
```

Try a bigger search space with `--qubits`, e.g. `--qubits 8` (256
answers, 12 Grover iterations, 5 ancilla qubits — see §3.6's table):

```bash
python eight_ball.py --qubits 8
```

The circuit diagram is only printed for small circuits (5 qubits or
fewer); larger ones just report how many qubits and layers deep the
circuit is, since a 13-qubit, 300+ layer diagram isn't legible in a
terminal anyway.

For a single, traditional "just give me one answer" reading:

```bash
python eight_ball.py --shots 1
```

To see the unamplified baseline or an overshot distribution from
§3.6's table:

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
to land somewhat below the noiseless prediction in §3.6's table, and
the other outcomes to be a bit more than perfectly flat — that's
physical gate and readout error, not a bug in the circuit. This gets
worse as `--qubits` grows: more qubits means more Grover iterations
(§3.6) *and* more ancilla-ladder gates per iteration (§3.4), so the
circuit gets substantially deeper — `--qubits 8` is 12 iterations over
13 qubits, hundreds of gates deep, which will be considerably noisier
on today's hardware than `--qubits 3`'s much shorter circuit. Small
`--qubits` values are the realistic choice for an actual QPU run;
larger ones are best explored on the local simulator or SV1/DM1/TN1.

## 8. Extending this

The real toy has 20 answers, not a power of 2. Everything in this
repo generalizes cleanly to `2ⁿ` answers for any `n` (that's the whole
point of `--qubits`), but 20 isn't `2ⁿ` for any integer `n` — the
nearest fit is `n=5` (32 states), which would need 12 of those 32
basis states marked "invalid" and the shake step to reject and re-draw
until it lands on one of the 20 real ones. The oracle would also need
to become a **multi-marked-item** oracle (flip the sign of all 20 valid
states, not just 1), which is a small change to §3.3's construction:
apply `X` to map each valid target individually and flip its sign, or
equivalently build a phase oracle straight from a lookup table of
valid/invalid rather than a single bitstring comparison. The rest of
the Grover math is a straightforward generalization of §3.6:
`sin(θ) = √(M/N)` instead of `√(1/N)` for `M` marked items, with the
same rotation and iteration-count reasoning otherwise unchanged.
