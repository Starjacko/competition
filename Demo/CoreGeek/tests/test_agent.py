import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent.brain import decide  # noqa: E402
from agent.protocol import (  # noqa: E402
    Pos,
    accept_task_command,
    buy_command,
    drop_command,
    remove_command,
    submit_answer_command,
    summon_treasure_command,
    use_command,
)


class AgentTest(unittest.TestCase):
    def test_sample_request_produces_commands(self) -> None:
        payload = json.loads((Path(__file__).parents[3] / "docs" / "request.txt").read_text(encoding="utf-8"))
        response = {"roleCommandMap": decide(payload)}
        self.assertIsInstance(response["roleCommandMap"], dict)
        for command in response["roleCommandMap"].values():
            self.assertIn(command["action"], {
                "move", "attack", "sell", "buy", "build", "remove",
                "acceptTask", "submitAnswer", "summonTreasure", "use",
                "drop", "collect",
            })

    def test_all_command_builders_use_interface_names(self) -> None:
        self.assertEqual(buy_command("Medicine", 2), {
            "action": "buy", "name": "Medicine", "num": 2,
        })
        self.assertEqual(remove_command(Pos(1, 2))["targetPos"], [{"x": 1, "y": 2}])
        self.assertEqual(accept_task_command(), {"action": "acceptTask"})
        self.assertEqual(submit_answer_command("ok")["taskAnswer"], "ok")
        self.assertEqual(summon_treasure_command(Pos(1, 2), ("StarSand",))["item"], ["StarSand"])
        self.assertEqual(use_command("Medicine"), {"action": "use", "name": "Medicine"})
        self.assertEqual(drop_command("stone"), {"action": "drop", "name": "stone"})


if __name__ == "__main__":
    unittest.main()
