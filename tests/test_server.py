"""Tests for tii-q-cloud-mcp server tools."""

from __future__ import annotations

from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import qibo
from fastmcp.server.elicitation import AcceptedElicitation, CancelledElicitation
from qibo import gates

from tii_quantum_mcp.client import MAX_FREQUENCY_OUTCOMES, circuit_from_input, result_to_markdown
from tii_quantum_mcp.server import (
    delete_job,
    get_job_result,
    get_job_status,
    get_quota,
    list_available_targets,
    list_jobs,
    submit_circuit,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BELL_QASM = """\
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""

BELL_JSON_RAW: dict = {
    "queue": [
        {
            "name": "h",
            "init_args": [0],
            "init_kwargs": {},
            "_target_qubits": [0],
            "_control_qubits": [],
            "_class": "H",
        },
        {
            "name": "cx",
            "init_args": [0, 1],
            "init_kwargs": {},
            "_target_qubits": [1],
            "_control_qubits": [0],
            "_class": "CNOT",
        },
        {
            "name": "measure",
            "init_args": [0, 1],
            "init_kwargs": {
                "register_name": None,
                "collapse": False,
                "basis": ["Z", "Z"],
                "p0": None,
                "p1": None,
            },
            "_target_qubits": [0, 1],
            "_control_qubits": [],
            "_class": "M",
            "measurement_result": {"samples": None},
        },
    ],
    "nqubits": 2,
    "density_matrix": False,
    "wire_names": [0, 1],
    "qibo_version": "0.3.2",
}

AVAILABLE_TARGETS = [
    {
        "project": "personal",
        "partition": {
            "name": "sim",
            "status": "available",
            "max_num_qubits": 8,
            "hardware_type": "simulator",
        },
        "shots_left": 9500,
        "jobs_left": 100,
    }
]


def _make_mock_job(pid="test-pid-123", status_name="SUCCESS", device="sim", project="personal"):
    """Create a mock QiboJob."""
    from tii_quantum.job import convert_str_to_job_status

    job = MagicMock()
    job.pid = pid
    job.device = device
    job.project = project
    job.nshots = 1000
    job._status = convert_str_to_job_status(status_name)
    job.queue_position = None
    job.seconds_to_job_start = None
    job.queue_last_update = None
    return job


def _make_mock_client(job=None):
    """Create a mock tii_quantum.Client."""
    client = MagicMock()
    client.base_url = "https://q-cloud.tii.ae"
    client.headers = {"x-api-token": "fake-token"}
    if job is not None:
        client.run_circuit.return_value = job
        client.get_job.return_value = job
    return client


# ---------------------------------------------------------------------------
# client.py unit tests
# ---------------------------------------------------------------------------


class TestCircuitFromInput:
    def test_qasm_bell(self):
        circuit = circuit_from_input(BELL_QASM)
        assert circuit.nqubits == 2

    def test_qasm_leading_whitespace(self):
        circuit = circuit_from_input("  \n" + BELL_QASM)
        assert circuit.nqubits == 2

    def test_json_bell(self):
        import json

        circuit = circuit_from_input(json.dumps(BELL_JSON_RAW))
        assert circuit.nqubits == 2

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="neither a valid QASM"):
            circuit_from_input("not a circuit")

    def test_json_missing_queue_raises(self):
        import json

        with pytest.raises(ValueError, match="'queue' key"):
            circuit_from_input(json.dumps({"nqubits": 2}))


class TestResultToMarkdown:
    def _make_result(self):
        c = qibo.Circuit(2)
        c.add(gates.H(0))
        c.add(gates.CNOT(0, 1))
        c.add(gates.M(0, 1))
        return c(nshots=100)

    def test_contains_pid(self):
        result = self._make_result()
        md = result_to_markdown(result, pid="abc123")
        assert "abc123" in md

    def test_contains_frequencies(self):
        result = self._make_result()
        md = result_to_markdown(result, pid="abc123")
        assert "Measurement frequencies" in md

    def test_max_samples_respected(self):
        result = self._make_result()
        md = result_to_markdown(result, pid="abc123", max_samples=5)
        # Bitstrings in the sample block should be ≤ 5
        sample_lines = [line for line in md.split("\n") if line and all(c in "01" for c in line)]
        assert len(sample_lines) <= 5

    def test_frequency_outcomes_are_capped(self):
        result = MagicMock()
        result.frequencies.return_value = Counter(
            {format(value, "08b"): 1 for value in range(MAX_FREQUENCY_OUTCOMES + 1)}
        )
        result.samples.return_value = []

        md = result_to_markdown(result, pid="abc123")

        assert "1 lower-frequency outcomes omitted" in md


# ---------------------------------------------------------------------------
# server.py tool tests (with mocked client)
# ---------------------------------------------------------------------------


@patch("tii_quantum_mcp.server.get_client")
class TestSubmitCircuit:
    @pytest.mark.asyncio
    async def test_success_qasm(self, mock_get_client):
        job = _make_mock_job()
        mock_get_client.return_value = _make_mock_client(job)
        result = await submit_circuit(
            BELL_QASM,
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "test-pid-123" in result
        assert "✓" in result

    @pytest.mark.asyncio
    async def test_success_json(self, mock_get_client):
        import json

        job = _make_mock_job()
        mock_get_client.return_value = _make_mock_client(job)
        result = await submit_circuit(
            json.dumps(BELL_JSON_RAW),
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "test-pid-123" in result

    @pytest.mark.asyncio
    async def test_invalid_circuit(self, mock_get_client):
        mock_get_client.return_value = _make_mock_client()
        result = await submit_circuit(
            "garbage input",
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "parse error" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_non_positive_nshots(self, mock_get_client):
        result = await submit_circuit(BELL_QASM, device="sim", nshots=0)

        assert "Invalid nshots" in result
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("TII_QUANTUM_TOKEN not set")
        result = await submit_circuit(
            BELL_QASM,
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "Authentication error" in result

    @pytest.mark.asyncio
    async def test_prompts_for_missing_target_and_shots(self, mock_get_client):
        job = _make_mock_job()
        client = _make_mock_client(job)
        ctx = MagicMock()
        ctx.elicit = AsyncMock(
            side_effect=[
                AcceptedElicitation(data="target-1"),
                AcceptedElicitation(data=500),
            ]
        )
        mock_get_client.return_value = client

        with patch("tii_quantum_mcp.server.ApiRequest") as mock_request:
            mock_request.get.return_value.json.return_value = AVAILABLE_TARGETS
            result = await submit_circuit(BELL_QASM, ctx=ctx)

        assert "test-pid-123" in result
        client.run_circuit.assert_called_once()
        assert client.run_circuit.call_args.kwargs["project"] == "personal"
        assert client.run_circuit.call_args.kwargs["device"] == "sim"
        assert client.run_circuit.call_args.kwargs["nshots"] == 500

    @pytest.mark.asyncio
    async def test_cancellation_does_not_submit(self, mock_get_client):
        client = _make_mock_client()
        ctx = MagicMock()
        ctx.elicit = AsyncMock(return_value=CancelledElicitation())
        mock_get_client.return_value = client

        with patch("tii_quantum_mcp.server.ApiRequest") as mock_request:
            mock_request.get.return_value.json.return_value = AVAILABLE_TARGETS
            result = await submit_circuit(BELL_QASM, ctx=ctx)

        assert result == "Submission cancelled; no job was created."
        client.run_circuit.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_values_without_context_do_not_submit(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client

        with patch("tii_quantum_mcp.server.ApiRequest") as mock_request:
            mock_request.get.return_value.json.return_value = AVAILABLE_TARGETS
            result = await submit_circuit(BELL_QASM)

        assert "Interactive selection is unavailable" in result
        client.run_circuit.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_shots_exceeding_selected_target_quota(self, mock_get_client):
        client = _make_mock_client()
        ctx = MagicMock()
        ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data=10_000))
        mock_get_client.return_value = client

        with patch("tii_quantum_mcp.server.ApiRequest") as mock_request:
            mock_request.get.return_value.json.return_value = AVAILABLE_TARGETS
            result = await submit_circuit(
                BELL_QASM,
                device="sim",
                project="personal",
                ctx=ctx,
            )

        assert "exceeds the 9500 shots remaining" in result
        client.run_circuit.assert_not_called()


@patch("tii_quantum_mcp.server.get_client")
class TestListAvailableTargets:
    def test_lists_only_compatible_available_targets(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        project_quotas = AVAILABLE_TARGETS + [
            {
                "project": "personal",
                "partition": {
                    "name": "busy-device",
                    "status": "busy",
                    "max_num_qubits": 8,
                    "hardware_type": "hardware",
                },
                "shots_left": 9500,
                "jobs_left": 100,
            },
            {
                "project": "personal",
                "partition": {
                    "name": "small-device",
                    "status": "available",
                    "max_num_qubits": 1,
                    "hardware_type": "hardware",
                },
                "shots_left": 9500,
                "jobs_left": 100,
            },
        ]

        with patch("tii_quantum_mcp.server.ApiRequest") as mock_request:
            mock_request.get.return_value.json.return_value = project_quotas
            result = list_available_targets(BELL_QASM)

        assert "sim" in result
        assert "busy-device" not in result
        assert "small-device" not in result


@patch("tii_quantum_mcp.server.get_client")
class TestGetJobStatus:
    def test_success_status(self, mock_get_client):
        job = _make_mock_job(status_name="SUCCESS")
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_status("test-pid-123")
        assert "SUCCESS" in result
        assert "get_job_result" in result

    def test_queueing_status(self, mock_get_client):
        job = _make_mock_job(status_name="QUEUEING")
        job.queue_position = 3
        job.seconds_to_job_start = 120
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_status("test-pid-123")
        assert "QUEUEING" in result
        assert "3" in result

    def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("no token")
        result = get_job_status("pid")
        assert "Authentication error" in result


@patch("tii_quantum_mcp.server.get_client")
class TestGetJobResult:
    def _make_qibo_result(self):
        c = qibo.Circuit(2)
        c.add(gates.H(0))
        c.add(gates.CNOT(0, 1))
        c.add(gates.M(0, 1))
        return c(nshots=100)

    def test_not_ready_returns_message(self, mock_get_client):
        job = _make_mock_job(status_name="RUNNING")
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_result("test-pid-123")
        assert "not yet complete" in result
        assert "RUNNING" in result

    def test_error_status_returns_message(self, mock_get_client):
        job = _make_mock_job(status_name="ERROR")
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_result("test-pid-123")
        assert "ERROR" in result

    def test_success_returns_markdown(self, mock_get_client):
        job = _make_mock_job(status_name="SUCCESS")
        job.result.return_value = self._make_qibo_result()
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_result("test-pid-123")
        assert "frequencies" in result.lower()
        assert "test-pid-123" in result

    @pytest.mark.parametrize("max_samples", [-1, 1001])
    def test_rejects_out_of_range_max_samples(self, mock_get_client, max_samples):
        result = get_job_result("test-pid-123", max_samples=max_samples)

        assert "Invalid max_samples" in result
        mock_get_client.assert_not_called()


@patch("tii_quantum_mcp.server.get_client")
class TestListJobs:
    def test_empty(self, mock_get_client):
        client = _make_mock_client()
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.return_value.json.return_value = []
            mock_get_client.return_value = client
            result = list_jobs()
        assert "No jobs" in result

    def test_with_jobs(self, mock_get_client):
        client = _make_mock_client()
        fake_jobs = [
            {
                "pid": "abc-1",
                "status": "SUCCESS",
                "created_at": "2026-05-09T10:00:00Z",
                "updated_at": "2026-05-09T11:00:00Z",
            }
        ]
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.return_value.json.return_value = fake_jobs
            mock_get_client.return_value = client
            result = list_jobs()
        assert "abc-1" in result
        assert "SUCCESS" in result


@patch("tii_quantum_mcp.server.get_client")
class TestGetQuota:
    def test_returns_quota_info(self, mock_get_client):
        client = _make_mock_client()
        disk = [
            {
                "user": {"email": "user@example.com"},
                "kbs_left": 8000.0,
                "kbs_max": 10000.0,
            }
        ]
        pqs = [
            {
                "project": "personal",
                "partition": {"name": "sim", "status": "available"},
                "shots_left": 9500,
                "jobs_left": 100,
                "seconds_left": 3600,
            }
        ]
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.return_value.json.side_effect = [disk, pqs]
            mock_get_client.return_value = client
            result = get_quota()
        assert "Disk" in result
        assert "2000.00 KB" in result
        assert "user@example.com" not in result


@patch("tii_quantum_mcp.server.get_client")
class TestDeleteJob:
    def test_success(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        result = delete_job("test-pid-123")
        assert "✓" in result
        client.delete_job.assert_called_once_with("test-pid-123")

    def test_error(self, mock_get_client):
        client = _make_mock_client()
        client.delete_job.side_effect = Exception("Not found")
        mock_get_client.return_value = client
        result = delete_job("bad-pid")
        assert "Error" in result
