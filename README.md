# tii-quantum-mcp

An [MCP](https://modelcontextprotocol.io/) server that lets LLM agents submit quantum circuits to the
[TII Q-Cloud](https://q-cloud.tii.ae) system and manage jobs via the
[`tii-quantum`](https://pypi.org/project/tii-quantum/) Python client.

## Example prompt

Once the server is connected to an MCP client, you can ask the agent to prepare and
submit a circuit in plain language. For example:

> Prepare a 2-qubit Bell state circuit and submit it to the Q-Cloud simulator.
> Check which targets are available first, then submit with 1000 shots.
> When the job finishes, show me the measurement results.

The agent will:

1. Build the Bell state circuit (e.g. as QASM 2.0)
2. Call `list_available_targets` to find a compatible project/partition
3. Call `submit_circuit` and report the returned PID
4. Poll `get_job_status` until the job reaches `SUCCESS`
5. Call `get_job_result` and show the measurement frequencies


## Tools

| Tool | Description |
|------|-------------|
| `submit_circuit` | Submit a quantum circuit (QASM 2.0 or qibo JSON) to Q-Cloud; returns a job PID |
| `visualize_circuit` | Render a text-based diagram of the circuit, including qubit and gate metadata, before submission |
| `list_available_targets` | List quota-backed project/partition pairs available to run a circuit |
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
pip install .
```

For development with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```

To run the published package without cloning the repository, use:

```bash
uvx tii-quantum-mcp serve
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

### MCP client configuration

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
1. list_available_targets(circuit_input="OPENQASM 2.0; ...")
   → shows the project/partition pairs that can run the circuit

2. submit_circuit(circuit_input="OPENQASM 2.0; ...", device="...", project="...", nshots=1000)
   → returns a confirmation containing PID "abc123"

3. get_job_status(pid="abc123")
   → returns status=QUEUEING, queue_position=3, eta_seconds=120

4. get_job_status(pid="abc123")
   → returns status=SUCCESS

5. get_job_result(pid="abc123")
   → returns measurement frequencies {"00": 512, "11": 488}
```

## License

Apache 2.0
