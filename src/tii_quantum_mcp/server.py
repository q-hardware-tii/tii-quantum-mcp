"""FastMCP server exposing TII Q-Cloud quantum circuit submission tools."""

from __future__ import annotations

import sys

from fastmcp import FastMCP
from qibo_client import constants as _qibo_constants
from qibo_client.utils import QiboApiRequest

from .client import circuit_from_input, get_client, result_to_markdown

mcp = FastMCP("tii-q-cloud")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_or_error():
    """Return (client, None) or (None, error_str)."""
    try:
        return get_client(), None
    except RuntimeError as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def submit_circuit(
    circuit_input: str,
    device: str,
    nshots: int | None = None,
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
        nshots:        Number of measurement shots. Use ``None`` for the server default.
        project:       Project name to associate with the job (default ``"personal"``).
        verbatim:      If ``True``, run the circuit without transpilation.

    Returns:
        A confirmation message containing the job PID, or an error message.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        circuit = circuit_from_input(circuit_input)
    except ValueError as exc:
        return f"Circuit parse error: {exc}"

    try:
        job = client.run_circuit(circuit, device=device, project=project,
                                 nshots=nshots, verbatim=verbatim)
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


@mcp.tool()
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
        lines.append(
            f"\nJob complete. Call `get_job_result(pid='{pid}')` to download results."
        )
    elif status == "ERROR":
        lines.append("\nJob finished with an error. Check the Q-Cloud dashboard for details.")

    return "\n".join(lines)


@mcp.tool()
def get_job_result(pid: str, max_samples: int = 20) -> str:
    """Download and return measurement results for a completed Q-Cloud job.

    This tool does **not** block: if the job is not yet in ``SUCCESS`` status
    it returns the current status instead of waiting.

    Args:
        pid:         Process ID of the job (returned by ``submit_circuit``).
        max_samples: Maximum number of raw bitstring samples to include in the
                     output (default 20).

    Returns:
        Markdown-formatted measurement frequencies and sample bitstrings,
        or a message indicating the job is not yet ready.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        job = client.get_job(pid)
    except Exception as exc:
        return f"Error fetching job `{pid}`: {exc}"

    from qibo_client.qibo_job import QiboJobStatus

    if job._status is None:
        return f"Job `{pid}` status is unknown. Try `get_job_status` first."

    if job._status == QiboJobStatus.ERROR:
        return f"Job `{pid}` finished with an ERROR. Results are not available."

    if job._status != QiboJobStatus.SUCCESS:
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


@mcp.tool()
def list_jobs() -> str:
    """List all Q-Cloud jobs associated with your account.

    Returns:
        A Markdown table of jobs with PID, status, and timestamps.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        jobs = QiboApiRequest.get(
            client.base_url + "/api/jobs/",
            headers=client.headers,
            timeout=_qibo_constants.TIMEOUT,
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


@mcp.tool()
def get_quota() -> str:
    """Return disk usage and project quota information for your Q-Cloud account.

    Returns:
        A Markdown summary of disk and compute quotas.
    """
    client, err = _client_or_error()
    if err:
        return f"Authentication error: {err}"

    try:
        disk = QiboApiRequest.get(
            client.base_url + "/api/disk_quota/",
            headers=client.headers,
            timeout=_qibo_constants.TIMEOUT,
        ).json()

        project_quotas = QiboApiRequest.get(
            client.base_url + "/api/projectquotas/",
            headers=client.headers,
            timeout=_qibo_constants.TIMEOUT,
        ).json()
    except Exception as exc:
        return f"Error fetching quota information: {exc}"

    lines = ["## Q-Cloud quota\n"]

    # Disk quota
    if disk:
        entry = disk[0] if isinstance(disk, list) else disk
        kbs_left = entry.get("kbs_left")
        kbs_max = entry.get("kbs_max")
        user_email = (entry.get("user") or {}).get("email", "")
        if user_email:
            lines.append(f"**User:** {user_email}\n")
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
        lines.append(
            "| Project | Device | Shots left | Jobs left | Time left (s) | Status |"
        )
        lines.append(
            "|---------|--------|------------|-----------|---------------|--------|"
        )
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
