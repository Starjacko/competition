from typing import Any, Callable

from .protocol import (
    Pos,
    Turn,
    Unit,
    WALL_MATERIAL,
    collect_command,
    distance,
    move_command,
    sell_command,
    use_command,
)

STONE_SAFETY_STOCK = 2
WALL_BUILD_STONE_STOCK = 2
StepToward = Callable[..., Pos | None]


def worker_resource_action(
    turn: Turn,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
    step_toward: StepToward,
    *,
    preferred_material: str | None = None,
    keep_stone_stock: bool = True,
) -> bool:
    """采矿和卖矿的单回合经济决策。"""
    if role.backpack_full:
        vendor = nearest_neutral(turn, role, "vendor")
        if vendor is None:
            return False
        if distance(role.pos, vendor) <= 1:
            sellable = sellable_item(role)
            if sellable is not None:
                commands[role.unit_id] = sell_command(sellable)
                return True
        step = step_toward(turn, role, vendor, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)
            return True
        return False

    material = preferred_material or best_material(
        turn, role, keep_stone_stock=keep_stone_stock,
    )
    mine = nearest_neutral(turn, role, material, claimed)
    if mine is None:
        return False
    if distance(role.pos, mine) <= 1:
        commands[role.unit_id] = collect_command(mine)
        claimed.add(mine)
        return True
    step = step_toward(turn, role, mine, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        claimed.add(mine)
        return True
    return False


def nearest_neutral(
    turn: Turn,
    role: Unit,
    kind: str,
    claimed: set[Pos] | None = None,
) -> Pos | None:
    claimed = claimed or set()
    points = tuple(pos for pos in turn.neutral(kind) if pos not in claimed)
    return min(points, key=lambda pos: distance(role.pos, pos), default=None)


def best_material(
    turn: Turn,
    role: Unit,
    *,
    keep_stone_stock: bool = True,
) -> str:
    if keep_stone_stock and stone_count(role) < STONE_SAFETY_STOCK:
        return WALL_MATERIAL
    materials = ("iron", "copper", "stone") if keep_stone_stock else ("iron", "copper")
    prices = {
        material: turn.vendor_prices.get(material, 0)
        for material in materials
    }
    return max(prices, key=lambda material: (prices[material], material))


def sellable_item(role: Unit) -> str | None:
    for material in ("iron", "copper", "stone"):
        if material in role.backpack:
            return material
    return None


def stone_count(role: Unit) -> int:
    return role.backpack.count(WALL_MATERIAL)


def has_stone(role: Unit) -> bool:
    return stone_count(role) > 0


def has_wall_build_stock(role: Unit) -> bool:
    return stone_count(role) >= WALL_BUILD_STONE_STOCK


def use_medicine_if_needed(
    role: Unit,
    commands: dict[int, dict[str, Any]],
) -> bool:
    """只在角色生命值过低时消耗药品，避免浪费库存。"""
    if role.health <= 50 and "medicine" in role.backpack:
        commands[role.unit_id] = use_command("medicine")
        return True
    return False
