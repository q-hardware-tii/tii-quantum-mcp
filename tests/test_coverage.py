"""Additional tests to drive line coverage of tii_quantum_mcp to 100%.

These target the branches not exercised by ``test_server.py``:
the ``__main__`` guard, QASM parse errors, the samples fallback, the
``_available_targets`` project/device/jobs filters, and the auth-error and
error paths of each server tool plus ``run_server``.
"""

from __future__ import annotations

import os
import runpy
from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

from tii_quantum_mcp.client import circuit_from_input, result_to_markdown
from tii_quantum_mcp.server import (
    _available_targets,
    delete_job,
    get_job_result,
    get_job_status,
    get_quota,
    list_available_targets,
    list_jobs,
    run_server,
    submit_circuit,
)

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
# __init__.py: the ``if __name__ == "__main__": main()`` guard
# ---------------------------------------------------------------------------


class TestMainGuard:
    def test_main_guard_invokes_main(self):
        """Cover the ``__main__`` guard by re-executing the module as ``__main__``."""
        with patch("argparse.ArgumentParser") as mock_parser_cls:
            mock_parser = MagicMock()
            mock_parser.parse_args.return_value = MagicMock(func=lambda a: None)
            mock_parser_cls.return_value = mock_parser
            import tii_quantum_mcp

            runpy.run_path(tii_quantum_mcp.__file__, run_name="__main__")
        mock_parser.parse_args.assert_called_once()


# ---------------------------------------------------------------------------
# client.py: QASM parse error and samples fallback
# ---------------------------------------------------------------------------


class TestCircuitFromInputErrors:
    def test_qasm_parse_error(self):
        """Cover the ``except`` around ``qibo.Circuit.from_qasm``."""
        with pytest.raises(ValueError, match="Failed to parse QASM input"):
            circuit_from_input("OPENQASM 2.0; this is not valid qasm")


class TestResultToMarkdownSamples:
    def test_samples_exception_is_swallowed(self):
        """Cover the bare ``except Exception: pass`` around ``result.samples()``."""
        result = MagicMock()
        result.frequencies.return_value = Counter({"00": 1})
        result.samples.side_effect = Exception("samples unavailable")

        md = result_to_markdown(result, pid="abc123")

        # The samples section is skipped when samples() raises.
        assert "First" not in md
        assert "Measurement frequencies" in md


# ---------------------------------------------------------------------------
# server.py: _available_targets project / device / jobs_left filters
# ---------------------------------------------------------------------------


class TestAvailableTargetsFilters:
    def _quota(self, **overrides):
        base = {
            "project": "personal",
            "partition": {
                "name": "sim",
                "status": "available",
                "max_num_qubits": 8,
                "hardware_type": "simulator",
            },
            "shots_left": 100,
            "jobs_left": 10,
        }
        base.update(overrides)
        return base

    def test_project_filter(self):
        """Cover the ``project is not None and quota_project != project`` continue."""
        quotas = [self._quota(project="other")]
        assert _available_targets(quotas, 2, project="personal") == []

    def test_device_filter(self):
        """Cover the ``device is not None and quota_device != device`` continue."""
        partition = {"name": "other-device", "status": "available", "max_num_qubits": 8}
        quotas = [self._quota(partition=partition)]
        assert _available_targets(quotas, 2, device="sim") == []

    def test_jobs_left_zero(self):
        """Cover the ``jobs_left <= 0`` continue."""
        quotas = [self._quota(jobs_left=0)]
        assert _available_targets(quotas, 2) == []

    def test_matching_target_is_returned(self):
        """Sanity check: a fully matching quota is included."""
        quotas = [self._quota()]
        targets = _available_targets(quotas, 2)
        assert len(targets) == 1
        assert targets[0]["device"] == "sim"


# ---------------------------------------------------------------------------
# server.py: submit_circuit error paths
# ---------------------------------------------------------------------------


@patch("tii_quantum_mcp.server.get_client")
class TestSubmitCircuitErrors:
    def test_submission_error(self, mock_get_client):
        """Cover the ``except`` around ``client.run_circuit``."""
        client = _make_mock_client()
        client.run_circuit.side_effect = Exception("submit failed")
        mock_get_client.return_value = client
        result = submit_circuit(BELL_QASM, device="sim")
        assert "Submission error" in result
        assert "submit failed" in result

    def test_submission_returns_none_job(self, mock_get_client):
        """Cover the ``job is None`` branch."""
        client = _make_mock_client()
        client.run_circuit.return_value = None
        mock_get_client.return_value = client
        result = submit_circuit(BELL_QASM, device="sim")
        assert "Submission failed" in result


# ---------------------------------------------------------------------------
# server.py: get_job_status ERROR branch
# ---------------------------------------------------------------------------


@patch("tii_quantum_mcp.server.get_client")
class TestGetJobStatusError:
    def test_error_status(self, mock_get_client):
        """Cover the ``status == "ERROR"`` branch."""
        job = _make_mock_job(status_name="ERROR")
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_status("test-pid-123")
        assert "Job finished with an error" in result


# ---------------------------------------------------------------------------
# server.py: get_job_result auth + download-error paths
# ---------------------------------------------------------------------------


@patch("tii_quantum_mcp.server.get_client")
class TestGetJobResultErrors:
    def test_auth_error(self, mock_get_client):
        """Cover the auth-error branch of get_job_result."""
        mock_get_client.side_effect = RuntimeError("no token")
        result = get_job_result("pid")
        assert "Authentication error" in result

    def test_result_download_error(self, mock_get_client):
        """Cover the ``except`` around ``job.result``."""
        job = _make_mock_job(status_name="SUCCESS")
        job.result.side_effect = Exception("download failed")
        mock_get_client.return_value = _make_mock_client(job)
        result = get_job_result("test-pid-123")
        assert "Error downloading results" in result
        assert "download failed" in result


# ---------------------------------------------------------------------------
# server.py: auth-error branches of the remaining read-only tools
# ---------------------------------------------------------------------------


@patch("tii_quantum_mcp.server.get_client")
class TestListAvailableTargetsAuth:
    def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("no token")
        result = list_available_targets()
        assert "Authentication error" in result


@patch("tii_quantum_mcp.server.get_client")
class TestListJobsAuth:
    def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("no token")
        result = list_jobs()
        assert "Authentication error" in result


@patch("tii_quantum_mcp.server.get_client")
class TestGetQuotaAuth:
    def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("no token")
        result = get_quota()
        assert "Authentication error" in result


@patch("tii_quantum_mcp.server.get_client")
class TestDeleteJobAuth:
    def test_auth_error(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("no token")
        result = delete_job("pid")
        assert "Authentication error" in result


# ---------------------------------------------------------------------------
# server.py: run_server entry point
# ---------------------------------------------------------------------------


class TestRunServer:
    def test_run_server_without_token(self):
        """Cover the warning branch and the ``mcp.run`` call."""
        with patch("tii_quantum_mcp.server.mcp") as mock_mcp:
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("TII_QUANTUM_TOKEN", None)
                run_server()
        mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_run_server_with_token(self):
        """Cover the no-warning branch and the ``mcp.run`` call."""
        with patch("tii_quantum_mcp.server.mcp") as mock_mcp:
            with patch.dict(os.environ, {"TII_QUANTUM_TOKEN": "fake-token"}):
                run_server()
        mock_mcp.run.assert_called_once_with(transport="stdio")
