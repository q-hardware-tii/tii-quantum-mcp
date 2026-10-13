"""Tests for tii-q-cloud-mcp server tools."""

from __future__ import annotations

import os
from collections import Counter
from unittest.mock import MagicMock, patch

import pytest
import qibo
from qibo import gates

from tii_quantum_mcp.client import MAX_FREQUENCY_OUTCOMES, circuit_from_input, get_client, result_to_markdown
from tii_quantum_mcp.server import (
    delete_job,
    get_job_result,
    get_job_status,
    get_quota,
    list_available_targets,
    list_jobs,
    submit_circuit,
    visualize_circuit,
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


class TestInitFunctions:
    """Test _cmd_serve, _cmd_check_auth, and main() from __init__.py."""

    def test_cmd_serve_calls_run_server(self):
        """Test lines 11-13: _cmd_serve() calls run_server()."""
        # Patch run_server in the server module, because _cmd_serve imports it locally
        with patch("tii_quantum_mcp.server.run_server") as mock_run:
            from tii_quantum_mcp import _cmd_serve
            _cmd_serve(MagicMock())
        mock_run.assert_called_once()

    def test_cmd_check_auth_success(self):
        """Test lines 18-34: _cmd_check_auth() success path."""
        # Patch get_client in the client module, because _cmd_check_auth imports it locally
        with patch("tii_quantum_mcp.client.get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.base_url = "https://q-cloud.tii.ae"
            mock_gc.return_value = mock_client
            from tii_quantum_mcp import _cmd_check_auth
            _cmd_check_auth(MagicMock())
        mock_client.check_client_server_qibo_versions.assert_called_once()

    def test_cmd_check_auth_runtime_error(self):
        """Test lines 22-24: _cmd_check_auth() RuntimeError exception path."""
        # Patch get_client in the client module, because _cmd_check_auth imports it locally
        with patch("tii_quantum_mcp.client.get_client",
                 side_effect=RuntimeError("no token")):
            from tii_quantum_mcp import _cmd_check_auth
            with pytest.raises(SystemExit):
                _cmd_check_auth(MagicMock())

    def test_cmd_check_auth_version_check_runtime_error(self):
        """Test lines 29-31: _cmd_check_auth() RuntimeError in version check."""
        # Patch get_client in the client module, because _cmd_check_auth imports it locally
        with patch("tii_quantum_mcp.client.get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.check_client_server_qibo_versions.side_effect = RuntimeError("version error")
            mock_gc.return_value = mock_client
            from tii_quantum_mcp import _cmd_check_auth
            with pytest.raises(SystemExit):
                _cmd_check_auth(MagicMock())

    def test_cmd_check_auth_general_exception(self):
        """Test lines 32-34: _cmd_check_auth() general Exception path."""
        # Patch get_client in the client module, because _cmd_check_auth imports it locally
        with patch("tii_quantum_mcp.client.get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.check_client_server_qibo_versions.side_effect = Exception("general error")
            mock_gc.return_value = mock_client
            from tii_quantum_mcp import _cmd_check_auth
            with pytest.raises(SystemExit):
                _cmd_check_auth(MagicMock())

    def test_main_serve(self):
        """Test lines 38-54: main() argument parsing and function dispatch."""
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = MagicMock(func=lambda a: "serve")
        with patch("tii_quantum_mcp.__init__.argparse.ArgumentParser",
                   return_value=mock_parser):
            from tii_quantum_mcp import main
            main()
        mock_parser.parse_args.assert_called_once()


class TestGetClient:
    def test_success_token_set(self):
        """Test lines 28-36: get_client() success path when token is set."""
        with patch.dict(os.environ, {"TII_QUANTUM_TOKEN": "fake-token"}):
            with patch("tii_quantum.Client") as mock_client:
                client = get_client()
        # Assert a client was returned
        assert client is not None
        # Assert the client was initialized with the token
        mock_client.assert_called_once_with(token="fake-token")

    def test_failure_token_not_set(self):
        """Test lines 62-63: get_client() failure path when token is not set."""
        # Ensure the token is not set
        with patch.dict(os.environ, {}, clear=True):
            # Remove TII_QUANTUM_TOKEN if it exists
            os.environ.pop("TII_QUANTUM_TOKEN", None)
            with pytest.raises(RuntimeError, match="TII_QUANTUM_TOKEN"):
                get_client()

    def test_failure_token_empty_string(self):
        """Test lines 62-63: get_client() failure path when token is an empty string.

        An empty string is falsy, so `if not token:` should trigger the RuntimeError.
        """
        with patch.dict(os.environ, {"TII_QUANTUM_TOKEN": ""}):
            with pytest.raises(RuntimeError, match="TII_QUANTUM_TOKEN"):
                get_client()


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

    def test_invalid_json_raises_decode_error(self):
        """Test lines 82-83: except json.JSONDecodeError.

        Pass a string that does not start with 'OPENQASM' and is not valid JSON,
        to trigger a JSONDecodeError.
        """
        with pytest.raises(ValueError, match="neither a valid QASM"):
            circuit_from_input("invalid json that is not QASM")

    def test_valid_json_invalid_qibo_raises(self):
        """Test lines 113-114: except Exception in qibo JSON parsing.

        Pass a valid JSON dict with a 'queue' key, but with invalid gate
        parameters that would cause qibo.Circuit.from_dict() to raise an exception.
        """
        import json

        # Create a JSON dict with a 'queue' key, but with an invalid gate
        # that should trigger an exception in from_dict()
        invalid_raw = {
            "queue": [
                {
                    "name": "INVALID_GATE",
                    "init_args": [0],
                    "init_kwargs": {},
                    "_target_qubits": [0],
                    "_control_qubits": [],
                    "_class": "INVALID",
                }
            ],
            "nqubits": 1,
        }
        with pytest.raises(ValueError, match="Failed to parse qibo JSON"):
            circuit_from_input(json.dumps(invalid_raw))


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

    def test_frequencies_exception_is_caught(self):
        """Test lines 124-125: except Exception in frequency extraction.

        Pass a mock result object where frequencies() raises an exception,
        to trigger the except block.
        """
        result = MagicMock()
        result.frequencies.side_effect = Exception("freq error")
        result.samples.return_value = []

        md = result_to_markdown(result, pid="abc123")

        assert "Could not extract frequencies: freq error" in md

    def test_frequencies_exception_is_caught_2(self):
        """Test lines 124-125: except Exception in frequency extraction.

        Pass a mock result object where frequencies() raises a ValueError,
        to trigger the except block.
        """
        result = MagicMock()
        result.frequencies.side_effect = ValueError("value error")
        result.samples.return_value = []

        md = result_to_markdown(result, pid="abc123")

        assert "Could not extract frequencies: value error" in md


# ---------------------------------------------------------------------------
# server.py tool tests (with mocked client)
# ---------------------------------------------------------------------------


@patch("tii_quantum_mcp.server.get_client")
class TestSubmitCircuit:
    def test_success_qasm(self, mock_get_client):
        job = _make_mock_job()
        mock_get_client.return_value = _make_mock_client(job)
        result = submit_circuit(
            BELL_QASM,
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "test-pid-123" in result
        assert "✓" in result

    def test_success_json(self, mock_get_client):
        import json

        job = _make_mock_job()
        mock_get_client.return_value = _make_mock_client(job)
        result = submit_circuit(
            json.dumps(BELL_JSON_RAW),
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "test-pid-123" in result

    def test_invalid_circuit(self, mock_get_client):
        mock_get_client.return_value = _make_mock_client()
        result = submit_circuit(
            "garbage input",
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "parse error" in result.lower()

    def test_rejects_non_positive_nshots(self, mock_get_client):
        result = submit_circuit(BELL_QASM, device="sim", nshots=0)

        assert "Invalid nshots" in result
        mock_get_client.assert_not_called()

    def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("TII_QUANTUM_TOKEN not set")
        result = submit_circuit(
            BELL_QASM,
            device="sim",
            project="personal",
            nshots=1000,
        )
        assert "Authentication error" in result


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

    def test_circuit_parse_error(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.circuit_from_input",
                 side_effect=ValueError("parse error")):
            result = list_available_targets("invalid circuit")
        assert "Circuit parse error: parse error" in result

    def test_fetch_exception(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.side_effect = Exception("API error")
            result = list_available_targets()
        assert "Error fetching available targets" in result
        assert "API error" in result

    def test_empty_targets(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.return_value.json.return_value = []
            result = list_available_targets()
        assert "No available targets" in result

    def test_non_empty_targets(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.return_value.json.return_value = AVAILABLE_TARGETS
            result = list_available_targets()
        assert "sim" in result
        assert "personal" in result

    def test_invalid_quota_response_not_a_list(self, mock_get_client):
        """Test line 55: raise ValueError if project_quotas is not a list."""
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            # Return a non-list to trigger the ValueError at line 55
            mock_req.get.return_value.json.return_value = "not a list"
            result = list_available_targets()
        assert "Error fetching available targets" in result
        assert "invalid project quota response" in result

    def test_all_five_continue_conditions(self, mock_get_client):
        """Test all five 'continue' conditions in _available_targets() (lines 65, 67, 69, 73, 75)."""
        client = _make_mock_client()
        mock_get_client.return_value = client
        # Create quotas that trigger each of the five 'continue' conditions:
        # 1. Line 65: partition is not a dict
        # 2. Line 67: project is not a string
        # 3. Line 69: project is not None and quota_project != project
        # 4. Line 73: max_num_qubits < nqubits
        # 5. Line 75: shots_left <= 0
        quotas = [
            # 1. partition is not a dict -> continue at line 65
            {"project": "p1", "partition": "not-a-dict", "shots_left": 100, "jobs_left": 10},
            # 2. project is not a string -> continue at line 67
            {"project": 123, "partition": {"name": "d1", "max_num_qubits": 10}, "shots_left": 100, "jobs_left": 10},
            # 3. project is not None and quota_project != project -> continue at line 69
            {"project": "different_project", "partition": {"name": "d2", "max_num_qubits": 10}, "shots_left": 100, "jobs_left": 10},
            # 4. max_num_qubits < nqubits -> continue at line 73
            {"project": "personal", "partition": {"name": "d3", "max_num_qubits": 1}, "shots_left": 100, "jobs_left": 10},
            # 5. shots_left <= 0 -> continue at line 75
            {"project": "personal", "partition": {"name": "d4", "max_num_qubits": 10}, "shots_left": 0, "jobs_left": 10},
        ]
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.return_value.json.return_value = quotas
            # Pass nqubits=2 to trigger the max_num_qubits < nqubits condition
            result = list_available_targets(BELL_QASM)
        # All five quotas should be filtered out, so no targets should be returned
        assert "No available targets" in result


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

    def test_get_job_exception(self, mock_get_client):
        client = _make_mock_client()
        client.get_job.side_effect = Exception("fetch error")
        mock_get_client.return_value = client
        result = get_job_status("pid")
        assert "Error fetching job" in result
        assert "fetch error" in result

    def test_queue_position_not_none(self, mock_get_client):
        job = _make_mock_job(status_name="QUEUEING")
        job.queue_position = 5
        job.seconds_to_job_start = 60
        job.queue_last_update = "2026-10-13T20:00:00Z"
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_status("pid")
        assert "5" in result
        assert "60s" in result
        assert "2026-10-13T20:00:00Z" in result


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

    def test_get_job_exception(self, mock_get_client):
        client = _make_mock_client()
        client.get_job.side_effect = Exception("fetch error")
        mock_get_client.return_value = client
        result = get_job_result("test-pid-123")
        assert "Error fetching job" in result
        assert "fetch error" in result

    def test_none_status_returns_message(self, mock_get_client):
        job = _make_mock_job()
        job._status = None
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_result("test-pid-123")
        assert "status is unknown" in result

    def test_success_result_none_returns_message(self, mock_get_client):
        job = _make_mock_job(status_name="SUCCESS")
        job.result.return_value = None
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_result("test-pid-123")
        assert "result download returned nothing" in result


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

    def test_exception(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.side_effect = Exception("API error")
            result = list_jobs()
        assert "Error fetching jobs" in result
        assert "API error" in result


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

    def test_exception(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.side_effect = Exception("API error")
            result = get_quota()
        assert "Error fetching quota information" in result
        assert "API error" in result

    def test_kbs_left_and_max_not_none(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        disk = [{"kbs_left": 8000.0, "kbs_max": 10000.0}]
        with patch("tii_quantum_mcp.server.ApiRequest") as mock_req:
            mock_req.get.return_value.json.side_effect = [disk, []]
            result = get_quota()
        assert "2000.00 KB" in result


@patch("tii_quantum_mcp.server.get_client")
class TestVisualizeCircuit:
    def test_success_qasm(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        # Mock circuit_from_input to return a circuit with a .diagram() method
        with patch("tii_quantum_mcp.server.circuit_from_input") as mock_cfi:
            mock_cfi.return_value = MagicMock(diagram=lambda: "0: ──H──M──", nqubits=2, queue=[1, 2])
            result = visualize_circuit(BELL_QASM)
        assert "Circuit diagram" in result
        assert "0: ──H──M──" in result
        assert "2" in result  # nqubits
        assert "2" in result  # n_gates

    def test_value_error_returns_parse_error(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.circuit_from_input",
                 side_effect=ValueError("invalid")):
            result = visualize_circuit("garbage")
        assert "Circuit parse error: invalid" in result

    def test_diagram_exception_returns_error(self, mock_get_client):
        client = _make_mock_client()
        mock_get_client.return_value = client
        with patch("tii_quantum_mcp.server.circuit_from_input") as mock_cfi:
            mock_cfi.return_value = MagicMock(diagram=MagicMock(side_effect=Exception("draw fail")))
            result = visualize_circuit(BELL_QASM)
        assert "Error drawing circuit: draw fail" in result


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
