from typing import Any

from .grid import next_step
from .protocol import (
    ORE_TYPES,
    PIONEER,
    Pos,
    Turn,
    Unit,
    WALL,
    WALL_MATERIAL,
    WEAPON_BUILD_COST,
    accept_task_command,
    buy_command,
    build_command,
    collect_command,
    distance,
    multi_attack_command,
    move_command,
    sell_command,
    station_footprint,
    use_command,
)

TOWER_LOADOUT = ("gatling", "railgun", "rocket")
STONE_BATCH = 6
SUMMON_ORDERS = (
    "BossRobotSummonOrder",
    "LargeRobotSummonOrder",
    "MiddleRobotSummonOrder",
    "SmallRobotSummonOrder",
)
UPGRADE_VOUCHERS = {
    "gatling": ("WeaponUpgradeVoucher1", "WeaponUpgradeVoucher2"),
    "railgun": ("WeaponUpgradeVoucher1", "WeaponUpgradeVoucher2"),
    "rocket": ("WeaponUpgradeVoucher1", "WeaponUpgradeVoucher2"),
    "station": ("StationUpgradeVoucher1", "StationUpgradeVoucher2"),
    "wall": ("WallUpgradeVoucher1", "WallUpgradeVoucher2"),
}
_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def decide(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    turn = Turn.load(payload)
    commands: dict[int, dict[str, Any]] = {}
    if turn.is_day:
        _day(turn, commands)
    else:
        _night(turn, commands)
    commands = {
        unit_id: command for unit_id, command in commands.items()
        if not (turn.action_failed(unit_id) and command.get("action") != "move")
    }
    return {str(key): value for key, value in commands.items()}


def _day(turn: Turn, commands: dict[int, dict[str, Any]]) -> None:
    sites = _tower_sites(turn)
    order = _wall_order(turn)
    standing_towers = {unit.pos for unit in turn.weapons()}
    standing_walls = {unit.pos for unit in turn.walls()}
    occupied = turn.occupied_cells()
    towers_missing = [pos for pos in sites if pos not in standing_towers]
    walls_missing = [pos for pos in order if pos not in standing_walls]
    free_towers = [pos for pos in towers_missing if pos not in occupied]
    free_walls = [pos for pos in walls_missing if pos not in occupied]

    claimed: set[Pos] = set()
    upgrade_targets: set[Pos] = set()
    planned_gold = [turn.gold]
    for role in turn.workers():
        if _maintain(turn, role, commands, claimed, planned_gold, allow_shop=True):
            continue
        if _upgrade(turn, role, commands, claimed, upgrade_targets, planned_gold):
            continue
        if _buy_defense_item(turn, role, commands, claimed, planned_gold):
            continue
        if _use_summon_order(turn, role, commands):
            continue
        _worker_day(
            turn, role, sites, free_towers, free_walls, claimed, commands,
            planned_gold[0],
        )
        command = commands.get(role.unit_id)
        if command and command.get("action") == "build" and command.get("name") in TOWER_LOADOUT:
            planned_gold[0] -= WEAPON_BUILD_COST
    _pioneer_task(turn, commands, claimed, planned_gold, upgrade_targets)
    for role, tower in _tower_pairs(turn):
        if role.kind != PIONEER:
            continue
        if role.unit_id in commands:
            continue
        if distance(role.pos, tower.pos) <= 1 and role.pos not in walls_missing:
            continue
        step = _step_toward(turn, role, tower.pos, claimed, inside_only=True)
        if step is not None:
            commands[role.unit_id] = move_command(step)


def _worker_day(
    turn: Turn,
    role: Unit,
    sites: tuple[Pos, ...],
    towers_missing: list[Pos],
    walls_missing: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    planned_gold: int,
) -> None:
    if towers_missing and planned_gold >= WEAPON_BUILD_COST:
        for index, site in enumerate(sites):
            if site in towers_missing and site not in claimed:
                _build_or_walk(
                    turn, role, site, TOWER_LOADOUT[index], claimed, commands,
                )
                return
    if not walls_missing:
        _trade_or_mine(turn, role, claimed, commands)
        return

    stones = role.backpack.count(WALL_MATERIAL)
    mine = _adjacent_mine(turn, role)
    if mine is not None and stones < STONE_BATCH:
        commands[role.unit_id] = collect_command(mine)
        claimed.add(mine)
        return
    if stones:
        for site in walls_missing:
            if site not in claimed:
                _build_or_walk(turn, role, site, WALL, claimed, commands)
                return
        return
    _mine(turn, role, claimed, commands, (WALL_MATERIAL,))


def _trade_or_mine(
    turn: Turn,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> None:
    vendor = _adjacent_zone(turn, role, "vendor")
    if vendor is not None:
        ores = [
            (
                turn.vendor_price(ore) if turn.vendor_price(ore) is not None else -1,
                priority,
                ore,
                role.backpack.count(ore),
            )
            for priority, ore in enumerate(("iron", "copper", "stone"))
            if role.backpack.count(ore)
        ]
        if ores:
            _, _, ore, amount = max(ores)
            commands[role.unit_id] = sell_command(ore, amount)
            return
    if any(role.backpack.count(ore) for ore in ORE_TYPES):
        vendor_target = _nearest_zone(turn, role, "vendor")
        if vendor_target is not None:
            step = _step_toward(turn, role, vendor_target, claimed)
            if step is not None:
                commands[role.unit_id] = move_command(step)
                return
    _mine(turn, role, claimed, commands, ORE_TYPES)


def _adjacent_zone(turn: Turn, role: Unit, kind: str) -> Pos | None:
    positions = [
        pos for pos, zone_kind in turn.zones.items()
        if zone_kind == kind and distance(role.pos, pos) <= 1
    ]
    return min(positions, key=lambda pos: (distance(role.pos, pos), pos.x, pos.y), default=None)


def _nearest_zone(turn: Turn, role: Unit, kind: str) -> Pos | None:
    positions = [pos for pos, zone_kind in turn.zones.items() if zone_kind == kind]
    return min(positions, key=lambda pos: (distance(role.pos, pos), pos.x, pos.y), default=None)


def _maintain(
    turn: Turn,
    role: Unit,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    planned_gold: list[int],
    *,
    allow_shop: bool,
) -> bool:
    if role.damaged and "Medicine" in role.backpack:
        commands[role.unit_id] = use_command("Medicine")
        return True
    if role.damaged and allow_shop and not role.backpack_full:
        price = turn.shop_price("Medicine")
        shop = _nearest_zone(turn, role, "weaponShop")
        if price is not None and price <= planned_gold[0] and shop is not None:
            if distance(role.pos, shop) <= 1:
                commands[role.unit_id] = buy_command("Medicine")
                planned_gold[0] -= price
                return True
            step = _step_toward(turn, role, shop, claimed)
            if step is not None:
                commands[role.unit_id] = move_command(step)
                return True
    if "WallFixer" not in role.backpack:
        damaged_walls = [wall for wall in turn.walls() if wall.damaged]
        if not (damaged_walls and allow_shop and role.kind == "worker" and not role.backpack_full):
            return False
        price = turn.shop_price("WallFixer")
        shop = _nearest_zone(turn, role, "weaponShop")
        if price is None or price > planned_gold[0] or shop is None:
            return False
        if distance(role.pos, shop) <= 1:
            commands[role.unit_id] = buy_command("WallFixer")
            planned_gold[0] -= price
            return True
        step = _step_toward(turn, role, shop, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)
            return True
        return False
    damaged_walls = [wall for wall in turn.walls() if wall.damaged]
    if not damaged_walls:
        return False
    target = min(damaged_walls, key=lambda wall: distance(role.pos, wall.pos))
    if distance(role.pos, target.pos) <= 1:
        commands[role.unit_id] = use_command("WallFixer", target.pos)
        return True
    step = _step_toward(turn, role, target.pos, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    return False


def _pioneer_task(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    planned_gold: list[int],
    upgrade_targets: set[Pos],
) -> None:
    pioneers = turn.alive((PIONEER,))
    if not pioneers or turn.phase_task:
        return
    pioneer = pioneers[0]
    if _maintain(turn, pioneer, commands, claimed, planned_gold, allow_shop=True):
        return
    if _upgrade(turn, pioneer, commands, claimed, upgrade_targets, planned_gold):
        return
    tasks = [
        task for task in turn.player_tasks
        if task.get("isValid") and str(task.get("taskType") or "")
    ]
    if not tasks:
        return
    task = min(tasks, key=lambda value: distance(pioneer.pos, Pos.load(value["taskPosition"])))
    target = Pos.load(task["taskPosition"])
    if distance(pioneer.pos, target) <= 1:
        commands[pioneer.unit_id] = accept_task_command()
        return
    step = _step_toward(turn, pioneer, target, claimed)
    if step is not None:
        commands[pioneer.unit_id] = move_command(step)


def _adjacent_mine(turn: Turn, role: Unit) -> Pos | None:
    mines = sorted(
        (
            mine for mine in turn.stone_mines()
            if role.pos != mine and distance(role.pos, mine) <= 1
        ),
        key=lambda pos: (distance(role.pos, pos), pos.x, pos.y),
    )
    return mines[0] if mines else None


def _night(turn: Turn, commands: dict[int, dict[str, Any]]) -> None:
    claimed: set[Pos] = set()
    planned_gold = [turn.gold]
    _use_defense_item(turn, commands)
    for role, tower in _tower_pairs(turn):
        if role.unit_id in commands:
            continue
        if _maintain(turn, role, commands, claimed, planned_gold, allow_shop=False):
            continue
        if distance(role.pos, tower.pos) <= 1:
            if tower.cooldown > 0:
                continue
            targets = _attack_targets(turn, tower)
            if targets:
                commands[tower.unit_id] = multi_attack_command(role.unit_id, targets)
            continue
        step = _step_toward(turn, role, tower.pos, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)


def _use_defense_item(turn: Turn, commands: dict[int, dict[str, Any]]) -> bool:
    station = turn.station()
    if station is None:
        return False
    nearby = [
        robot for robot in turn.robots
        if robot.health > 0
        and min(distance(robot.pos, cell) for cell in turn.footprint(station)) <= 6
    ]
    if len(nearby) < 2:
        return False
    target = max(
        nearby,
        key=lambda robot: (
            sum(distance(robot.pos, other.pos) <= 1 for other in nearby),
            robot.health,
            -robot.robot_id,
        ),
    )
    for item in ("Bomb", "DizzyWeapon"):
        role = next(
            (role for role in turn.controllable() if item in role.backpack
             and not role.damaged and role.unit_id not in commands),
            None,
        )
        if role is not None:
            commands[role.unit_id] = use_command(item, target.pos)
            return True
    return False


def _buy_defense_item(
    turn: Turn,
    role: Unit,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    planned_gold: list[int],
) -> bool:
    if role.backpack_full or any(item in role.backpack for item in ("Bomb", "DizzyWeapon")):
        return False
    item = next(
        (
            item for item in ("Bomb", "DizzyWeapon")
            if turn.shop_price(item) is not None
            and turn.shop_price(item) <= planned_gold[0]
        ),
        None,
    )
    shop = _nearest_zone(turn, role, "weaponShop")
    if item is None or shop is None:
        return False
    if distance(role.pos, shop) <= 1:
        commands[role.unit_id] = buy_command(item)
        planned_gold[0] -= turn.shop_price(item) or 0
        return True
    step = _step_toward(turn, role, shop, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    return False


def _use_summon_order(
    turn: Turn,
    role: Unit,
    commands: dict[int, dict[str, Any]],
) -> bool:
    """Use one summon order during daytime; the server applies it next night."""
    if role.unit_id in commands:
        return False
    # 每个游戏日只在白天前10回合主动使用，最多消耗10张。
    if (turn.round_no - 1) % 130 >= 10:
        return False
    order = next((item for item in SUMMON_ORDERS if item in role.backpack), None)
    if order is None:
        return False
    return _set_use_command(turn, role, commands, order)


def _set_use_command(
    turn: Turn,
    role: Unit,
    commands: dict[int, dict[str, Any]],
    item: str,
) -> bool:
    if turn.action_failed(role.unit_id):
        return False
    commands[role.unit_id] = use_command(item)
    return True


def _upgrade(
    turn: Turn,
    role: Unit,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    upgrade_targets: set[Pos],
    planned_gold: list[int],
) -> bool:
    plan = _upgrade_plan(turn, role, upgrade_targets, planned_gold[0])
    if plan is None:
        return False
    target, voucher = plan
    upgrade_targets.add(target.pos)
    if voucher not in role.backpack:
        if role.backpack_full:
            upgrade_targets.discard(target.pos)
            return False
        price = turn.shop_price(voucher)
        shop = _nearest_zone(turn, role, "weaponShop")
        if price is None or price > planned_gold[0] or shop is None:
            upgrade_targets.discard(target.pos)
            return False
        if distance(role.pos, shop) <= 1:
            commands[role.unit_id] = buy_command(voucher)
            planned_gold[0] -= price
            return True
        step = _step_toward(turn, role, shop, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)
            return True
        upgrade_targets.discard(target.pos)
        return False
    if _building_distance(turn, role, target) <= 1:
        commands[role.unit_id] = use_command(voucher, target.pos)
        return True
    step = _step_toward(turn, role, target.pos, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    upgrade_targets.discard(target.pos)
    return False


def _upgrade_plan(
    turn: Turn,
    role: Unit,
    upgrade_targets: set[Pos],
    available_gold: int,
) -> tuple[Unit, str] | None:
    candidates: list[tuple[int, int, int, int, int, Unit, str]] = []
    station = turn.station()
    buildings = (*turn.weapons(), *((station,) if station else ()), *turn.walls())
    for building in buildings:
        if building.pos in upgrade_targets or building.level >= 3:
            continue
        vouchers = UPGRADE_VOUCHERS.get(building.kind)
        if vouchers is None:
            continue
        voucher = vouchers[building.level - 1] if 1 <= building.level <= 2 else None
        if voucher is None:
            continue
        carried = voucher in role.backpack
        if not carried:
            price = turn.shop_price(voucher)
            if role.backpack_full or price is None or price > available_gold:
                continue
        kind_priority = 0 if building.kind in TOWER_LOADOUT else 1 if building.kind == "station" else 2
        candidates.append((
            0 if carried else 1,
            kind_priority,
            building.level,
            _building_distance(turn, role, building),
            building.unit_id,
            building,
            voucher,
        ))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:5])
    _, _, _, _, _, target, voucher = candidates[0]
    return target, voucher


def _building_distance(turn: Turn, role: Unit, building: Unit) -> int:
    return min(
        distance(role.pos, cell) for cell in turn.footprint(building)
    )


def _tower_pairs(turn: Turn) -> tuple[tuple[Unit, Unit], ...]:
    return tuple(zip(turn.controllable(), turn.weapons()))


def _attack_targets(turn: Turn, tower: Unit) -> tuple[Pos, ...]:
    reach = tower.range_of_attack()
    targets = [
        robot for robot in turn.robots
        if robot.health > 0 and distance(tower.pos, robot.pos) <= reach
    ]
    threatening = [robot for robot in targets if robot.target_team == turn.team_type]
    targets = threatening or targets
    targets.sort(key=lambda robot: (distance(tower.pos, robot.pos), robot.robot_id))
    count = tower.level if tower.kind in ("gatling", "rocket") else 1
    if tower.kind == "gatling":
        selected = _gatling_targets(tower, targets, count)
    else:
        selected = tuple(robot.pos for robot in targets[:count])
    if selected and len(selected) < count:
        selected += (selected[-1],) * (count - len(selected))
    return selected


def _gatling_targets(tower: Unit, robots: list[Any], count: int) -> tuple[Pos, ...]:
    selected: list[Pos] = []
    for robot in robots:
        if all(_within_right_angle(tower.pos, robot.pos, other) for other in selected):
            selected.append(robot.pos)
        if len(selected) == count:
            break
    return tuple(selected)


def _within_right_angle(origin: Pos, first: Pos, second: Pos) -> bool:
    first_x, first_y = first.x - origin.x, first.y - origin.y
    second_x, second_y = second.x - origin.x, second.y - origin.y
    return first_x * second_x + first_y * second_y >= 0


def _build_or_walk(
    turn: Turn,
    role: Unit,
    target: Pos,
    name: str,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> None:
    if role.pos != target and distance(role.pos, target) <= 1:
        commands[role.unit_id] = build_command(target, name)
        claimed.add(target)
        return
    step = _step_toward(turn, role, target, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)


def _mine(
    turn: Turn,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    kinds: tuple[str, ...],
) -> bool:
    if role.backpack_full:
        return False
    mines = sorted(
        (pos for pos, _ in turn.mines(kinds) if pos not in claimed),
        key=lambda pos: (distance(role.pos, pos), pos.x, pos.y),
    )
    for mine in mines:
        if role.pos != mine and distance(role.pos, mine) <= 1:
            commands[role.unit_id] = collect_command(mine)
            claimed.add(mine)
            return True
        step = _step_toward(turn, role, mine, claimed)
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
    for stand in _stand_cells(turn, role, target, claimed, inside_only):
        if stand == role.pos:
            return None
        step = next_step(turn, role, stand)
        if step is None or step in claimed:
            continue
        claimed.add(step)
        return step
    return None


def _stand_cells(
    turn: Turn,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    inside_only: bool = False,
) -> list[Pos]:
    station = turn.station()
    footprint = station_footprint(station.pos) if station else ()
    blocked = turn.blocked(role)
    cells = [
        pos for pos in _neighbours(target)
        if turn.land(pos)
        and pos not in blocked
        and (pos == role.pos or pos not in claimed)
        and (
            not inside_only
            or _footprint_distance(pos, footprint) <= 1
        )
    ]
    cells.sort(key=lambda pos: (_footprint_distance(pos, footprint), pos.x, pos.y))
    return cells


def _tower_sites(turn: Turn) -> tuple[Pos, ...]:
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    cells = [
        pos for pos in _cells_at_distance(station.pos, 1) if turn.land(pos)
    ]
    cells.sort(key=lambda pos: (_footprint_distance(pos, footprint), pos.x, pos.y))
    return tuple(cells[:3])


def _wall_order(turn: Turn) -> tuple[Pos, ...]:
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    xs = [pos.x for pos in footprint]
    ys = [pos.y for pos in footprint]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    order = [
        *(Pos(x, ymin - 2) for x in range(xmax + 2, xmin - 3, -1)),
        *(Pos(xmin - 2, y) for y in range(ymin - 1, ymax + 2)),
        *(Pos(x, ymax + 2) for x in range(xmin - 2, xmax + 3)),
        *(Pos(xmax + 2, y) for y in range(ymax + 1, ymin - 2, -1)),
    ]
    entrance = Pos(xmax + 2, ymin - 1)
    return tuple(
        pos for pos in order if pos != entrance and turn.land(pos)
    )


def _cells_at_distance(station_pos: Pos, radius: int) -> tuple[Pos, ...]:
    footprint = station_footprint(station_pos)
    xs = [pos.x for pos in footprint]
    ys = [pos.y for pos in footprint]
    cells = []
    for x in range(min(xs) - radius, max(xs) + radius + 1):
        for y in range(min(ys) - radius, max(ys) + radius + 1):
            pos = Pos(x, y)
            if pos in footprint:
                continue
            if _footprint_distance(pos, footprint) == radius:
                cells.append(pos)
    return tuple(cells)


def _footprint_distance(pos: Pos, footprint: tuple[Pos, ...]) -> int:
    if not footprint:
        return 0
    return min(distance(pos, cell) for cell in footprint)


def _neighbours(pos: Pos) -> tuple[Pos, ...]:
    return tuple(
        Pos(pos.x + dx, pos.y + dy) for dx, dy in _NEIGHBOUR_STEPS
    )
