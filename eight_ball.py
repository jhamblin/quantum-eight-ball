"""A Magic 8-Ball, powered by Grover's algorithm on Amazon Braket.

Shake:  a genuine quantum coin-flip (H on each qubit + measure) picks a
        hidden "correct" answer uniformly among 8 possibilities --
        modeling the die tumbling to a random, hidden face inside a
        real 8-ball.
Reveal: Grover's algorithm searches the 8 possibilities for that
        hidden answer and amplifies its probability close to 1, then a
        measurement reveals it -- modeling looking through the window.

See README.md for the full math (oracle/diffuser construction, the
rotation argument, and the iteration-count and success-probability
formulas) behind every step here.
"""

import argparse
import math
from typing import Optional

from braket.circuits import Circuit
from braket.devices import LocalSimulator

N_QUBITS = 3
N_ANSWERS = 2**N_QUBITS  # 8

ANSWERS = [
    "It is certain",
    "Without a doubt",
    "You may rely on it",
    "Ask again later",
    "Cannot predict now",
    "Don't count on it",
    "My sources say no",
    "Outlook not so good",
]

MANAGED_SIMULATORS = {
    "sv1": "arn:aws:braket:::device/quantum-simulator/amazon/sv1",
    "dm1": "arn:aws:braket:::device/quantum-simulator/amazon/dm1",
    "tn1": "arn:aws:braket:::device/quantum-simulator/amazon/tn1",
}


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
    """round(pi/4 * sqrt(N/M) - 1/2); see README section 3.4."""
    theta = math.asin(math.sqrt(n_marked / n_items))
    return round((math.pi / (4 * theta)) - 0.5)


def ccz(circuit: Circuit, q0: int, q1: int, q2: int) -> Circuit:
    """Controlled-controlled-Z: flips the sign of |111> only.

    Built from the identity Z = H X H, so sandwiching a Toffoli's
    target with H turns its controlled-X into a controlled-Z.
    """
    circuit.h(q2)
    circuit.ccnot(q0, q1, q2)
    circuit.h(q2)
    return circuit


def oracle(target_bits: str) -> Circuit:
    """Phase oracle: Uf|x> = -|x> if x == target_bits else |x>."""
    circuit = Circuit()
    zero_positions = [i for i, bit in enumerate(target_bits) if bit == "0"]

    for i in zero_positions:
        circuit.x(i)
    ccz(circuit, 0, 1, 2)
    for i in zero_positions:
        circuit.x(i)

    return circuit


def diffuser() -> Circuit:
    """Inversion about the mean: D = H^3 (2|000><000| - I) H^3."""
    circuit = Circuit()
    circuit.h(0).h(1).h(2)
    circuit.x(0).x(1).x(2)
    ccz(circuit, 0, 1, 2)
    circuit.x(0).x(1).x(2)
    circuit.h(0).h(1).h(2)
    return circuit


def build_grover_circuit(target_bits: str, iterations: int) -> Circuit:
    circuit = Circuit().h(0).h(1).h(2)
    for _ in range(iterations):
        circuit.add_circuit(oracle(target_bits))
        circuit.add_circuit(diffuser())
    return circuit


def shake(device) -> str:
    """Quantum coin-flip: uniform superposition + one measurement."""
    circuit = Circuit().h(0).h(1).h(2)
    result = device.run(circuit, shots=1).result()
    return next(iter(result.measurement_counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "question", nargs="?", default=None, help="A question, for flavor only."
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
        "theoretical optimum (2, for 8 answers). --iterations 0 skips "
        "amplification entirely, for comparison.",
    )
    args = parser.parse_args()

    if args.question:
        print(f'\U0001f3b1 You asked: "{args.question}"')

    device = get_device(args.device, args.qpu_arn)

    print("\nShaking the ball (quantum coin-flip picks a hidden answer)...")
    target_bits = shake(device)
    target_index = int(target_bits, 2)
    print(f"Hidden answer: {target_bits} -> \"{ANSWERS[target_index]}\" (kept secret until revealed below)")

    iterations = (
        args.iterations if args.iterations is not None else optimal_iterations(N_ANSWERS)
    )
    circuit = build_grover_circuit(target_bits, iterations)
    print(f"\nGrover circuit ({N_QUBITS} qubits, {iterations} iteration(s)):")
    print(circuit)

    print(f"\nRunning {args.shots} shot(s) on {device}...")
    result = device.run(circuit, shots=args.shots).result()
    counts = result.measurement_counts

    print("\nMeasurement counts:")
    for bitstring in sorted(counts):
        marker = "  <- hidden answer" if bitstring == target_bits else ""
        print(f"  {bitstring}: {counts[bitstring]}{marker}")

    revealed_bits = max(counts, key=counts.get)
    revealed_index = int(revealed_bits, 2)
    hit_rate = counts.get(target_bits, 0) / args.shots

    print(f"\n\U0001f3b1 The ball reveals: \"{ANSWERS[revealed_index]}\"")
    print(
        f"(hidden answer measured {counts.get(target_bits, 0)}/{args.shots} = "
        f"{hit_rate:.1%} of shots)"
    )


if __name__ == "__main__":
    main()
