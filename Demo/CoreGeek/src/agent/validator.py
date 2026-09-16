from typing import Any

from .protocol import PIONEER, TOWER_TYPES, Pos, Turn, distance


def validated_commands(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for actor_id, command in commands.items():
        actor = turn.unit(actor_id)
        if actor is not None and actor.health > 0 and command_valid(
            turn, actor, command,
        ):
            result[str(actor_id)] = command
    return result


def command_valid(
    turn: Turn,
    actor: Any,
    command: dict[str, Any],
) -> bool:
    action = command.get("action")
    if action not in {
        "move", "collect", "build", "remove", "attack", "sell",
        "buy", "acceptTask", "submitAnswer", "use",
    }:
        return False
    if action == "attack":
        return _attack_valid(turn, actor, command)
    role = actor
    if action in {"build", "remove"} and role.kind != "worker":
        return False
    if action == "build" and not turn.is_day:
        return False
    if action in {"collect", "build", "remove"} and role.kind != "worker":
        return False
    if action in {"acceptTask", "submitAnswer"} and role.kind != PIONEER:
        return False
    if action == "buy":
        return isinstance(command.get("name"), str)
    if action in {"move", "collect", "build", "attack"}:
        positions = command.get("targetPos")
        if not isinstance(positions, list) or not positions:
            return False
        if any(not isinstance(pos, dict) for pos in positions):
            return False
    if action == "move":
        target = _load_target(command)
        return (
            target is not None
            and distance(role.pos, target) <= 1
            and turn.land(target)
            and target not in turn.blocked(role)
        )
    if action == "collect":
        target = _load_target(command)
        return (
            target is not None
            and target in turn.mines()
            and distance(role.pos, target) <= 1
        )
    if action == "build":
        target = _load_target(command)
        return (
            target is not None
            and distance(role.pos, target) <= 1
            and turn.land(target)
            and target not in turn.occupied_cells()
        )
    if action == "remove":
        target = _load_target(command)
        return (
            target is not None
            and distance(role.pos, target) <= 1
            and any(wall.pos == target for wall in turn.walls())
        )
    if action == "use":
        name = command.get("name")
        return isinstance(name, str) and name in role.backpack
    return True


def _attack_valid(turn: Turn, weapon: Any, command: dict[str, Any]) -> bool:
    if turn.is_day or weapon.kind not in TOWER_TYPES:
        return False
    positions = command.get("targetPos")
    if not isinstance(positions, list) or not positions:
        return False
    if any(not isinstance(pos, dict) for pos in positions):
        return False
    try:
        controller_id = int(command.get("controllerId") or 0)
    except (TypeError, ValueError):
        return False
    controller = turn.unit(controller_id)
    if controller is None or controller.kind not in (PIONEER, "worker"):
        return False
    if distance(controller.pos, weapon.pos) > 1:
        return False
    if weapon.cooldown > 0:
        return False
    target_limit = weapon.level if weapon.kind in ("gatling", "rocket") else 1
    if len(positions) > max(1, target_limit):
        return False
    try:
        return all(
            distance(weapon.pos, Pos.load(target)) <= weapon.range_of_attack()
            for target in positions
        )
    except (KeyError, TypeError, ValueError):
        return False


def _load_target(command: dict[str, Any]) -> Pos | None:
    try:
        return Pos.load(command["targetPos"][0])
    except (KeyError, TypeError, ValueError):
        return None
