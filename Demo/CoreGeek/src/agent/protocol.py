from dataclasses import dataclass
from typing import Any

DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS

WEAPON_BUILD_COST = 25
WALL_MATERIAL = "stone"
LAND = "land"
STATION = "station"
WALL = "wall"
WORKER = "worker"
PIONEER = "pioneer"
TOWER_TYPES = ("gatling", "railgun", "rocket")
CONTROLLABLE_TYPES = (WORKER, PIONEER)
TOWER_RANGE_BY_LEVEL = {
    "gatling": (3, 5, 7),
    "railgun": (6, 8, 10),
    "rocket": (10, 15, 10**9),
}


@dataclass(frozen=True, slots=True)
class Pos:
    x: int
    y: int

    @classmethod
    def load(cls, raw: Any) -> "Pos":
        return cls(int(raw["x"]), int(raw["y"]))

    def dump(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


def distance(first: Pos, second: Pos) -> int:
    return max(abs(first.x - second.x), abs(first.y - second.y))


def station_footprint(pos: Pos) -> tuple[Pos, ...]:
    return (
        pos,
        Pos(pos.x + 1, pos.y),
        Pos(pos.x, pos.y - 1),
        Pos(pos.x + 1, pos.y - 1),
    )


@dataclass(frozen=True, slots=True)
class Unit:
    unit_id: int
    pos: Pos
    kind: str
    health: int
    level: int
    cooldown: int
    attack_range: int
    capacity: int | None
    backpack: tuple[str, ...]

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Unit":
        raw_capacity = raw.get("backPackCapability")
        return cls(
            int(raw.get("id") or 0),
            Pos.load(raw["pos"]),
            str(raw["roleType"]),
            int(raw["health"]),
            int(raw.get("level") or 0),
            int(raw.get("cooldown") or 0),
            int(raw.get("attackRange") or 0),
            int(raw_capacity) if raw_capacity is not None else None,
            tuple(str(item) for item in raw.get("backpack") or ()),
        )

    @property
    def backpack_full(self) -> bool:
        if self.capacity is None:
            return False
        return len(self.backpack) >= self.capacity

    def range_of_attack(self) -> int:
        if self.attack_range > 0:
            return self.attack_range
        table = TOWER_RANGE_BY_LEVEL.get(self.kind)
        if table is None:
            return 0
        level = min(max(self.level, 1), len(table))
        return table[level - 1]


@dataclass(frozen=True, slots=True)
class Robot:
    robot_id: int
    pos: Pos
    health: int
    kind: str
    abnormal_state: str
    target_team: str

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Robot":
        return cls(
            int(raw.get("id") or 0),
            Pos.load(raw["pos"]),
            int(raw.get("health") or 0),
            str(raw.get("roleType") or ""),
            str(raw.get("abnormalState") or ""),
            str(raw.get("targetTeam") or ""),
        )


@dataclass(frozen=True, slots=True)
class Turn:
    round_no: int
    is_day: bool
    gold: int
    width: int
    height: int
    zones: dict[Pos, str]
    ours: tuple[Unit, ...]
    enemy: tuple[Unit, ...]
    robots: tuple[Robot, ...]
    tasks: tuple[dict[str, Any], ...]
    phase_task: str
    last_action_results: dict[int, bool]
    last_treasure_result: int
    llm_response: str
    official_news: str
    folk_legends: str
    last_cmd_result: str
    vendor_prices: dict[str, int]
    shop_prices: dict[str, int]

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "Turn":
        round_no = int(payload["roundNo"])
        info = payload["mapInfo"]
        team = payload["teamOur"]
        news = payload.get("worldNews") or {}
        return cls(
            round_no,
            (round_no - 1) % ROUNDS_PER_DAY < DAY_ROUNDS,
            int(team.get("goldNum") or 0),
            int(info["width"]),
            int(info["height"]),
            {
                Pos.load(zone["pos"]): str(zone["neutralType"])
                for zone in info.get("zones") or ()
            },
            tuple(Unit.load(role) for role in team.get("roles") or ()),
            tuple(
                Unit.load(role)
                for role in (payload.get("teamEnemy") or {}).get("roles") or ()
            ),
            tuple(
                Robot.load(robot)
                for robot in (payload.get("robot") or {}).get("roles") or ()
            ),
            tuple(team.get("playerTasks") or ()),
            str(payload.get("phaseTask") or ""),
            {
                int(key): bool(value)
                for key, value in (payload.get("lastRoundRoleActionResults") or {}).items()
            },
            int(payload.get("lastSummonTreasureResult") or 0),
            str(payload.get("llmResp") or ""),
            str(news.get("officialNews") or ""),
            str(news.get("folkLegends") or ""),
            str(payload.get("lastCmdResult") or ""),
            _price_map(payload.get("vendorShopList")),
            _price_map(payload.get("weaponShopList")),
        )

    def station(self) -> Unit | None:
        for unit in self.ours:
            if unit.kind == STATION:
                return unit
        return None

    def alive(self, kinds: tuple[str, ...]) -> tuple[Unit, ...]:
        return tuple(
            unit for unit in self.ours
            if unit.kind in kinds and unit.health > 0
        )

    def controllable(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive(CONTROLLABLE_TYPES), key=lambda unit: unit.unit_id,
        ))

    def workers(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive((WORKER,)), key=lambda unit: unit.unit_id,
        ))

    def weapons(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive(TOWER_TYPES),
            key=lambda unit: (unit.pos.x, unit.pos.y),
        ))

    def walls(self) -> tuple[Unit, ...]:
        return self.alive((WALL,))

    def unit(self, unit_id: int) -> Unit | None:
        return next((unit for unit in self.ours if unit.unit_id == unit_id), None)

    def stone_mines(self) -> tuple[Pos, ...]:
        return tuple(
            pos for pos, kind in self.zones.items() if kind == WALL_MATERIAL
        )

    def footprint(self, unit: Unit) -> tuple[Pos, ...]:
        if unit.kind == STATION:
            return station_footprint(unit.pos)
        return (unit.pos,)

    def land(self, pos: Pos) -> bool:
        if not 0 <= pos.x < self.width or not 0 <= pos.y < self.height:
            return False
        return self.zones.get(pos, LAND) == LAND

    def occupied_cells(self) -> frozenset[Pos]:
        cells: set[Pos] = set()
        for unit in self.ours:
            cells.update(self.footprint(unit))
        return frozenset(cells)

    def blocked(self, moving: Unit) -> frozenset[Pos]:
        cells = {pos for pos, kind in self.zones.items() if kind != LAND}
        cells.update(self.occupied_cells())
        cells.discard(moving.pos)
        for robot in self.robots:
            cells.add(robot.pos)
        return frozenset(cells)

    def mines(self, material: str | None = None) -> tuple[Pos, ...]:
        return tuple(
            pos for pos, kind in self.zones.items()
            if kind in ("stone", "iron", "copper")
            and (material is None or kind == material)
        )

    def neutral(self, kind: str) -> tuple[Pos, ...]:
        return tuple(pos for pos, value in self.zones.items() if value == kind)

    def task_points(self) -> tuple[tuple[Pos, dict[str, Any]], ...]:
        points: list[tuple[Pos, dict[str, Any]]] = []
        for task in self.tasks:
            raw_pos = task.get("taskPosition")
            if isinstance(raw_pos, dict):
                points.append((Pos.load(raw_pos), task))
        return tuple(points)


def move_command(pos: Pos) -> dict[str, Any]:
    return {"action": "move", "targetPos": [pos.dump()]}


def collect_command(pos: Pos) -> dict[str, Any]:
    return {"action": "collect", "targetPos": [pos.dump()]}


def build_command(pos: Pos, name: str) -> dict[str, Any]:
    return {"action": "build", "targetPos": [pos.dump()], "name": name}


def remove_command(pos: Pos) -> dict[str, Any]:
    """拆除一段围墙，拆除后该位置下一回合可重新建造。"""
    return {"action": "remove", "targetPos": [pos.dump()]}


def attack_command(controller_id: int, pos: Pos) -> dict[str, Any]:
    return {
        "action": "attack",
        "targetPos": [pos.dump()],
        "controllerId": str(controller_id),
    }


def sell_command(name: str, num: int = 1) -> dict[str, Any]:
    return {"action": "sell", "name": name, "num": max(1, int(num))}


def buy_command(name: str, num: int = 1) -> dict[str, Any]:
    return {"action": "buy", "name": name, "num": max(1, int(num))}


def use_command(name: str, target: Pos | None = None) -> dict[str, Any]:
    command: dict[str, Any] = {"action": "use", "name": name}
    if target is not None:
        command["targetPos"] = [target.dump()]
    return command


def drop_command(name: str) -> dict[str, Any]:
    return {"action": "drop", "name": name}


def accept_task_command() -> dict[str, Any]:
    return {"action": "acceptTask"}


def submit_answer_command(answer: str) -> dict[str, Any]:
    return {"action": "submitAnswer", "taskAnswer": answer}


def summon_treasure_command(target: Pos, items: list[str]) -> dict[str, Any]:
    return {
        "action": "summonTreasure",
        "targetPos": [target.dump()],
        "item": list(items),
    }


def _price_map(items: Any) -> dict[str, int]:
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("name")): int(item.get("price") or 0)
        for item in items
        if isinstance(item, dict) and item.get("name") is not None
    }
