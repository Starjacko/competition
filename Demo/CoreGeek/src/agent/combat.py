from typing import Any, Callable

from .grid import can_reach_any
from .protocol import (
    Pos,
    Turn,
    Unit,
    TOWER_TYPES,
    distance,
    move_command,
    use_command,
)

StepToward = Callable[..., Pos | None]


def night(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
) -> None:
    """夜间分配角色控制武器，并按威胁优先级攻击机器人。"""
    claimed: set[Pos] = set()
    assigned: set[int] = set()
    roles = list(turn.controllable())
    for tower in turn.weapons():
        controller = best_controller(turn, tower, roles, assigned)
        if controller is None:
            continue
        assigned.add(controller.unit_id)
        if use_medicine_if_needed(controller, commands):
            continue
        if distance(controller.pos, tower.pos) <= 1:
            if tower.cooldown > 0:
                continue
            targets = attack_targets(turn, tower)
            if targets:
                commands[controller.unit_id] = attack_command(tower, targets)
        else:
            step = step_toward(
                turn, controller, tower.pos, claimed, inside_only=True,
            )
            if step is not None:
                commands[controller.unit_id] = move_command(step)


def best_controller(
    turn: Turn,
    tower: Unit,
    roles: list[Unit],
    assigned: set[int],
) -> Unit | None:
    available = [role for role in roles if role.unit_id not in assigned]
    reachable = [
        role for role in available
        if can_reach_any(turn, role, _tower_stands(tower))
    ]
    if not reachable:
        return None
    return min(
        reachable,
        key=lambda role: (
            0 if distance(role.pos, tower.pos) <= 1 else 1,
            distance(role.pos, tower.pos),
            role.unit_id,
        ),
    )


def _tower_stands(tower: Unit) -> tuple[Pos, ...]:
    return tuple(
        Pos(tower.pos.x + dx, tower.pos.y + dy)
        for dx, dy in (
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1), (0, 1),
            (1, -1), (1, 0), (1, 1),
        )
    )


def attack_targets(turn: Turn, tower: Unit) -> list[Pos]:
    robots = [
        robot for robot in turn.robots
        if robot.health > 0
        and distance(tower.pos, robot.pos) <= tower.range_of_attack()
    ]
    if not robots:
        return []
    station = turn.station()
    station_pos = station.pos if station else tower.pos
    type_weight = {
        "bossRobot": 1000,
        "largeRobot": 500,
        "middleRobot": 200,
        "smallRobot": 100,
    }
    robots.sort(
        key=lambda robot: (
            -(
                type_weight.get(robot.kind, 50)
                + max(0, 20 - distance(station_pos, robot.pos))
                + max(0, 100 - robot.health)
            ),
            robot.robot_id,
        ),
    )
    count = tower.level if tower.kind in ("gatling", "rocket") else 1
    return [robot.pos for robot in robots[:max(1, count)]]


def attack_command(tower: Unit, targets: list[Pos]) -> dict[str, Any]:
    return {
        "action": "attack",
        "controllerId": str(tower.unit_id),
        "targetPos": [target.dump() for target in targets],
    }


def use_medicine_if_needed(
    role: Unit,
    commands: dict[int, dict[str, Any]],
) -> bool:
    if role.health <= 50 and "medicine" in role.backpack:
        commands[role.unit_id] = use_command("medicine")
        return True
    return False


def base_under_pressure(turn: Turn) -> bool:
    station = turn.station()
    if station is None:
        return True
    return any(
        robot.health > 0 and distance(station.pos, robot.pos) <= 5
        for robot in turn.robots
    )
