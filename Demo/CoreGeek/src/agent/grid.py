from heapq import heappop, heappush
from collections import deque
from itertools import count

from .protocol import Pos, Turn, Unit, distance

_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def next_step(turn: Turn, moving: Unit, goal: Pos) -> Pos | None:
    if moving.pos == goal:
        return None
    blocked = turn.blocked(moving)
    order = count()
    frontier: list[tuple[int, int, int, Pos]] = [
        (distance(moving.pos, goal), 0, next(order), moving.pos)
    ]
    came_from: dict[Pos, Pos] = {}
    best = {moving.pos: 0}
    seen: set[Pos] = set()

    while frontier:
        _, cost, _, current = heappop(frontier)
        if current in seen:
            continue
        if current == goal:
            return _first_step(came_from, moving.pos, goal)
        seen.add(current)
        for dx, dy in _STEPS:
            step = Pos(current.x + dx, current.y + dy)
            if step in blocked or not turn.land(step):
                continue
            new_cost = cost + 1
            if new_cost >= best.get(step, new_cost + 1):
                continue
            best[step] = new_cost
            came_from[step] = current
            heappush(
                frontier,
                (
                    new_cost + distance(step, goal),
                    new_cost,
                    next(order),
                    step,
                ),
            )
    return None


def can_reach_any(
    turn: Turn,
    moving: Unit,
    goals: tuple[Pos, ...],
) -> bool:
    """检查角色是否能到达任意一个目标站位。"""
    if not goals:
        return False
    blocked = turn.blocked(moving)
    targets = set(goals)
    if moving.pos in targets:
        return True

    frontier = deque([moving.pos])
    visited = {moving.pos}
    while frontier:
        current = frontier.popleft()
        for dx, dy in _STEPS:
            step = Pos(current.x + dx, current.y + dy)
            if step in visited or step in blocked or not turn.land(step):
                continue
            if step in targets:
                return True
            visited.add(step)
            frontier.append(step)
    return False


def _first_step(came_from: dict[Pos, Pos], start: Pos, goal: Pos) -> Pos:
    current = goal
    while came_from[current] != start:
        current = came_from[current]
    return current
