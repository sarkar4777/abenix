import json
import sys

# Build N nodes that each sleep ~30s via code_executor, sequential depends_on chain
N = 12  # 12 * 30 = 360s total under 600s cap
nodes = []
for i in range(N):
    n = {
        "id": f"sleep_{i}",
        "tool_name": "code_executor",
        "arguments": {
            "code": "import time\ntime.sleep(28)\nresult = {'step': %d}\nprint(result)" % i,
            "language": "python",
        },
        "depends_on": [f"sleep_{i-1}"] if i > 0 else [],
        "max_retries": 0,
        "on_error": "stop",
    }
    nodes.append(n)
print(json.dumps({"nodes": nodes, "timeout_seconds": 600}))
