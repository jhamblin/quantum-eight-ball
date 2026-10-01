"""Tests for eight_ball.py.

Run with:
    pip install -r requirements-dev.txt
    pytest

Covers the same checks done by hand while building this script:
correctness of the ancilla-ladder multi-controlled-X and the
multi-controlled-Z phase oracle it's built from, the optimal-iteration
and ancilla-count formulas, the answer list, and -- as a statistical
check against Grover's theoretical success-probability formula from
README.md section 3.6 -- the full oracle+diffuser circuit end to end.
"""

import json
import math
import os
import subprocess
import sys

import numpy as np
import pytest
from braket.circuits import Circuit
from braket.devices import LocalSimulator

import eight_ball as eb


def _run_once(circuit: Circuit) -> str:
    """Run a circuit with no superposition left in it and read the (single,
    deterministic) resulting bitstring."""
    result = LocalSimulator().run(circuit, shots=1).result()
    return next(iter(result.measurement_counts))


# --- multi_controlled_x: the ancilla-ladder AND, §3.4 --------------------


@pytest.mark.parametrize("k", [0, 1, 2, 3, 4, 5])
def test_multi_controlled_x_truth_table(k):
    """For every input where the ancillas start at |0> (the construction's
    only valid domain -- see README §3.4), target flips iff every control
    is 1, and the ancillas end back at |0>."""
    controls = list(range(k))
    target = k
    ancillas = list(range(k + 1, k + 1 + eb.ancilla_count(k)))
    n_total = k + 1 + len(ancillas)

    for control_bits in range(2**k):
        control_values = [(control_bits >> (k - 1 - i)) & 1 for i in range(k)]
        for target_start in (0, 1):
            circuit = Circuit()
            for q, bit in zip(controls, control_values):
                if bit:
                    circuit.x(q)
            if target_start:
                circuit.x(target)

            eb.multi_controlled_x(circuit, controls, target, ancillas)

            bits = _run_once(circuit)
            expected_target = target_start ^ (1 if all(control_values) else 0)

            assert int(bits[target]) == expected_target, (
                f"k={k} controls={control_values} target_start={target_start}: "
                f"expected target={expected_target}, got {bits[target]}"
            )
            assert bits[k + 1 :] == "0" * len(ancillas), (
                f"k={k}: ancillas should reset to 0, got {bits[k + 1:]!r}"
            )


@pytest.mark.parametrize("k,expected", [(0, 0), (1, 0), (2, 0), (3, 1), (4, 2), (5, 3), (7, 5)])
def test_ancilla_count(k, expected):
    assert eb.ancilla_count(k) == expected


# --- phase_flip_all_ones: the multi-controlled-Z oracle building block ---


@pytest.mark.parametrize("n_qubits", [1, 2, 3, 4, 5])
def test_phase_flip_all_ones_flips_only_all_ones(n_qubits):
    """Checked via the circuit's unitary rather than measurement, since a
    global/relative phase flip isn't visible in a computational-basis
    measurement by itself (see README §3.3)."""
    qubits = list(range(n_qubits))
    ancillas = list(range(n_qubits, n_qubits + eb.ancilla_count(n_qubits - 1)))
    n_anc = len(ancillas)
    n_total = n_qubits + n_anc

    circuit = Circuit()
    eb.phase_flip_all_ones(circuit, qubits, ancillas)
    unitary = circuit.to_unitary()

    for x in range(2**n_total):
        anc_bits = x & ((1 << n_anc) - 1) if n_anc else 0
        if anc_bits != 0:
            continue  # ancillas must start at |0>; outside that, undefined.

        main_value = x >> n_anc
        expected_sign = -1 if main_value == 2**n_qubits - 1 else 1

        column = unitary[:, x]
        nonzero = np.flatnonzero(np.abs(column) > 1e-9)
        assert list(nonzero) == [x], "a phase flip must not move any basis state"
        assert column[x].real == pytest.approx(expected_sign, abs=1e-9)
        assert column[x].imag == pytest.approx(0, abs=1e-9)


# --- optimal_iterations: the rotation-count formula, §3.6 ----------------


@pytest.mark.parametrize(
    "n_items,expected", [(2, 0), (4, 1), (8, 2), (16, 3), (32, 4), (256, 12)]
)
def test_optimal_iterations(n_items, expected):
    assert eb.optimal_iterations(n_items) == expected


# --- answers -------------------------------------------------------------


def test_get_answers_matches_original_fixed_8_answer_order():
    assert eb.get_answers(3) == [
        "It is certain",
        "Without a doubt",
        "You may rely on it",
        "Ask again later",
        "Cannot predict now",
        "Don't count on it",
        "My sources say no",
        "Outlook not so good",
    ]


def test_get_answers_pads_beyond_the_curated_list():
    answers = eb.get_answers(6)  # 64 answers, only 32 curated
    assert len(answers) == 64
    assert answers[:32] == eb.CURATED_ANSWERS
    assert all("uncharted" in a for a in answers[32:])


# --- GenAI answer generation (--genai), §4.1 ------------------------------


def test_extract_json_array_plain():
    assert eb._extract_json_array('["a", "b"]') == ["a", "b"]


def test_extract_json_array_with_prose_and_fences():
    text = 'Sure, here you go:\n```json\n["x", "y", "z"]\n```\nHope that helps!'
    assert eb._extract_json_array(text) == ["x", "y", "z"]


def test_extract_json_array_missing_raises():
    with pytest.raises(SystemExit):
        eb._extract_json_array("no array here")


def test_generate_genai_answers_caches_and_reuses(tmp_path, monkeypatch):
    """Mocks the Bedrock client -- no AWS credentials needed -- to check the
    caching behavior: one API call for a fresh request, zero for a repeat."""
    anthropic = pytest.importorskip("anthropic")
    monkeypatch.setattr(eb, "GENAI_CACHE_PATH", str(tmp_path / "cache.json"))

    calls = []

    class FakeTextBlock:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class FakeResponse:
        def __init__(self, answers):
            self.content = [FakeTextBlock(json.dumps(answers))]

    class FakeMessages:
        def create(self, model, max_tokens, messages):
            calls.append(messages[0]["content"])
            return FakeResponse([f"fake answer {len(calls)}-{i}" for i in range(3)])

    class FakeClient:
        def __init__(self, aws_region=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AnthropicBedrockMantle", FakeClient)

    first = eb.generate_genai_answers(3, "fake-model", "us-east-1")
    assert len(first) == 3
    assert len(calls) == 1

    second = eb.generate_genai_answers(3, "fake-model", "us-east-1")
    assert second == first
    assert len(calls) == 1  # served from the cache, no second API call


def test_get_answers_uses_genai_only_beyond_curated_list(tmp_path, monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    monkeypatch.setattr(eb, "GENAI_CACHE_PATH", str(tmp_path / "cache.json"))

    class FakeMessages:
        def create(self, model, max_tokens, messages):
            return type("R", (), {"content": [type("B", (), {"type": "text", "text": "[]"})()]})()

    class FakeClient:
        def __init__(self, aws_region=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AnthropicBedrockMantle", FakeClient)

    # 3 qubits needs only curated answers -- --genai should be a no-op here,
    # i.e. it must not even try to instantiate the Bedrock client.
    answers = eb.get_answers(3, use_genai=True)
    assert answers == eb.CURATED_ANSWERS[:8]


# --- shake: the quantum coin-flip -----------------------------------------


@pytest.mark.parametrize("n_qubits", [1, 3, 5])
def test_shake_returns_a_valid_bitstring(n_qubits):
    device = LocalSimulator()
    for _ in range(5):
        bits = eb.shake(device, list(range(n_qubits)))
        assert len(bits) == n_qubits
        assert set(bits) <= {"0", "1"}


# --- get_device ------------------------------------------------------------


def test_get_device_local_needs_no_aws_credentials():
    device = eb.get_device("local", None)
    assert isinstance(device, LocalSimulator)


def test_get_device_qpu_requires_an_arn():
    with pytest.raises(SystemExit):
        eb.get_device("qpu", None)


# --- end-to-end Grover amplification, against the §3.6 formula -----------


@pytest.mark.parametrize(
    "n_qubits,shots",
    [(3, 3000), (4, 3000), (5, 3000)],
)
def test_grover_amplifies_to_the_predicted_probability(n_qubits, shots):
    qubits = list(range(n_qubits))
    ancillas = list(range(n_qubits, n_qubits + eb.ancilla_count(n_qubits - 1)))
    n_items = 2**n_qubits
    target_bits = format(n_items // 3, f"0{n_qubits}b")
    iterations = eb.optimal_iterations(n_items)

    circuit = eb.build_grover_circuit(target_bits, iterations, qubits, ancillas)
    result = LocalSimulator().run(circuit, shots=shots).result()
    counts = result.measurement_counts

    hits = sum(c for bits, c in counts.items() if bits[:n_qubits] == target_bits)
    measured = hits / shots

    theta = math.asin(math.sqrt(1 / n_items))
    predicted = math.sin((2 * iterations + 1) * theta) ** 2

    assert measured == pytest.approx(predicted, abs=0.05), (
        f"n_qubits={n_qubits}: predicted {predicted:.3f}, measured {measured:.3f}"
    )

    leaked = sum(c for bits, c in counts.items() if "1" in bits[n_qubits:])
    assert leaked == 0, "ancillas leaked on a noiseless simulator"


@pytest.mark.parametrize(
    "iterations,expected",
    [(0, 0.125), (1, 0.781), (2, 0.946), (3, 0.329)],
)
def test_grover_iteration_scan_matches_readme_table(iterations, expected):
    """README §3.6's under/optimal/overshoot table, for the default 3 qubits."""
    target_bits = "101"
    circuit = eb.build_grover_circuit(target_bits, iterations, [0, 1, 2], [])
    result = LocalSimulator().run(circuit, shots=3000).result()
    measured = result.measurement_counts.get(target_bits, 0) / 3000
    assert measured == pytest.approx(expected, abs=0.04)


# --- CLI smoke test --------------------------------------------------------


def test_cli_runs_end_to_end():
    result = subprocess.run(
        [sys.executable, "eight_ball.py", "--qubits", "3", "--shots", "50"],
        cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "The ball reveals" in result.stdout
