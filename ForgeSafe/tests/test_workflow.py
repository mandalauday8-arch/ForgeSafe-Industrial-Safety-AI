from pathlib import Path
import time
import unittest

from forgesafe.workflow import ForgeSafeWorkflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.workflow = ForgeSafeWorkflow(root)

    def test_cctv_event_gets_guidance_and_action(self):
        decisions = self.workflow.process_cctv([{"class": "NO-Helmet", "confidence": 0.9}])
        self.assertTrue(len(decisions) > 0)
        decision = decisions[0]["decision"]
        self.assertEqual(decision["event"]["kind"], "ppe_violation")
        self.assertEqual(decision["action"], "Notify supervisor and create corrective action")
        self.assertEqual(decision["guidance"][0]["title"], "PPE violation")

    def test_low_risk_machine_is_ignored(self):
        self.assertEqual(self.workflow.process_machine({"name": "CNC Mill", "risk": "LOW"}), [])

    def test_high_risk_machine_creates_incident(self):
        machine_data = {
            "name": "Hydraulic Press",
            "id": "MC_325835",
            "risk": "CRITICAL",
            "failureProbability": 88.5,
            "anomalyDetected": True,
            "anomalyType": "Pressure degradation",
            "demoStatus": "FAULT",
            "sensorReadings": [{"label": "Hydraulic pressure", "value": "88.2bar"}],
        }
        decisions = self.workflow.process_machine(machine_data)
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]["decision"]
        report = decisions[0]["report"]

        self.assertEqual(decision["event"]["severity"], "CRITICAL")
        self.assertEqual(decision["action"], "Stop work and escalate immediately")
        self.assertEqual(decision["owner"], "Site supervisor")
        self.assertIsNotNone(decision["simulated_action"])
        self.assertEqual(decision["simulated_action"]["type"], "simulated_shutdown")
        self.assertEqual(report["status"], "OPEN")
        self.assertTrue(len(decision["guidance"]) > 0)

    def test_same_machine_state_creates_only_one_incident(self):
        machine_data = {
            "name": "CNC Lathe",
            "id": "MC_044379",
            "risk": "CRITICAL",
            "failureProbability": 92.0,
            "anomalyDetected": True,
            "anomalyType": "Bearing / vibration degradation",
            "demoStatus": "FAULT",
        }

        self.assertEqual(len(self.workflow.process_machine(machine_data)), 1)
        self.assertEqual(len(self.workflow.process_machine(machine_data)), 0)
        self.assertEqual(len(self.workflow.get_incidents()), 1)

        self.workflow.clear_machine_incident("MC_044379")
        self.assertEqual(len(self.workflow.process_machine(machine_data)), 1)

        self.workflow.machine_incident_times["MC_044379"] = time.monotonic() - 61
        self.assertEqual(len(self.workflow.process_machine(machine_data)), 1)

    def test_frozen_machine_does_not_create_incidents(self):
        machine_data = {
            "name": "CNC Lathe",
            "id": "MC_044379",
            "risk": "CRITICAL",
            "failureProbability": 92.0,
            "anomalyDetected": True,
            "anomalyType": "Bearing / vibration degradation",
            "demoStatus": "FAULT",
        }

        self.workflow.freeze_machine("MC_044379")
        self.assertEqual(self.workflow.process_machine(machine_data), [])
        self.assertEqual(self.workflow.get_incidents(), [])

    def test_simulated_action_execution_and_reset(self):
        machine_data = {
            "name": "CNC Lathe",
            "id": "MC_044379",
            "risk": "CRITICAL",
            "failureProbability": 92.0,
            "anomalyDetected": True,
            "anomalyType": "Bearing / vibration degradation",
            "demoStatus": "FAULT",
        }
        decisions = self.workflow.process_machine(machine_data)
        report_id = decisions[0]["report"]["report_id"]

        result = self.workflow.execute_simulated_action(
            report_id=report_id,
            action_type="simulated_shutdown",
            target_id="MC_044379",
        )
        self.assertTrue(result["success"])

        override = self.workflow.get_machine_override("MC_044379")
        self.assertIsNotNone(override)
        self.assertEqual(override["state"], "SIMULATED SHUTDOWN")

        # Test incident status update
        incidents = self.workflow.get_incidents()
        updated_report = next(i for i in incidents if i["report_id"] == report_id)
        self.assertEqual(updated_report["status"], "ACTION_EXECUTED")

        # Test machine reset
        reset_result = self.workflow.reset_machine("MC_044379")
        self.assertTrue(reset_result["success"])
        self.assertIsNone(self.workflow.get_machine_override("MC_044379"))

    def test_clear_incidents_preserves_machine_controls(self):
        self.workflow.process_cctv([{"class": "NO-Helmet", "confidence": 0.9}])
        self.workflow.execute_simulated_action(
            report_id="missing-report",
            action_type="simulated_shutdown",
            target_id="MC_044379",
        )

        self.workflow.clear_incidents()

        self.assertEqual(self.workflow.get_incidents(), [])
        self.assertEqual(self.workflow.snapshot(), [])
        self.assertIsNotNone(self.workflow.get_machine_override("MC_044379"))

    def test_reset_all_restores_initial_runtime_state(self):
        self.workflow.process_cctv([{"class": "NO-Helmet", "confidence": 0.9}])
        self.workflow.execute_simulated_action(
            report_id="missing-report",
            action_type="simulated_shutdown",
            target_id="MC_044379",
        )

        self.workflow.reset_all()
        status = self.workflow.status()

        self.assertEqual(self.workflow.get_incidents(), [])
        self.assertEqual(self.workflow.snapshot(), [])
        self.assertEqual(self.workflow.simulated_machine_states, {})
        self.assertEqual(status["open_decisions"], 0)
        self.assertEqual(status["active_incidents"], 0)
        self.assertEqual(status["agent_stats"]["safety_agent"]["processed"], 0)
        self.assertEqual(status["agent_stats"]["action_agent"]["actions"], 0)

    def test_rag_knowledge_search_across_procedures(self):
        # Test vibration search
        vibe_results = self.workflow.knowledge.search("vibration bearing spindle")
        self.assertTrue(len(vibe_results) > 0)
        self.assertTrue(any("ISO 10816" in r.get("standard", "") or "ISO 10816" in r.get("text", "") for r in vibe_results))

        # Test hydraulic search
        hydraulic_results = self.workflow.knowledge.search("hydraulic press pressure loss")
        self.assertTrue(len(hydraulic_results) > 0)
        self.assertTrue(any("ISO 4413" in r.get("standard", "") or "Hydraulic" in r.get("title", "") for r in hydraulic_results))

        # Test furnace thermal search
        furnace_results = self.workflow.knowledge.search("furnace overheating thermal runaway")
        self.assertTrue(len(furnace_results) > 0)
        self.assertTrue(any("NFPA 86" in r.get("standard", "") or "Furnace" in r.get("title", "") for r in furnace_results))

    def test_agent_status_metrics(self):
        status = self.workflow.status()
        self.assertIn("agents", status)
        self.assertEqual(len(status["agents"]), 5)
        self.assertGreaterEqual(status["knowledge_documents"], 7)
        self.assertIn("agent_stats", status)


if __name__ == "__main__":
    unittest.main()
