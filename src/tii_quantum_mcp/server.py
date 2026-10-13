"""FastMCP server exposing TII Q-Cloud quantum circuit submission tools."""

from __future__ import annotations

import sys
from typing import Any

from fastmcp import FastMCP
from tii_quantum import constants as _tii_quantum_constants
from tii_quantum.job import JobStatus
from tii_quantum.utils import ApiRequest

from .client import circuit_from_input, get_client, result_to_markdown

mcp = FastMCP("tii-q-cloud")
MAX_RESULT_SAMPLES = 1_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_or_error():
    """Return (client, None) or (None, error_str)."""
    try:
        return get_client(), None
    except RuntimeError as exc:
        return None, str(exc)


def _fetch_project_quotas(client: Any) -> list[dict[str, Any]]:
    """Fetch project/partition quota entries for the authenticated account."""
    project_quotas = ApiRequest.get(
        client.base_url + "/api/projectquotas/",
        headers=client.headers,
        timeout=_tii_quantum_constants.TIMEOUT,
    ).json()
    if not isinstance(project_quotas, list):
        raise ValueError("Q-Cloud returned an invalid project quota response.")
    return project_quotas


def _available_targets(
    project_quotas: list[dict[str, Any]],
    nqubits: int,
    project: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """Return quota-backed targets that can run a circuit with *nqubits*."""
    targets = []
    for quota in project_quotas:
        partition = quota.get("partition")
        if not isinstance(partition, dict):
            continue

        quota_project = quota.get("project")
        quota_device = partition.get("name")
        max_num_qubits = partition.get("max_num_qubits")
        shots_left = quota.get("shots_left")
        jobs_left = quota.get("jobs_left")
        status = partition.get("status")

        if not isinstance(quota_project, str) or not isinstance(quota_device, str):
            continue
        if project is not None and quota_project != project:
            continue
        if device is not None and quota_device != device:
            continue
        if not isinstance(max_num_qubits, int) or max_num_qubits < nqubits:
            continue
        if not isinstance(shots_left, (int, float)) or shots_left <= 0:
            continue
        if not isinstance(jobs_left, (int, float)) or jobs_left <= 0:
            continue
        if not isinstance(status, str) or status.lower() != "available":
            continue

        targets.append(
            {
                "project": quota_project,
                "device": quota_device,
                "max_num_qubits": max_num_qubits,
                "shots_left": shots_left,
                "jobs_left": jobs_left,
                "hardware_type": partition.get("hardware_type", "unknown"),
            }
        )
    return targets


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def submit_circuit(
    circuit_input: str,
    device: str,
    nshots: int = 1024,
    project: str = "personal",
    verbatim: bool = False,
) -> str:
    """Submit a quantum circuit to the TII Q-Cloud and return the job PID.

    Args:
        circuit_input: The quantum circuit in one of two formats:
            - **QASM 2.0** string (starts with ``OPENQASM 2.0;``)
            - **qibo JSON** string — the JSON-serialised ``circuit.raw`` dict
              (contains a ``"queue"`` key)
        device:        Target device / partition name (e.g. ``"sim"``).
        nshots:        Number of measurement shots (default 1024).
        project:       Project name to associate with the job (default ``"personal"``).
        verbatim:      If ``True``, run the circuit without transpilation.

    Returns:
        A confirmation message containing the job PID, or an error message.
    """
    if nshots < 1:
        return "Invalid nshots: provide a positive integer."

    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        circuit = circuit_from_input(circuit_input)
    except ValueError as exc:
        return f"Circuit parse error: {exc}"

    try:
        job = client.run_circuit(
            circuit, device=device, project=project, nshots=nshots, verbatim=verbatim
        )
    except Exception as exc:
        return f"Submission error: {exc}"

    if job is None:
        return "Submission failed: server returned no job object."

    return (
        f"✓ Circuit submitted successfully.\n\n"
        f"- **PID:** `{job.pid}`\n"
        f"- **Device:** {job.device}\n"
        f"- **Project:** {job.project}\n"
        f"- **Shots:** {job.nshots}\n\n"
        f"Use `get_job_status(pid='{job.pid}')` to monitor progress."
    )


@mcp.tool(annotations={"readOnlyHint": True})
def get_job_status(pid: str) -> str:
    """Refresh and return the current status of a Q-Cloud job.

    Args:
        pid: Process ID of the job (returned by ``submit_circuit``).

    Returns:
        A Markdown summary with status, queue position, and estimated start time.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        job = client.get_job(pid)
    except Exception as exc:
        return f"Error fetching job `{pid}`: {exc}"

    status = job._status.name if job._status else "UNKNOWN"
    lines = [
        f"## Job `{pid}`\n",
        f"- **Status:** {status}",
    ]
    if job.device:
        lines.append(f"- **Device:** {job.device}")
    if job.project:
        lines.append(f"- **Project:** {job.project}")
    if job.queue_position is not None:
        lines.append(f"- **Queue position:** {job.queue_position}")
    if job.seconds_to_job_start is not None:
        eta = int(job.seconds_to_job_start)
        lines.append(f"- **Estimated time to start:** {eta}s")
    if job.queue_last_update:
        lines.append(f"- **Queue last updated:** {job.queue_last_update}")

    if status == "SUCCESS":
        lines.append(f"\nJob complete. Call `get_job_result(pid='{pid}')` to download results.")
    elif status == "ERROR":
        lines.append("\nJob finished with an error. Check the Q-Cloud dashboard for details.")

    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True})
def get_job_result(pid: str, max_samples: int = 20) -> str:
    """Download and return measurement results for a completed Q-Cloud job.

    This tool does **not** block: if the job is not yet in ``SUCCESS`` status
    it returns the current status instead of waiting.

    Args:
        pid:         Process ID of the job (returned by ``submit_circuit``).
        max_samples: Maximum number of raw bitstring samples to include in the
                     output, from 0 to 1000 (default 20).

    Returns:
        Markdown-formatted measurement frequencies and sample bitstrings,
        or a message indicating the job is not yet ready.
    """
    if not 0 <= max_samples <= MAX_RESULT_SAMPLES:
        return f"Invalid max_samples: provide an integer from 0 to {MAX_RESULT_SAMPLES}."

    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        job = client.get_job(pid)
    except Exception as exc:
        return f"Error fetching job `{pid}`: {exc}"

    if job._status is None:
        return f"Job `{pid}` status is unknown. Try `get_job_status` first."

    if job._status == JobStatus.ERROR:
        return f"Job `{pid}` finished with an ERROR. Results are not available."

    if job._status != JobStatus.SUCCESS:
        return (
            f"Job `{pid}` is not yet complete (status: **{job._status.name}**). "
            f"Use `get_job_status(pid='{pid}')` to monitor progress."
        )

    try:
        result = job.result(wait=0.5, verbose=False)
    except Exception as exc:
        return f"Error downloading results for job `{pid}`: {exc}"

    if result is None:
        return f"Job `{pid}` completed but result download returned nothing."

    return result_to_markdown(result, pid=pid, max_samples=max_samples)


@mcp.tool(annotations={"readOnlyHint": True})
def list_available_targets(circuit_input: str | None = None) -> str:
    """List available project/partition pairs, optionally compatible with a circuit.

    Args:
        circuit_input: Optional QASM 2.0 or qibo JSON circuit used to filter
            targets by required qubit count.

    Returns:
        A Markdown table of available targets and their remaining quotas.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    nqubits = 0
    if circuit_input is not None:
        try:
            nqubits = circuit_from_input(circuit_input).nqubits
        except ValueError as exc:
            return f"Circuit parse error: {exc}"

    try:
        targets = _available_targets(_fetch_project_quotas(client), nqubits)
    except Exception as exc:
        return f"Error fetching available targets: {exc}"

    if not targets:
        return "No available targets match your account quota and circuit requirements."

    lines = [
        "| Project | Device | Hardware | Max qubits | Shots left | Jobs left |",
        "|---------|--------|----------|------------|------------|-----------|",
    ]
    for target in targets:
        lines.append(
            f"| {target['project']} | {target['device']} | {target['hardware_type']} | "
            f"{target['max_num_qubits']} | {target['shots_left']} | {target['jobs_left']} |"
        )
    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True})
def list_jobs() -> str:
    """List all Q-Cloud jobs associated with your account.

    Returns:
        A Markdown table of jobs with PID, status, and timestamps.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        jobs = ApiRequest.get(
            client.base_url + "/api/jobs/",
            headers=client.headers,
            timeout=_tii_quantum_constants.TIMEOUT,
        ).json()
    except Exception as exc:
        return f"Error fetching jobs: {exc}"

    if not jobs:
        return "No jobs found for your account."

    lines = [
        "| PID | Status | Created | Updated |",
        "|-----|--------|---------|---------|",
    ]
    for job in jobs:
        pid = job.get("pid", "—")
        status = job.get("status", "—")
        created = job.get("created_at", "—")
        updated = job.get("updated_at", "—")
        if created and "T" in str(created):
            created = created.split("T")[0]
        if updated and "T" in str(updated):
            updated = updated.split("T")[0]
        lines.append(f"| `{pid}` | {status} | {created} | {updated} |")

    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True})
def get_quota() -> str:
    """Return disk usage and project quota information for your Q-Cloud account.

    Returns:
        A Markdown summary of disk and compute quotas.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        disk = ApiRequest.get(
            client.base_url + "/api/disk_quota/",
            headers=client.headers,
            timeout=_tii_quantum_constants.TIMEOUT,
        ).json()

        project_quotas = ApiRequest.get(
            client.base_url + "/api/projectquotas/",
            headers=client.headers,
            timeout=_tii_quantum_constants.TIMEOUT,
        ).json()
    except Exception as exc:
        return f"Error fetching quota information: {exc}"

    lines = ["## Q-Cloud quota\n"]

    # Disk quota
    if disk:
        entry = disk[0] if isinstance(disk, list) else disk
        kbs_left = entry.get("kbs_left")
        kbs_max = entry.get("kbs_max")
        if kbs_left is not None and kbs_max is not None:
            kbs_used = kbs_max - kbs_left
            lines.append(
                f"### Disk usage\n"
                f"- Used: **{kbs_used:.2f} KB** / {kbs_max:.2f} KB "
                f"({kbs_left:.2f} KB remaining)\n"
            )

    # Project quotas — `project` is a plain string, `partition` is a dict
    if project_quotas:
        lines.append("### Project quotas\n")
        lines.append("| Project | Device | Shots left | Jobs left | Time left (s) | Status |")
        lines.append("|---------|--------|------------|-----------|---------------|--------|")
        for pq in project_quotas:
            proj = pq.get("project", "—")
            part = pq.get("partition") or {}
            device = part.get("name", "—")
            status = part.get("status", "—")
            shots_left = pq.get("shots_left", "—")
            jobs_left = pq.get("jobs_left", "—")
            seconds_left = pq.get("seconds_left", "—")
            lines.append(
                f"| {proj} | {device} | {shots_left} | {jobs_left} | {seconds_left} | {status} |"
            )

    return "\n".join(lines)


@mcp.tool()
def delete_job(pid: str) -> str:
    """Delete a Q-Cloud job by its PID.

    Args:
        pid: Process ID of the job to delete.

    Returns:
        A confirmation or error message.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        client.delete_job(pid)
    except Exception as exc:
        return f"Error deleting job `{pid}`: {exc}"

    return f"✓ Job `{pid}` deleted successfully."


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def run_server() -> None:
    """Start the MCP stdio server."""
    token = __import__("os").environ.get("TII_QUANTUM_TOKEN")
    if not token:
        print(
            "[tii-q-cloud-mcp] WARNING: TII_QUANTUM_TOKEN is not set. "
            "Tools will return authentication errors.",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")
