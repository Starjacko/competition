import json
import logging
from typing import Any

from .combat import night
from .day import day
from .grid import next_step
from .protocol import PIONEER, Pos, Turn, Unit, distance
from .validator import validated_commands

LOGGER = logging.getLogger(__name__)

_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    """解析一回合输入，分发到白天/夜晚策略，并返回协议响应。"""
    try:
        turn = Turn.load(payload)
        commands: dict[int, dict[str, Any]] = {}
        prompt = day(turn, commands, _step_toward) if turn.is_day else ""
        if not turn.is_day:
            night(turn, commands, _step_toward)

        valid_commands = validated_commands(turn, commands)
        _log_turn(turn, commands, valid_commands, prompt)
        return {
            "roleCommandMap": valid_commands,
            "prompt": prompt,
            "executeCmd": "",
        }
    except Exception:
        LOGGER.exception("decision fallback")
        return {"roleCommandMap": {}, "prompt": "", "executeCmd": ""}


def _step_toward(
    turn: Turn,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    *,
    inside_only: bool = False,
) -> Pos | None:
    """移动到目标相邻可站位；夜晚控塔时可限制在基地附近。"""
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


def _footprint_distance(pos: Pos, footprint: tuple[Pos, ...]) -> int:
    return min((distance(pos, cell) for cell in footprint), default=0)


def _neighbours(pos: Pos) -> tuple[Pos, ...]:
    return tuple(Pos(pos.x + dx, pos.y + dy) for dx, dy in _NEIGHBOUR_STEPS)
