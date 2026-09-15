import logging
from dataclasses import dataclass
from typing import Any, Callable

from .economy import (
    stone_count,
    use_medicine_if_needed,
    worker_resource_action,
)
from .grid import can_reach_any
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

LOGGER = logging.getLogger(__name__)

# 开局金币优先落三座火箭炮；后续升级也优先围绕防御塔展开。
TOWER_LOADOUT = ("rocket", "rocket", "rocket")

# 采石不贪多：一次最多准备 10 个石头，够建一批墙就回去施工。
STONE_BATCH_TARGET = 10

# 白天只保留三个顶层状态，日志里也会打印这些值，便于按阶段排查。
BUILD_TOWERS = "build_towers"
BUILD_WALLS = "build_walls"
UPGRADE_BUILDINGS = "upgrade_buildings"

StepToward = Callable[..., Pos | None]

_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


@dataclass(slots=True)
class DayPlan:
    """白天策略快照，集中描述当前阶段和角色分工。"""

    state: str
    missing_towers: list[tuple[Pos, str]]
    missing_walls: list[Pos]
    tower_worker: Unit | None
    wall_worker: Unit | None


def day(turn: Turn, commands: dict[int, dict[str, Any]], step_toward: StepToward) -> str:
    """白天主状态机：建塔 -> 建 C 字墙 -> 经济与升级。"""
    claimed: set[Pos] = set()
    plan = _make_day_plan(turn)
    _log_day_plan(turn, plan)

    for role in turn.workers():
        if use_medicine_if_needed(role, commands):
            continue
        if _worker_action(
            turn, role, plan, claimed, commands, step_toward,
        ):
            continue

    return _pioneer_action(turn, commands, claimed, step_toward)


# ---------------------------------------------------------------------------
# 状态机与角色分工
# ---------------------------------------------------------------------------


def _worker_action(
    turn: Turn,
    role: Unit,
    plan: DayPlan,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> bool:
    # 状态一：防御塔没满时，塔工补三座不相邻火箭炮。
    # 墙工只准备一小批石头，不抢建塔目标，避免第三塔卡住。
    if plan.state == BUILD_TOWERS:
        if role == plan.tower_worker:
            return _tower_worker_action(
                turn, role, plan,
                claimed, commands, step_toward,
            )
        if role == plan.wall_worker:
            return _stone_worker_action(
                turn, role, plan.missing_walls, claimed, commands, step_toward,
            )

    # 状态二：塔已满但 C 字墙没满。墙工循环采石/建墙；
    # 其他工人继续卖矿、买券、升级，保证有人把资源花出去。
    if plan.state == BUILD_WALLS and role == plan.wall_worker:
        return _wall_worker_action(
            turn, role, plan.missing_walls, claimed, commands, step_toward,
        )

    # 状态三：防御塔和围墙都成型后，所有工人都做经济和建筑升级。
    return _economy_worker_action(
        turn, role, plan.missing_towers, plan.missing_walls,
        claimed, commands, step_toward,
    )


def _day_state(
    missing_towers: list[tuple[Pos, str]],
    missing_walls: list[Pos],
) -> str:
    """根据缺失建筑决定白天阶段，保证策略不会在多个目标之间乱跳。"""
    if missing_towers:
        return BUILD_TOWERS
    if missing_walls:
        return BUILD_WALLS
    return UPGRADE_BUILDINGS


def _make_day_plan(turn: Turn) -> DayPlan:
    """生成本回合的白天计划：缺什么建筑、谁负责塔、谁负责墙。"""
    missing_towers = _missing_towers(turn)
    missing_walls = _missing_walls(turn)
    tower_worker, wall_worker = _worker_roles(turn, turn.workers())
    return DayPlan(
        state=_day_state(missing_towers, missing_walls),
        missing_towers=missing_towers,
        missing_walls=missing_walls,
        tower_worker=tower_worker,
        wall_worker=wall_worker,
    )


def _worker_roles(
    turn: Turn,
    workers: tuple[Unit, ...],
) -> tuple[Unit | None, Unit | None]:
    """固定两个工人的职责，减少同时抢一个目标导致的卡位。"""
    if not workers:
        return None, None
    station = turn.station()
    station_pos = station.pos if station else Pos(0, 0)
    wall_worker = min(
        workers,
        key=lambda role: (
            -stone_count(role),
            distance(role.pos, station_pos),
            role.unit_id,
        ),
    )
    tower_worker = min(
        workers,
        key=lambda role: (
            role.unit_id == wall_worker.unit_id,
            distance(role.pos, station_pos),
            role.unit_id,
        ),
    )
    return tower_worker, wall_worker


def _log_day_plan(turn: Turn, plan: DayPlan) -> None:
    """打印白天关键状态，方便从日志判断当前为什么采矿、建墙或升级。"""
    LOGGER.info(
        "day-plan round=%s state=%s tower_worker=%s wall_worker=%s front=%s "
        "wall_stone_need=%s missing_towers=%s missing_walls=%s",
        turn.round_no,
        plan.state,
        plan.tower_worker.unit_id if plan.tower_worker else None,
        plan.wall_worker.unit_id if plan.wall_worker else None,
        "right" if _front_direction(turn) > 0 else "left",
        min(len(plan.missing_walls), STONE_BATCH_TARGET),
        [{"site": site.dump(), "name": name} for site, name in plan.missing_towers],
        [pos.dump() for pos in plan.missing_walls[:8]],
    )


# ---------------------------------------------------------------------------
# 工人和开拓者动作
# ---------------------------------------------------------------------------


def _pioneer_action(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    step_toward: StepToward,
) -> str:
    """开拓者优先处理自动化任务；空闲时帮忙卖矿、买券和升级。"""
    pioneer = next(iter(turn.alive((PIONEER,))), None)
    if pioneer is None or pioneer.unit_id in commands:
        return ""
    if use_medicine_if_needed(pioneer, commands):
        return ""

    prompt = pioneer_day(turn, pioneer, commands, claimed, step_toward)
    if pioneer.unit_id not in commands and not prompt and not _has_available_task(turn):
        _upgrade_or_sell_action(turn, pioneer, claimed, commands, step_toward)
    return prompt


def _tower_worker_action(
    turn: Turn,
    role: Unit,
    plan: DayPlan,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> bool:
    """塔工先补缺失火箭炮；金币不足或暂时不可建时转经济行为。"""
    if plan.missing_towers and turn.gold >= WEAPON_BUILD_COST:
        site, name = plan.missing_towers[0]
        if _build_or_walk(turn, role, site, name, claimed, commands, step_toward):
            plan.missing_towers.pop(0)
            return True
    return _economy_worker_action(
        turn, role, plan.missing_towers, plan.missing_walls,
        claimed, commands, step_toward,
    )


# ---------------------------------------------------------------------------
# 经济、卖矿和升级
# ---------------------------------------------------------------------------


def _stone_worker_action(
    turn: Turn,
    role: Unit,
    missing_walls: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> bool:
    """建塔阶段的墙工只准备少量石头，避免前期两个人都挖矿不施工。"""
    target_stones = min(max(1, len(missing_walls)), STONE_BATCH_TARGET)
    if stone_count(role) < target_stones:
        return worker_resource_action(
            turn, role, claimed, commands, step_toward,
            preferred_material=WALL_MATERIAL,
        )
    return worker_resource_action(
        turn, role, claimed, commands, step_toward,
        keep_stone_stock=False,
    )


def _economy_worker_action(
    turn: Turn,
    role: Unit,
    missing_towers: list[tuple[Pos, str]],
    missing_walls: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> bool:
    """通用经济动作：能补塔先补塔，其次升级/卖矿/买券，最后采矿。"""
    if missing_towers and turn.gold >= WEAPON_BUILD_COST:
        site, name = missing_towers[0]
        if _build_or_walk(turn, role, site, name, claimed, commands, step_toward):
            missing_towers.pop(0)
            return True
    if _upgrade_or_sell_action(turn, role, claimed, commands, step_toward):
        return True
    return worker_resource_action(
        turn, role, claimed, commands, step_toward,
        keep_stone_stock=False,
    )


# ---------------------------------------------------------------------------
# 建造动作
# ---------------------------------------------------------------------------


def _wall_worker_action(
    turn: Turn,
    role: Unit,
    missing_walls: list[Pos],
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> bool:
    """墙工循环执行：有石头就建下一段 C 字墙，石头不足就采一小批。"""
    if missing_walls:
        if stone_count(role) > 0:
            if _build_or_walk(
                turn, role, missing_walls[0], WALL,
                claimed, commands, step_toward,
            ):
                missing_walls.pop(0)
                return True
        target_stones = min(len(missing_walls), STONE_BATCH_TARGET)
        if stone_count(role) < target_stones:
            return worker_resource_action(
                turn, role, claimed, commands, step_toward,
                preferred_material=WALL_MATERIAL,
            )
    return _economy_worker_action(
        turn, role, [], missing_walls, claimed, commands, step_toward,
    )


def _build_or_walk(
    turn: Turn,
    role: Unit,
    target: Pos,
    name: str,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> bool:
    """如果已贴近目标就建造，否则移动到目标周围可达空格。"""
    if role.pos != target and distance(role.pos, target) <= 1:
        commands[role.unit_id] = build_command(target, name)
        claimed.add(target)
        return True
    step = step_toward(turn, role, target, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    return False


# ---------------------------------------------------------------------------
# 经济、卖矿和升级
# ---------------------------------------------------------------------------


def _upgrade_or_sell_action(
    turn: Turn,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> bool:
    """消费背包和金币：先用升级券，再卖矿，最后买下一张升级券。"""
    voucher = _building_voucher_for(role)
    if voucher is not None:
        target = _upgrade_target(turn, role, voucher)
        if target is None:
            return False
        if distance(role.pos, target.pos) <= 1:
            commands[role.unit_id] = use_command(voucher, target.pos)
            return True
        step = step_toward(turn, role, target.pos, claimed)
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
            step = step_toward(turn, role, vendor, claimed)
            if step is not None:
                commands[role.unit_id] = move_command(step)
                return True

    buy_name = _next_building_voucher(turn)
    if buy_name is None or role.backpack_full:
        return False
    if turn.gold < turn.shop_prices.get(buy_name, 10**9):
        return False
    shop = _nearest_zone(turn, role, "weaponShop")
    if shop is None:
        return False
    if distance(role.pos, shop) <= 1:
        commands[role.unit_id] = buy_command(buy_name)
        return True
    step = step_toward(turn, role, shop, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        return True
    return False


def _building_voucher_for(role: Unit) -> str | None:
    """按升级收益顺序查找角色背包里的建筑升级券。"""
    for name in (
        "WeaponUpgradeVoucher1",
        "WeaponUpgradeVoucher2",
        "StationUpgradeVoucher1",
        "StationUpgradeVoucher2",
        "WallUpgradeVoucher1",
        "WallUpgradeVoucher2",
    ):
        if name in role.backpack:
            return name
    return None


def _upgrade_target(turn: Turn, role: Unit, voucher: str) -> Unit | None:
    """给升级券选择最近的合法目标：塔、基地或墙必须正好处于可升等级。"""
    target_level = 1 if voucher.endswith("1") else 2
    if voucher.startswith("Weapon"):
        candidates = turn.weapons()
    elif voucher.startswith("Station"):
        station = turn.station()
        candidates = (station,) if station is not None else ()
    elif voucher.startswith("Wall"):
        candidates = turn.walls()
    else:
        candidates = ()
    return min(
        (unit for unit in candidates if unit.level == target_level),
        key=lambda unit: (
            distance(role.pos, unit.pos),
            unit.level,
            unit.pos.x,
            unit.pos.y,
        ),
        default=None,
    )


def _valuable_ore(role: Unit) -> str | None:
    """石头用于围墙，不主动卖；铜/铁优先变现金币。"""
    for name in ("copper", "iron"):
        if name in role.backpack:
            return name
    return None


def _next_building_voucher(turn: Turn) -> str | None:
    # 升级优先级：火箭炮伤害 > 基地血量 > 围墙耐久。
    if any(tower.level == 1 for tower in turn.weapons()):
        return "WeaponUpgradeVoucher1"
    if any(tower.level == 2 for tower in turn.weapons()):
        return "WeaponUpgradeVoucher2"
    station = turn.station()
    if station is not None and station.level == 1:
        return "StationUpgradeVoucher1"
    if station is not None and station.level == 2:
        return "StationUpgradeVoucher2"
    if any(wall.level == 1 for wall in turn.walls()):
        return "WallUpgradeVoucher1"
    if any(wall.level == 2 for wall in turn.walls()):
        return "WallUpgradeVoucher2"
    return None


def _has_available_task(turn: Turn) -> bool:
    """判断开拓者是否还有可接/进行中的任务，避免经济动作打断任务链。"""
    if turn.phase_task:
        return True
    return any(
        task.get("isValid")
        and int(task.get("coldDownRounds") or 0) == 0
        for _, task in turn.task_points()
    )


def _nearest_zone(turn: Turn, role: Unit, kind: str) -> Pos | None:
    """查找最近的商店或卖矿点。"""
    points = turn.neutral(kind)
    return min(points, key=lambda pos: distance(role.pos, pos), default=None)


# ---------------------------------------------------------------------------
# 布局规划
# ---------------------------------------------------------------------------


def _missing_towers(turn: Turn) -> list[tuple[Pos, str]]:
    """返回还没建成的计划塔位，保持顺序让第三座塔稳定补齐。"""
    tower_positions = {unit.pos for unit in turn.weapons()}
    return [
        (site, TOWER_LOADOUT[index])
        for index, site in enumerate(_tower_sites(turn))
        if site not in tower_positions
    ]


def _missing_walls(turn: Turn) -> list[Pos]:
    """返回 C 字墙里还缺的格子。"""
    wall_positions = {unit.pos for unit in turn.walls()}
    return [pos for pos in _wall_order(turn) if pos not in wall_positions]


def _tower_sites(turn: Turn) -> tuple[Pos, ...]:
    """规划三座不相邻火箭炮，并确保人白天能建、晚上能走过去控塔。"""
    station = turn.station()
    if station is None:
        return ()
    front = _front_direction(turn)
    footprint = turn.footprint(station)
    xs = [pos.x for pos in footprint]
    ys = [pos.y for pos in footprint]
    front_x = (max(xs) + 1) if front > 0 else (min(xs) - 1)
    preferred = (
        Pos(front_x, min(ys) - 1),
        Pos(front_x, max(ys) + 1),
        Pos(front_x + front, min(ys)),
        Pos(front_x + front, max(ys)),
        Pos(front_x + front, min(ys) - 2),
        Pos(front_x + front, max(ys) + 2),
    )
    selected: list[Pos] = []
    fallback = tuple(_cells_at_distance(station.pos, 2))
    existing_towers = {tower.pos for tower in turn.weapons()}
    for pos in (*preferred, *fallback):
        if any(distance(pos, chosen) <= 1 for chosen in selected):
            continue
        if not turn.land(pos):
            continue
        # 已建成的计划内塔位必须保留，否则下一回合计划会漂移。
        if pos in turn.occupied_cells() and pos not in existing_towers:
            continue
        stands = _neighbours(pos)
        if any(can_reach_any(turn, role, stands) for role in turn.workers()) and any(
            can_reach_any(turn, role, stands) for role in turn.controllable()
        ):
            selected.append(pos)
            if len(selected) == len(TOWER_LOADOUT):
                break
    return tuple(selected)


def _wall_order(turn: Turn) -> tuple[Pos, ...]:
    """规划 C 字墙：先进攻正面，再从正面向后补上下两边，不建背面。"""
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
    horizontal_xs = range(front_x, back_x, -front)
    existing_walls = {wall.pos for wall in turn.walls()}
    candidates = [
        *(Pos(front_x, y) for y in range(ymin - 1, ymax + 2)),
        *(Pos(x, ymin - 2) for x in horizontal_xs),
        *(Pos(x, ymax + 2) for x in horizontal_xs),
    ]
    seen: set[Pos] = set()
    ordered = []
    for pos in candidates:
        if pos not in seen:
            ordered.append(pos)
            seen.add(pos)
    return tuple(
        pos for pos in ordered
        if turn.land(pos)
        and (pos not in turn.occupied_cells() or pos in existing_walls)
    )


def _front_direction(turn: Turn) -> int:
    """根据基地左右位置判断主要受敌方向：左侧基地防右，右侧基地防左。"""
    station = turn.station()
    if station is None:
        return 1
    return 1 if station.pos.x < turn.width // 2 else -1


def _cells_at_distance(station_pos: Pos, radius: int) -> tuple[Pos, ...]:
    """塔位候选不足时，从基地外圈补可用格子。"""
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
    """计算点到基地占地的最短距离。"""
    return min((distance(pos, cell) for cell in footprint), default=0)


def _neighbours(pos: Pos) -> tuple[Pos, ...]:
    """八方向邻格，用于找建造站位和控塔站位。"""
    return tuple(Pos(pos.x + dx, pos.y + dy) for dx, dy in _NEIGHBOUR_STEPS)
