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

    def read_worker_registry_entry(self, name):
        return {
            "runtime": "openclaw",
            "skills": ["argus-finding-emit"],
            "skills_updated_at": "2026-08-03T07:25:24Z",
        }


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


if __name__ == "__main__":
    unittest.main()
