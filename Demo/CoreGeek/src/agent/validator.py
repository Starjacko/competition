from typing import Any

from .protocol import PIONEER, TOWER_TYPES, Pos, Turn, distance


def validated_commands(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for role_id, command in commands.items():
        role = turn.unit(role_id)
        if role is not None and role.health > 0 and command_valid(
            turn, role, command,
        ):
            result[str(role_id)] = command
    return result


def command_valid(
    turn: Turn,
    role: Any,
    command: dict[str, Any],
) -> bool:
    action = command.get("action")
    if action not in {
        "move", "collect", "build", "attack", "sell",
        "acceptTask", "submitAnswer", "use",
    }:
        return False
    if action == "attack" and turn.is_day:
        return False
    if action == "build" and (not turn.is_day or role.kind != "worker"):
        return False
    if action in {"collect", "build"} and role.kind != "worker":
        return False
    if action in {"acceptTask", "submitAnswer"} and role.kind != PIONEER:
        return False
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
    if action == "attack":
        try:
            controller_id = int(command.get("controllerId") or 0)
        except (TypeError, ValueError):
            return False
        controller = turn.unit(controller_id)
        if controller is None or controller.kind not in TOWER_TYPES:
            return False
        if distance(role.pos, controller.pos) > 1:
            return False
        targets = command["targetPos"]
        if len(targets) > max(1, controller.level):
            return False
        try:
            return all(
                distance(controller.pos, Pos.load(target))
                <= controller.range_of_attack()
                for target in targets
            )
        except (KeyError, TypeError, ValueError):
            return False
    if action == "use":
        name = command.get("name")
        return isinstance(name, str) and name in role.backpack
    return True


def _load_target(command: dict[str, Any]) -> Pos | None:
    try:
        return Pos.load(command["targetPos"][0])
    except (KeyError, TypeError, ValueError):
        return None
