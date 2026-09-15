import json
import logging
from typing import Any

from .combat import night
from .economy import (
    has_wall_build_stock,
    stone_count,
    use_medicine_if_needed,
    worker_resource_action,
)
from .grid import can_reach_any, next_step
from .protocol import (
    PIONEER,
    Pos,
    Turn,
    Unit,
    WALL,
    WALL_MATERIAL,
    WEAPON_BUILD_COST,
    build_command,
    buy_command,
    distance,
    move_command,
    sell_command,
    use_command,
)
from .tasks import pioneer_day
from .validator import validated_commands

LOGGER = logging.getLogger(__name__)
TOWER_LOADOUT = ("gatling", "railgun", "rocket")
_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    """编排一回合策略，并返回完整协议响应。"""
    try:
        turn = Turn.load(payload)
        commands: dict[int, dict[str, Any]] = {}
        prompt = ""
        if turn.is_day:
            prompt = _day(turn, commands)
        else:
            night(turn, commands, _step_toward)
        valid_commands = validated_commands(turn, commands)
        _log_turn(turn, commands, valid_commands, prompt)
        return {
            "roleCommandMap": valid_commands,
            "prompt": prompt,
            "executeCmd": "",
        }
    except Exception:
        # 输入不完整时仍返回协议要求的顶层字段，避免服务端崩溃。
        LOGGER.exception("decision fallback")
        return {"roleCommandMap": {}, "prompt": "", "executeCmd": ""}


def _day(turn: Turn, commands: dict[int, dict[str, Any]]) -> str:
    tower_positions = {unit.pos for unit in turn.weapons()}
    missing_towers = [
        (site, TOWER_LOADOUT[index])
        for index, site in enumerate(_tower_sites(turn))
        if site not in tower_positions
    ]
    wall_positions = {unit.pos for unit in turn.walls()}
    missing_walls = [
        pos for pos in _wall_order(turn) if pos not in wall_positions
    ]
    claimed: set[Pos] = set()
    workers = turn.workers()
    builder = _defense_worker(turn, workers)
    LOGGER.info(
        "day-plan round=%s builder=%s missing_towers=%s missing_walls=%s",
        turn.round_no,
        builder.unit_id if builder else None,
        [
            {"site": site.dump(), "name": name}
            for site, name in missing_towers
        ],
        [pos.dump() for pos in missing_walls[:8]],
    )

    for role in workers:
        if use_medicine_if_needed(role, commands):
            continue
        if role == builder:
            if _defense_worker_action(
                turn, role, missing_towers, missing_walls,
                claimed, commands,
            ):
                continue
        elif _economy_worker_action(
            turn, role, builder is None, missing_towers, missing_walls,
            claimed, commands,
        ):
            continue

    pioneer = next(iter(turn.alive((PIONEER,))), None)
    if (
        pioneer is not None
        and pioneer.unit_id not in commands
        and not use_medicine_if_needed(pioneer, commands)
    ):
        return pioneer_day(turn, pioneer, commands, claimed, _step_toward)
    return ""


def _defense_worker(
    turn: Turn,
    workers: tuple[Unit, ...],
) -> Unit | None:
    station = turn.station()
    station_pos = station.pos if station else Pos(0, 0)
    return min(
        workers,
        key=lambda role: (
            -stone_count(role),
            distance(role.pos, station_pos),
            role.unit_id,
        ),
        default=None,
    )


def _defense_worker_action(
    turn: Turn,
    role: Unit,
    missing_towers: list[tuple[Pos, str]],
    missing_walls: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    """防御工优先保证迎敌面围墙，再补三种炮塔。"""
    if missing_walls and has_wall_build_stock(role):
        if _build_or_walk(turn, role, missing_walls[0], WALL, claimed, commands):
            missing_walls.pop(0)
            return True
    if missing_towers and turn.gold >= WEAPON_BUILD_COST:
        site, name = missing_towers[0]
        if _build_or_walk(turn, role, site, name, claimed, commands):
            missing_towers.pop(0)
            return True
    if missing_walls or missing_towers:
        return worker_resource_action(
            turn, role, claimed, commands, _step_toward,
            preferred_material=WALL_MATERIAL,
        )
    return worker_resource_action(
        turn, role, claimed, commands, _step_toward,
        keep_stone_stock=False,
    )


def _economy_worker_action(
    turn: Turn,
    role: Unit,
    should_fallback_build: bool,
    missing_towers: list[tuple[Pos, str]],
    missing_walls: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    """经济工主要采高价矿和卖矿，必要时兜底建设。"""
    if _upgrade_or_sell_action(turn, role, claimed, commands):
        return True
    if should_fallback_build:
        if missing_towers and turn.gold >= WEAPON_BUILD_COST:
            site, name = missing_towers[0]
            if _build_or_walk(turn, role, site, name, claimed, commands):
                missing_towers.pop(0)
                return True
        if missing_walls and has_wall_build_stock(role):
            if _build_or_walk(
                turn, role, missing_walls[0], WALL, claimed, commands,
            ):
                missing_walls.pop(0)
                return True
    return worker_resource_action(
        turn, role, claimed, commands, _step_toward,
        keep_stone_stock=False,
    )


def _upgrade_or_sell_action(
    turn: Turn,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    voucher = _weapon_voucher_for(role)
    if voucher is not None:
        target = _upgrade_target(turn, voucher)
        if target is None:
            return False
        if distance(role.pos, target.pos) <= 1:
            commands[role.unit_id] = use_command(voucher, target.pos)
            return True
        step = _step_toward(turn, role, target.pos, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)
            return True
        return False

    sellable = _valuable_ore(role)
    if sellable is not None:
        vendor = _nearest_zone(turn, role, "vendor")
        if vendor is not None:
            if distance(role.pos, vendor) <= 1:
                commands[role.unit_id] = sell_command(sellable)
                return True
            step = _step_toward(turn, role, vendor, claimed)
            if step is not None:
                commands[role.unit_id] = move_command(step)
                return True

    buy_name = _next_weapon_voucher(turn)
    if buy_name is None or role.backpack_full:
        return False
    price = turn.shop_prices.get(buy_name, 10**9)
    if turn.gold < price:
        return False
    shop = _nearest_zone(turn, role, "weaponShop")
    if shop is None:
        return False
    if distance(role.pos, shop) <= 1:
        commands[role.unit_id] = buy_command(buy_name)
        return True
    step = _step_toward(turn, role, shop, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    return False


def _weapon_voucher_for(role: Unit) -> str | None:
    for name in ("WeaponUpgradeVoucher1", "WeaponUpgradeVoucher2"):
        if name in role.backpack:
            return name
    return None


def _upgrade_target(turn: Turn, voucher: str) -> Unit | None:
    target_level = 1 if voucher.endswith("1") else 2
    return min(
        (tower for tower in turn.weapons() if tower.level == target_level),
        key=lambda tower: (tower.pos.x, tower.pos.y),
        default=None,
    )


def _valuable_ore(role: Unit) -> str | None:
    for name in ("copper", "iron"):
        if name in role.backpack:
            return name
    return None


def _next_weapon_voucher(turn: Turn) -> str | None:
    if any(tower.level == 1 for tower in turn.weapons()):
        return "WeaponUpgradeVoucher1"
    if any(tower.level == 2 for tower in turn.weapons()):
        return "WeaponUpgradeVoucher2"
    return None


def _nearest_zone(turn: Turn, role: Unit, kind: str) -> Pos | None:
    points = turn.neutral(kind)
    return min(points, key=lambda pos: distance(role.pos, pos), default=None)


def _log_turn(
    turn: Turn,
    raw_commands: dict[int, dict[str, Any]],
    valid_commands: dict[str, dict[str, Any]],
    prompt: str,
) -> None:
    dropped = {
        str(role_id): command
        for role_id, command in raw_commands.items()
        if str(role_id) not in valid_commands
    }
    summary = {
        "round": turn.round_no,
        "phase": "day" if turn.is_day else "night",
        "gold": turn.gold,
        "station": _unit_summary(turn.station()),
        "workers": [_unit_summary(unit) for unit in turn.workers()],
        "pioneers": [_unit_summary(unit) for unit in turn.alive((PIONEER,))],
        "weapons": [_unit_summary(unit) for unit in turn.weapons()],
        "robots": [
            {
                "id": robot.robot_id,
                "type": robot.kind,
                "hp": robot.health,
                "pos": robot.pos.dump(),
            }
            for robot in turn.robots
        ],
        "task_active": bool(turn.phase_task),
        "llm_resp": bool(turn.llm_response),
        "prompt_len": len(prompt),
        "raw_commands": {
            str(role_id): command for role_id, command in raw_commands.items()
        },
        "valid_commands": valid_commands,
        "dropped_commands": dropped,
    }
    LOGGER.info(
        "turn-summary %s",
        json.dumps(summary, ensure_ascii=False, sort_keys=True),
    )


def _unit_summary(unit: Unit | None) -> dict[str, Any] | None:
    if unit is None:
        return None
    return {
        "id": unit.unit_id,
        "type": unit.kind,
        "hp": unit.health,
        "level": unit.level,
        "pos": unit.pos.dump(),
        "bag": list(unit.backpack),
    }


def _assign_defensive_moves(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
) -> None:
    station = turn.station()
    if station is None:
        return
    claimed: set[Pos] = set()
    targets = [unit.pos for unit in turn.weapons()] or [station.pos]
    for role in turn.controllable():
        target = min(targets, key=lambda pos: distance(role.pos, pos))
        if distance(role.pos, target) > 1:
            step = _step_toward(turn, role, target, claimed)
            if step is not None:
                commands[role.unit_id] = move_command(step)


def _build_or_walk(
    turn: Turn,
    role: Unit,
    target: Pos,
    name: str,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    if role.pos != target and distance(role.pos, target) <= 1:
        commands[role.unit_id] = build_command(target, name)
        claimed.add(target)
        return True
    step = _step_toward(turn, role, target, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    return False


def _step_toward(
    turn: Turn,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    *,
    inside_only: bool = False,
) -> Pos | None:
    station = turn.station()
    footprint = turn.footprint(station) if station else ()
    candidates = [
        pos for pos in _neighbours(target)
        if turn.land(pos)
        and pos not in turn.blocked(role)
        and pos not in claimed
        and (not inside_only or _footprint_distance(pos, footprint) <= 1)
    ]
    candidates.sort(
        key=lambda pos: (
            _footprint_distance(pos, footprint) if inside_only else 0,
            distance(role.pos, pos),
            pos.x,
            pos.y,
        ),
    )
    for stand in candidates:
        step = next_step(turn, role, stand)
        if step is not None and step not in claimed:
            claimed.add(step)
            return step
    return None


def _tower_sites(turn: Turn) -> tuple[Pos, ...]:
    station = turn.station()
    if station is None:
        return ()
    front = _front_direction(turn)
    footprint = turn.footprint(station)
    xs = [pos.x for pos in footprint]
    ys = [pos.y for pos in footprint]
    front_x = (max(xs) + 1) if front > 0 else (min(xs) - 1)
    preferred = (
        Pos(front_x, min(ys)),
        Pos(front_x, max(ys)),
        Pos(front_x, min(ys) - 1),
        Pos(front_x, max(ys) + 1),
    )
    candidates = []
    fallback = tuple(
        pos for pos in _cells_at_distance(station.pos, 1)
        if pos not in preferred
    )
    for pos in (*preferred, *fallback):
        if not turn.land(pos) or pos in turn.occupied_cells():
            continue
        # 武器建成后角色要站在相邻格控制，提前过滤夜间不可达的位置。
        stands = _neighbours(pos)
        builder_reachable = any(
            can_reach_any(turn, role, stands) for role in turn.workers()
        )
        controller_reachable = any(
            can_reach_any(turn, role, stands)
            for role in turn.controllable()
        )
        if builder_reachable and controller_reachable:
            candidates.append(pos)
    return tuple(candidates[:3])


def _wall_order(turn: Turn) -> tuple[Pos, ...]:
    station = turn.station()
    if station is None:
        return ()
    footprint = turn.footprint(station)
    xs = [pos.x for pos in footprint]
    ys = [pos.y for pos in footprint]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    front = _front_direction(turn)
    front_x = (xmax + 2) if front > 0 else (xmin - 2)
    back_x = (xmin - 2) if front > 0 else (xmax + 2)
    candidates = [
        *(Pos(front_x, y) for y in range(ymin - 1, ymax + 2)),
        *(Pos(x, ymin - 2) for x in range(xmin - 2, xmax + 3)),
        *(Pos(x, ymax + 2) for x in range(xmax + 2, xmin - 3, -1)),
        *(Pos(back_x, y) for y in range(ymax + 1, ymin - 2, -1)),
    ]
    entrance = Pos(back_x, ymin - 1)
    return tuple(
        pos for pos in candidates
        if (
            pos != entrance
            and turn.land(pos)
            and pos not in turn.occupied_cells()
        )
    )


def _front_direction(turn: Turn) -> int:
    station = turn.station()
    if station is None:
        return 1
    return 1 if station.pos.x < turn.width // 2 else -1


def _cells_at_distance(station_pos: Pos, radius: int) -> tuple[Pos, ...]:
    footprint = (
        Pos(station_pos.x, station_pos.y),
        Pos(station_pos.x + 1, station_pos.y),
        Pos(station_pos.x, station_pos.y - 1),
        Pos(station_pos.x + 1, station_pos.y - 1),
    )
    cells = []
    for x in range(station_pos.x - radius, station_pos.x + radius + 2):
        for y in range(station_pos.y - radius - 1, station_pos.y + radius + 1):
            pos = Pos(x, y)
            if pos not in footprint and _footprint_distance(pos, footprint) == radius:
                cells.append(pos)
    return tuple(cells)


def _footprint_distance(pos: Pos, footprint: tuple[Pos, ...]) -> int:
    return min((distance(pos, cell) for cell in footprint), default=0)


def _neighbours(pos: Pos) -> tuple[Pos, ...]:
    return tuple(
        Pos(pos.x + dx, pos.y + dy) for dx, dy in _NEIGHBOUR_STEPS
    )
