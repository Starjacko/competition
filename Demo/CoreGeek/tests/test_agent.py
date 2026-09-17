import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent.brain import decide  # noqa: E402
from agent.protocol import (  # noqa: E402
    Pos,
    Turn,
    accept_task_command,
    buy_command,
    drop_command,
    remove_command,
    submit_answer_command,
    summon_treasure_command,
    use_command,
)


class AgentTest(unittest.TestCase):
    def sample(self) -> dict:
        payload = json.loads((Path(__file__).parents[3] / "docs" / "request.txt").read_text(encoding="utf-8"))
        payload.pop("lastRoundRoleActionResults", None)
        return payload

    def test_sample_request_produces_commands(self) -> None:
        payload = self.sample()
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

    def test_enemy_unit_blocks_movement(self) -> None:
        payload = self.sample()
        payload["teamEnemy"]["roles"].append({
            "id": 20010, "pos": {"x": 6, "y": 23}, "roleType": "worker",
            "health": 220, "attackPower": 0, "attackRange": 0,
            "backPackCapability": 100, "backpack": [],
        })
        self.assertIn(Pos(6, 23), Turn.load(payload).blocked(Turn.load(payload).workers()[0]))

    def test_medicine_is_used_before_other_worker_action(self) -> None:
        payload = self.sample()
        worker = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "worker")
        worker["health"] = 100
        worker["backpack"] = ["Medicine"]
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {"action": "use", "name": "Medicine"})

    def test_injured_worker_buys_medicine_when_next_to_shop(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 1
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 24, "y": 20}
        worker["health"] = 100
        worker["backpack"] = []
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "buy", "name": "Medicine", "num": 1,
        })

    def test_failed_non_move_action_is_not_immediately_repeated(self) -> None:
        payload = self.sample()
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["health"] = 100
        worker["backpack"] = ["Medicine"]
        payload["lastRoundRoleActionResults"] = {str(worker["id"]): False}
        self.assertNotIn(str(worker["id"]), decide(payload))

    def test_worker_with_ore_walks_to_vendor_before_mining_more(self) -> None:
        payload = self.sample()
        payload["teamOur"]["roles"] = [
            role for role in payload["teamOur"]["roles"] if role["roleType"] != "station"
        ]
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10012)
        worker["backpack"] = ["iron"]
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])]["action"], "move")

    def test_wall_fixer_is_used_when_adjacent_to_damaged_wall(self) -> None:
        payload = self.sample()
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 5, "y": 19}
        worker["backpack"] = ["WallFixer"]
        wall = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "wall")
        wall["health"] = 500
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "use", "name": "WallFixer", "targetPos": [wall["pos"]],
        })

    def test_worker_buys_wall_fixer_when_next_to_shop(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 1
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 24, "y": 20}
        worker["backpack"] = []
        wall = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "wall")
        wall["health"] = 500
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "buy", "name": "WallFixer", "num": 1,
        })

    def test_worker_buys_weapon_upgrade_voucher_when_gold_is_available(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 1
        payload["teamOur"]["goldNum"] = 100
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 24, "y": 20}
        worker["backpack"] = []
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "buy", "name": "WeaponUpgradeVoucher1", "num": 1,
        })

    def test_worker_uses_upgrade_voucher_next_to_weapon(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 1
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 8, "y": 24}
        worker["backpack"] = ["WeaponUpgradeVoucher1"]
        gatling = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "gatling")
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "use", "name": "WeaponUpgradeVoucher1",
            "targetPos": [gatling["pos"]],
        })

    def test_level_two_weapon_uses_second_upgrade_voucher(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 1
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 8, "y": 24}
        worker["backpack"] = ["WeaponUpgradeVoucher2"]
        gatling = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "gatling")
        gatling["level"] = 2
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "use", "name": "WeaponUpgradeVoucher2",
            "targetPos": [gatling["pos"]],
        })

    def test_bomb_is_used_only_when_robots_are_dense_near_station(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 71
        payload["robot"]["roles"] = [
            {"id": 1, "pos": {"x": 11, "y": 24}, "health": 40},
            {"id": 2, "pos": {"x": 11, "y": 25}, "health": 60},
        ]
        worker = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "worker")
        worker["backpack"] = ["Bomb"]
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "use", "name": "Bomb", "targetPos": [{"x": 11, "y": 25}],
        })

    def test_bomb_is_not_used_for_a_single_distant_robot(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 71
        payload["robot"]["roles"] = [
            {"id": 1, "pos": {"x": 30, "y": 10}, "health": 40},
        ]
        worker = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "worker")
        worker["backpack"] = ["Bomb"]
        response = decide(payload)
        self.assertNotEqual(response.get(str(worker["id"]), {}).get("action"), "use")

    def test_station_upgrade_is_selected_before_wall_upgrade(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 1
        payload["teamOur"]["goldNum"] = 100
        payload["teamOur"]["roles"] = [
            role for role in payload["teamOur"]["roles"]
            if role["roleType"] not in {"gatling", "railgun", "rocket"}
        ]
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 24, "y": 20}
        worker["backpack"] = []
        response = decide(payload)
        self.assertEqual(response[str(worker["id"])], {
            "action": "buy", "name": "StationUpgradeVoucher1", "num": 1,
        })

    def test_gatling_targets_stay_within_right_angle(self) -> None:
        payload = self.sample()
        payload["roundNo"] = 71
        payload["robot"]["roles"] = [
            {"id": 1, "pos": {"x": 11, "y": 24}, "health": 40, "targetTeam": "challenger"},
            {"id": 2, "pos": {"x": 10, "y": 25}, "health": 40, "targetTeam": "challenger"},
            {"id": 3, "pos": {"x": 7, "y": 24}, "health": 40, "targetTeam": "challenger"},
        ]
        gatling = next(role for role in payload["teamOur"]["roles"] if role["roleType"] == "gatling")
        gatling["level"] = 3
        worker = next(role for role in payload["teamOur"]["roles"] if role["id"] == 10010)
        worker["pos"] = {"x": 8, "y": 24}
        response = decide(payload)
        targets = response[str(gatling["id"])]["targetPos"]
        self.assertLessEqual(len(targets), 3)
        self.assertNotIn({"x": 7, "y": 24}, targets)


if __name__ == "__main__":
    unittest.main()
