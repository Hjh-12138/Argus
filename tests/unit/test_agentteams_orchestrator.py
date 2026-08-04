import unittest
from pathlib import Path

from agentteams.orchestrator import Orchestrator, WorkerDefinition


class StableWorkerClient:
    def get_workers(self, name):
        return [{
            "name": name,
            "phase": "Running",
            "model": "deepseek-v4-flash",
            "runtime": "openclaw",
            "containerState": "running",
            "matrixUserID": "@argus-sec:matrix-local.agentteams.io:18080",
            "roomID": "!room:matrix-local.agentteams.io:18080",
        }]


class RestartingWorkerClient(StableWorkerClient):
    def __init__(self):
        self.states = ["Running", "Starting", "Running"]

    def get_workers(self, name):
        phase = self.states.pop(0) if self.states else "Running"
        return [{
            "name": name,
            "phase": phase,
            "model": "deepseek-v4-flash",
            "runtime": "openclaw",
            "containerState": phase.lower(),
            "matrixUserID": "@argus-sec:matrix-local.agentteams.io:18080",
            "roomID": "!room:matrix-local.agentteams.io:18080",
        }]


class WorkerConvergenceTests(unittest.TestCase):
    def test_idempotent_worker_configuration_converges_without_timestamp_change(self):
        orchestrator = Orchestrator(
            StableWorkerClient(), Path.cwd(), model="deepseek-v4-flash")
        worker = WorkerDefinition(
            "sec", "argus-sec", "Security auditor.",
            ("argus-finding-emit",),
        )

        converged = orchestrator._wait_configured_worker(worker, 1)

        self.assertTrue(converged)

    def test_convergence_returns_the_state_that_satisfied_running(self):
        orchestrator = Orchestrator(
            RestartingWorkerClient(), Path.cwd(), model="deepseek-v4-flash")
        worker = WorkerDefinition(
            "sec", "argus-sec", "Security auditor.",
            ("argus-finding-emit",),
        )

        state = orchestrator._wait_configured_worker(worker, 3)

        self.assertEqual("Running", state["phase"])
        self.assertEqual("running", state["containerState"])


if __name__ == "__main__":
    unittest.main()
