# tii-quantum-mcp

An [MCP](https://modelcontextprotocol.io/) server that lets LLM agents submit quantum circuits to the
[TII Q-Cloud](https://q-cloud.tii.ae) system and manage jobs via the
[`tii-quantum`](https://pypi.org/project/tii-quantum/) Python client.

## Tools

| Tool | Description |
|------|-------------|
| `submit_circuit` | Submit a quantum circuit (QASM 2.0 or qibo JSON) to Q-Cloud; returns a job PID |
| `get_job_status` | Refresh and return the current status, queue position, and ETA for a job |
| `get_job_result` | Download and return measurement frequencies + samples for a completed job |
| `list_jobs` | List all jobs associated with your account |
| `get_quota` | Display disk usage and project quota information |
| `delete_job` | Delete a specific job by PID |

## Circuit formats

`submit_circuit` accepts two formats, auto-detected:

- **QASM 2.0** — pass an OpenQASM 2.0 string (starts with `OPENQASM 2.0;`)
- **qibo JSON** — pass a JSON string of the `circuit.raw` dict (contains a `"queue"` key)

## Installation

```bash
pip install tii-quantum-mcp
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv add tii-quantum-mcp
```

## Configuration

Set your TII Q-Cloud API token as an environment variable:

```bash
export TII_QUANTUM_TOKEN=your_token_here
```

## Usage

### Start the MCP server (stdio transport)

```bash
tii-quantum-mcp serve
```

### Verify authentication

```bash
tii-quantum-mcp check-auth
```

### MCP client configuration (e.g. Claude Desktop)

```json
{
  "mcpServers": {
    "tii-q-cloud": {
      "command": "tii-quantum-mcp",
      "args": ["serve"],
      "env": {
        "TII_QUANTUM_TOKEN": "your_token_here"
      }
    }
  }
}
```

## Typical workflow

```
1. submit_circuit(qasm_code="OPENQASM 2.0; ...", device="...", nshots=1000)
   → returns pid="abc123"

2. get_job_status(pid="abc123")
   → returns status=QUEUEING, queue_position=3, eta_seconds=120

3. get_job_status(pid="abc123")
   → returns status=SUCCESS

4. get_job_result(pid="abc123")
   → returns measurement frequencies {"00": 512, "11": 488}
```

## License

Apache 2.0
