"""Helpers for tii-q-cloud-mcp: client construction and data serialisation."""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import TYPE_CHECKING

import qibo

if TYPE_CHECKING:
    from tii_quantum import Client


_TOKEN_ENV = "TII_QUANTUM_TOKEN"


def get_client() -> Client:
    """Return an authenticated :class:`tii_quantum.Client`.

    Reads the API token from the ``TII_QUANTUM_TOKEN`` environment variable.

    Raises:
        RuntimeError: If the environment variable is not set.
    """
    import tii_quantum

    token = os.environ.get(_TOKEN_ENV)
    if not token:
        raise RuntimeError(
            f"Environment variable {_TOKEN_ENV!r} is not set. "
            "Please export your TII Q-Cloud API token before starting the server."
        )
    return tii_quantum.Client(token=token)


def circuit_from_input(circuit_input: str) -> qibo.Circuit:
    """Parse *circuit_input* and return a :class:`qibo.Circuit`.

    Two formats are accepted, auto-detected:

    * **QASM 2.0** — a string starting with ``OPENQASM`` (case-insensitive).
    * **qibo JSON** — a JSON-encoded ``circuit.raw`` dict (must contain a
      ``"queue"`` key).

    Args:
        circuit_input: The circuit encoded as QASM 2.0 text or a JSON string.

    Returns:
        A :class:`qibo.Circuit` ready for submission.

    Raises:
        ValueError: If the input cannot be parsed as either format.
    """
    stripped = circuit_input.strip()

    if stripped.upper().startswith("OPENQASM"):
        try:
            return qibo.Circuit.from_qasm(stripped)
        except Exception as exc:
            raise ValueError(f"Failed to parse QASM input: {exc}") from exc

    # Try qibo JSON (circuit.raw)
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "circuit_input is neither a valid QASM string (must start with 'OPENQASM') "
            f"nor valid JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict) or "queue" not in raw:
        raise ValueError(
            "JSON circuit_input must be a qibo circuit.raw dict containing a 'queue' key. "
            f"Got top-level keys: {list(raw.keys())}"
        )

    try:
        return qibo.Circuit.from_dict(raw)
    except Exception as exc:
        raise ValueError(f"Failed to parse qibo JSON circuit: {exc}") from exc


def result_to_markdown(result: qibo.result.QuantumState, pid: str, max_samples: int = 20) -> str:
    """Serialise a :class:`qibo.result.QuantumState` to a Markdown string.

    Args:
        result:      The measurement result returned by ``QiboJob.result()``.
        pid:         Job PID, included in the header for traceability.
        max_samples: Maximum number of individual bitstring samples to show.

    Returns:
        A Markdown-formatted string with frequencies and a sample table.
    """
    lines: list[str] = [f"## Results for job `{pid}`\n"]

    # Frequencies
    try:
        freqs: Counter = result.frequencies()
        total = sum(freqs.values())
        lines.append("### Measurement frequencies\n")
        lines.append("| Bitstring | Count | Probability |")
        lines.append("|-----------|-------|-------------|")
        for bitstring, count in sorted(freqs.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{bitstring}` | {count} | {count / total:.4f} |")
        lines.append("")
    except Exception as exc:
        lines.append(f"*Could not extract frequencies: {exc}*\n")

    # Raw samples (first max_samples)
    try:
        samples = result.samples()
        lines.append(f"### First {min(max_samples, len(samples))} samples\n")
        lines.append("```")
        for row in samples[:max_samples]:
            lines.append("".join(str(b) for b in row))
        lines.append("```")
    except Exception:
        pass  # samples not always available (e.g. state-vector backends)

    return "\n".join(lines)
