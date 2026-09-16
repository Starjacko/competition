from dataclasses import dataclass
from typing import Any

DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS

WEAPON_BUILD_COST = 25
WALL_MATERIAL = "stone"
ORE_TYPES = ("stone", "iron", "copper")
LAND = "land"
STATION = "station"
WALL = "wall"
WORKER = "worker"
PIONEER = "pioneer"
TOWER_TYPES = ("gatling", "railgun", "rocket")
CONTROLLABLE_TYPES = (WORKER, PIONEER)
MAX_HEALTH_BY_KIND = {WORKER: (220,), PIONEER: (200,), STATION: (1500, 3000, 4500),
                      WALL: (1000, 1500, 2000), "gatling": (1000, 1500, 2000),
                      "railgun": (1000, 1500, 2000), "rocket": (1000, 1500, 2000)}
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

    @property
    def max_health(self) -> int:
        values = MAX_HEALTH_BY_KIND.get(self.kind)
        if values is None:
            return self.health
        level = min(max(self.level, 1), len(values))
        return values[level - 1]

    @property
    def damaged(self) -> bool:
        return self.health < self.max_health


@dataclass(frozen=True, slots=True)
class Robot:
    robot_id: int
    pos: Pos
    health: int
    abnormal_state: str = ""
    target_team: str = ""

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Robot":
        return cls(
            int(raw["id"]), Pos.load(raw["pos"]), int(raw["health"]),
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
    robots: tuple[Robot, ...]
    team_type: str = ""
    total_score: int = 0
    player_tasks: tuple[dict[str, Any], ...] = ()
    enemy_roles: tuple[Unit, ...] = ()
    phase_task: str = ""
    last_action_results: dict[int, bool] | None = None
    last_summon_treasure_result: int = 0
    llm_resp: str = ""
    world_news: dict[str, Any] | None = None
    last_cmd_result: str = ""
    vendor_shop: tuple[dict[str, Any], ...] = ()
    weapon_shop: tuple[dict[str, Any], ...] = ()
    errors: tuple[dict[str, Any], ...] = ()

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "Turn":
        round_no = int(payload["roundNo"])
        info = payload["mapInfo"]
        team = payload["teamOur"]
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
                Robot.load(robot)
                for robot in (payload.get("robot") or {}).get("roles") or ()
            ),
            str(team.get("type") or ""),
            int(team.get("totalScore") or 0),
            tuple(team.get("playerTasks") or ()),
            tuple(Unit.load(role) for role in (payload.get("teamEnemy") or {}).get("roles") or ()),
            str(payload.get("phaseTask") or ""),
            {
                int(key): bool(value)
                for key, value in (payload.get("lastRoundRoleActionResults") or {}).items()
            },
            int(payload.get("lastSummonTreasureResult") or 0),
            str(payload.get("llmResp") or ""),
            payload.get("worldNews") or {},
            str(payload.get("lastCmdResult") or ""),
            tuple(payload.get("vendorShopList") or ()),
            tuple(payload.get("weaponShopList") or ()),
            tuple(payload.get("errors") or ()),
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

    def mines(self, kinds: tuple[str, ...] = ORE_TYPES) -> tuple[tuple[Pos, str], ...]:
        return tuple(
            (pos, kind) for pos, kind in self.zones.items() if kind in kinds
        )

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
        for unit in (*self.ours, *self.enemy_roles):
            cells.update(self.footprint(unit))
        return frozenset(cells)

    def blocked(self, moving: Unit) -> frozenset[Pos]:
        cells = {pos for pos, kind in self.zones.items() if kind != LAND}
        cells.update(self.occupied_cells())
        cells.discard(moving.pos)
        for robot in self.robots:
            cells.add(robot.pos)
        return frozenset(cells)


def move_command(pos: Pos) -> dict[str, Any]:
    return {"action": "move", "targetPos": [pos.dump()]}


def collect_command(pos: Pos) -> dict[str, Any]:
    return {"action": "collect", "targetPos": [pos.dump()]}


def build_command(pos: Pos, name: str) -> dict[str, Any]:
    return {"action": "build", "targetPos": [pos.dump()], "name": name}


def attack_command(controller_id: int, pos: Pos) -> dict[str, Any]:
    return {
        "action": "attack",
        "targetPos": [pos.dump()],
        "controllerId": str(controller_id),
    }


def multi_attack_command(controller_id: int, positions: tuple[Pos, ...]) -> dict[str, Any]:
    return {
        "action": "attack",
        "targetPos": [pos.dump() for pos in positions],
        "controllerId": str(controller_id),
    }


def sell_command(name: str, num: int = 1) -> dict[str, Any]:
    return {"action": "sell", "name": name, "num": num}


def buy_command(name: str, num: int = 1) -> dict[str, Any]:
    return {"action": "buy", "name": name, "num": num}


def remove_command(pos: Pos) -> dict[str, Any]:
    return {"action": "remove", "targetPos": [pos.dump()]}


def accept_task_command() -> dict[str, Any]:
    return {"action": "acceptTask"}


def submit_answer_command(answer: str) -> dict[str, Any]:
    return {"action": "submitAnswer", "taskAnswer": answer}


def summon_treasure_command(pos: Pos, items: tuple[str, ...]) -> dict[str, Any]:
    return {
        "action": "summonTreasure",
        "targetPos": [pos.dump()],
        "item": list(items),
    }


def use_command(name: str, pos: Pos | None = None) -> dict[str, Any]:
    command: dict[str, Any] = {"action": "use", "name": name}
    if pos is not None:
        command["targetPos"] = [pos.dump()]
    return command


def drop_command(name: str) -> dict[str, Any]:
    return {"action": "drop", "name": name}
