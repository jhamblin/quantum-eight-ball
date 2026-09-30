"""A Magic 8-Ball, powered by Grover's algorithm on Amazon Braket.

Shake:  a genuine quantum coin-flip (H on each qubit + measure) picks a
        hidden "correct" answer uniformly among the possible answers --
        modeling the die tumbling to a random, hidden face inside a
        real 8-ball.
Reveal: Grover's algorithm searches the possibility space for that
        hidden answer and amplifies its probability close to 1, then a
        measurement reveals it -- modeling looking through the window.

The number of qubits (and therefore the number of possible answers,
2**qubits) is configurable with --qubits; it defaults to 3 (8 answers)
because that's the smallest circuit that still does real Grover
amplification. See README.md for the full math (oracle/diffuser
construction, the general multi-controlled-Z/ancilla construction used
for --qubits > 3, the rotation argument, and the iteration-count and
success-probability formulas) behind every step here.
"""

import argparse
import math
from typing import List, Optional

from braket.circuits import Circuit
from braket.devices import LocalSimulator

DEFAULT_QUBITS = 3

# The first 8 preserve the original fixed-8-answer version of this
# script, in the same order, so `--qubits 3` behaves identically to
# before. Answers beyond the 32 curated here are auto-generated
# placeholders -- see get_answers().
CURATED_ANSWERS = [
    "It is certain",
    "Without a doubt",
    "You may rely on it",
    "Ask again later",
    "Cannot predict now",
    "Don't count on it",
    "My sources say no",
    "Outlook not so good",
    "It is decidedly so",
    "Yes, definitely",
    "As I see it, yes",
    "Most likely",
    "Outlook good",
    "Signs point to yes",
    "Yes",
    "Reply hazy, try again",
    "Better not tell you now",
    "Concentrate and ask again",
    "The odds are impossible to calculate",
    "Very doubtful",
    "Signs point to no",
    "Highly unlikely",
    "The stars say no",
    "Chances are slim",
    "My reply is no",
    "Better not count on it",
    "The qubits are undecided",
    "Superposition says maybe",
    "Ask again after decoherence",
    "The wavefunction has not collapsed yet",
    "Entangled with another answer, unclear",
    "Only in a parallel universe",
]

MANAGED_SIMULATORS = {
    "sv1": "arn:aws:braket:::device/quantum-simulator/amazon/sv1",
    "dm1": "arn:aws:braket:::device/quantum-simulator/amazon/dm1",
    "tn1": "arn:aws:braket:::device/quantum-simulator/amazon/tn1",
}


def get_answers(n_qubits: int) -> List[str]:
    """Return exactly 2**n_qubits answer strings.

    Uses the curated list above as far as it goes; beyond that (more
    than 5 qubits / 32 answers) there's no more hand-written 8-ball
    flavor text, so the rest are generated placeholders.
    """
    n_answers = 2**n_qubits
    if n_answers <= len(CURATED_ANSWERS):
        return CURATED_ANSWERS[:n_answers]

    padding = [
        f"Response #{i} (uncharted qubit state)"
        for i in range(len(CURATED_ANSWERS), n_answers)
    ]
    return CURATED_ANSWERS + padding


def get_device(name: str, qpu_arn: Optional[str]):
    if name == "local":
        return LocalSimulator()

    # Imported lazily so `--device local` never requires AWS credentials.
    from braket.aws import AwsDevice

    if name == "qpu":
        if not qpu_arn:
            raise SystemExit("--qpu-arn is required when --device qpu")
        return AwsDevice(qpu_arn)

    return AwsDevice(MANAGED_SIMULATORS[name])


def optimal_iterations(n_items: int, n_marked: int = 1) -> int:
    """round(pi/4 * sqrt(N/M) - 1/2); see README section 3.5."""
    theta = math.asin(math.sqrt(n_marked / n_items))
    return round((math.pi / (4 * theta)) - 0.5)


def ancilla_count(n_controls: int) -> int:
    """Ancilla qubits needed to AND n_controls bits with 2-control Toffolis."""
    return max(0, n_controls - 2)


def multi_controlled_x(
    circuit: Circuit, controls: List[int], target: int, ancillas: List[int]
) -> None:
    """Flip `target` iff every qubit in `controls` is |1>.

    For up to 2 controls this is just CNOT/Toffoli directly. For more,
    it's the standard "ladder" decomposition: AND the controls down
    into a chain of ancilla qubits two at a time using Toffolis, use
    the last ancilla as the final control into `target`, then run the
    same Toffolis in reverse to reset the ancillas back to |0> (their
    required starting state). This keeps every gate a plain CNOT or a
    2-control Toffoli, so the circuit still only uses gates a real
    device (not just a simulator) can run.
    """
    k = len(controls)
    if k == 0:
        circuit.x(target)
        return
    if k == 1:
        circuit.cnot(controls[0], target)
        return
    if k == 2:
        circuit.ccnot(controls[0], controls[1], target)
        return

    assert len(ancillas) == k - 2, "need exactly k-2 ancilla qubits for k controls"

    chain = [controls[0], controls[1]] + ancillas  # AND accumulates along here
    # Forward: AND controls[0..k-2] down into ancillas[-1].
    circuit.ccnot(chain[0], chain[1], chain[2])
    for i in range(2, k - 1):
        circuit.ccnot(controls[i], chain[i], chain[i + 1])
    # Final control (controls[k-1]) AND the fully-accumulated ancilla -> target.
    circuit.ccnot(controls[k - 1], chain[-1], target)
    # Backward: uncompute the ancillas (but not `target`) back to |0>.
    for i in reversed(range(2, k - 1)):
        circuit.ccnot(controls[i], chain[i], chain[i + 1])
    circuit.ccnot(chain[0], chain[1], chain[2])


def phase_flip_all_ones(
    circuit: Circuit, qubits: List[int], ancillas: List[int]
) -> None:
    """Flip the sign of the |11...1> basis state across `qubits`.

    A multi-controlled-Z: use the last qubit as the phase-kickback
    target (Z = H X H) and every other qubit as a control into a
    multi-controlled-X on that target.
    """
    if len(qubits) == 1:
        circuit.z(qubits[0])
        return

    *controls, target = qubits
    circuit.h(target)
    multi_controlled_x(circuit, controls, target, ancillas)
    circuit.h(target)


def oracle(target_bits: str, qubits: List[int], ancillas: List[int]) -> Circuit:
    """Phase oracle: Uf|x> = -|x> if x == target_bits else |x>."""
    circuit = Circuit()
    zero_positions = [qubits[i] for i, bit in enumerate(target_bits) if bit == "0"]

    for q in zero_positions:
        circuit.x(q)
    phase_flip_all_ones(circuit, qubits, ancillas)
    for q in zero_positions:
        circuit.x(q)

    return circuit


def diffuser(qubits: List[int], ancillas: List[int]) -> Circuit:
    """Inversion about the mean: D = H^n (2|0..0><0..0| - I) H^n."""
    circuit = Circuit()
    for q in qubits:
        circuit.h(q)
    for q in qubits:
        circuit.x(q)
    phase_flip_all_ones(circuit, qubits, ancillas)
    for q in qubits:
        circuit.x(q)
    for q in qubits:
        circuit.h(q)
    return circuit


def build_grover_circuit(
    target_bits: str, iterations: int, qubits: List[int], ancillas: List[int]
) -> Circuit:
    circuit = Circuit()
    for q in qubits:
        circuit.h(q)
    for _ in range(iterations):
        circuit.add_circuit(oracle(target_bits, qubits, ancillas))
        circuit.add_circuit(diffuser(qubits, ancillas))
    return circuit


def shake(device, qubits: List[int]) -> str:
    """Quantum coin-flip: uniform superposition + one measurement."""
    circuit = Circuit()
    for q in qubits:
        circuit.h(q)
    result = device.run(circuit, shots=1).result()
    return next(iter(result.measurement_counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "question", nargs="?", default=None, help="A question, for flavor only."
    )
    parser.add_argument(
        "--qubits",
        type=int,
        default=DEFAULT_QUBITS,
        help=f"Number of qubits, giving 2**qubits possible answers "
        f"(default: {DEFAULT_QUBITS}, i.e. 8 answers).",
    )
    parser.add_argument(
        "--device",
        choices=["local", *MANAGED_SIMULATORS, "qpu"],
        default="local",
        help="Where to run the circuits (default: local).",
    )
    parser.add_argument(
        "--qpu-arn",
        default=None,
        help="Device ARN to use when --device qpu.",
    )
    parser.add_argument(
        "--shots",
        type=int,
        default=1000,
        help="Measurement shots for the reveal circuit (default: 1000). "
        "Use --shots 1 for a single real answer.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Override the number of Grover iterations. Defaults to the "
        "theoretical optimum for --qubits. --iterations 0 skips "
        "amplification entirely, for comparison.",
    )
    args = parser.parse_args()

    if args.qubits < 1:
        raise SystemExit("--qubits must be at least 1")

    n_answers = 2**args.qubits
    answers = get_answers(args.qubits)
    main_qubits = list(range(args.qubits))
    n_ancillas = ancilla_count(args.qubits - 1)  # phase_flip_all_ones uses n-1 controls
    ancillas = list(range(args.qubits, args.qubits + n_ancillas))

    if args.question:
        print(f'\U0001f3b1 You asked: "{args.question}"')

    device = get_device(args.device, args.qpu_arn)

    print(
        f"\nShaking the ball ({args.qubits}-qubit coin-flip picks 1 of "
        f"{n_answers} hidden answers)..."
    )
    target_bits = shake(device, main_qubits)
    target_index = int(target_bits, 2)
    print(
        f'Hidden answer: {target_bits} -> "{answers[target_index]}" '
        "(kept secret until revealed below)"
    )

    iterations = (
        args.iterations if args.iterations is not None else optimal_iterations(n_answers)
    )
    circuit = build_grover_circuit(target_bits, iterations, main_qubits, ancillas)
    total_qubits = args.qubits + n_ancillas
    print(
        f"\nGrover circuit ({args.qubits} answer qubits"
        + (f" + {n_ancillas} ancilla" if n_ancillas else "")
        + f" = {total_qubits} total, {iterations} iteration(s)):"
    )
    if total_qubits <= 5:
        print(circuit)
    else:
        print(
            f"  (diagram omitted: {circuit.depth} layers deep across "
            f"{total_qubits} qubits, too wide to print legibly)"
        )

    print(f"\nRunning {args.shots} shot(s) on {device}...")
    result = device.run(circuit, shots=args.shots).result()
    full_counts = result.measurement_counts

    # Collapse out the ancilla bits (should always read 0 -- see README);
    # keep just the answer-qubit prefix of each measured bitstring.
    counts = {}
    ancilla_leakage = 0
    for bitstring, count in full_counts.items():
        answer_bits, anc_bits = bitstring[: args.qubits], bitstring[args.qubits :]
        if "1" in anc_bits:
            ancilla_leakage += count
        counts[answer_bits] = counts.get(answer_bits, 0) + count

    print("\nMeasurement counts:")
    for bitstring in sorted(counts):
        marker = "  <- hidden answer" if bitstring == target_bits else ""
        print(f"  {bitstring}: {counts[bitstring]}{marker}")

    if ancilla_leakage:
        print(
            f"\n(note: {ancilla_leakage}/{args.shots} shots left an ancilla "
            "qubit as |1> instead of resetting to |0> -- a sign of gate "
            "noise, expected on real QPUs but not on simulators)"
        )

    revealed_bits = max(counts, key=counts.get)
    revealed_index = int(revealed_bits, 2)
    hit_rate = counts.get(target_bits, 0) / args.shots

    print(f'\n\U0001f3b1 The ball reveals: "{answers[revealed_index]}"')
    print(
        f"(hidden answer measured {counts.get(target_bits, 0)}/{args.shots} = "
        f"{hit_rate:.1%} of shots)"
    )


if __name__ == "__main__":
    main()
