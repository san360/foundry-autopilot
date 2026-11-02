# Copyright (c) Microsoft. All rights reserved.

"""Entry point — starts the generic host with :class:`FinCrimeTriageAgent`.

Equivalent of ``Program.cs`` in the original C# sample.
"""

from __future__ import annotations

import sys

from .agent import FinCrimeTriageAgent
from .host_agent_server import create_and_run_host


def main() -> int:
    try:
        print("Starting Contoso Bank FinCrime Alert Triage autopilot host...")
        create_and_run_host(FinCrimeTriageAgent)
    except Exception as ex:
        print(f"❌ Failed to start server: {ex}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
