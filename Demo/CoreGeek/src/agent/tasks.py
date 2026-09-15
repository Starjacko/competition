import logging
from typing import Any, Callable

from .protocol import (
    PIONEER,
    Pos,
    Turn,
    Unit,
    accept_task_command,
    distance,
    move_command,
    submit_answer_command,
)

StepToward = Callable[..., Pos | None]
LOGGER = logging.getLogger(__name__)


def pioneer_day(
    turn: Turn,
    pioneer: Unit,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    step_toward: StepToward,
) -> str:
    """处理开拓者到达任务点、接取任务和提交答案的流程。"""
    if pioneer.kind != PIONEER:
        LOGGER.info("task-flow state=not_pioneer role=%s", pioneer.unit_id)
        return ""
    if turn.phase_task:
        LOGGER.info(
            "task-flow state=continue_task pioneer=%s llm_resp=%s",
            pioneer.unit_id,
            bool(turn.llm_response),
        )
        return _continue_task(turn, pioneer, commands, claimed, step_toward)
    active_task = _active_task(turn)
    if active_task is None:
        LOGGER.info("task-flow state=no_available_task pioneer=%s", pioneer.unit_id)
        return _continue_task(turn, pioneer, commands, claimed, step_toward)
    task_pos, _ = active_task
    if distance(pioneer.pos, task_pos) <= 1:
        if turn.phase_task and turn.llm_response:
            commands[pioneer.unit_id] = submit_answer_command(
                turn.llm_response,
            )
        elif not turn.phase_task:
            commands[pioneer.unit_id] = accept_task_command()
            LOGGER.info(
                "task-flow state=accept_task pioneer=%s task_pos=%s",
                pioneer.unit_id,
                task_pos.dump(),
            )
        return _task_prompt(turn)
    step = step_toward(turn, pioneer, task_pos, claimed)
    if step is not None:
        commands[pioneer.unit_id] = move_command(step)
        LOGGER.info(
            "task-flow state=move_to_task pioneer=%s task_pos=%s step=%s",
            pioneer.unit_id,
            task_pos.dump(),
            step.dump(),
        )
    else:
        LOGGER.info(
            "task-flow state=task_unreachable pioneer=%s task_pos=%s",
            pioneer.unit_id,
            task_pos.dump(),
        )
    return ""


def _active_task(turn: Turn) -> tuple[Pos, dict[str, Any]] | None:
    return next(
        (
            (pos, task) for pos, task in turn.task_points()
            if task.get("isValid")
            and int(task.get("coldDownRounds") or 0) == 0
        ),
        None,
    )


def _continue_task(
    turn: Turn,
    pioneer: Unit,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    step_toward: StepToward,
) -> str:
    if not turn.phase_task:
        return ""
    task_points = turn.task_points()
    if not task_points:
        LOGGER.info(
            "task-flow state=active_task_no_point pioneer=%s prompt_len=%s",
            pioneer.unit_id,
            len(_task_prompt(turn)),
        )
        return _task_prompt(turn)
    task_pos = min(
        (pos for pos, _ in task_points),
        key=lambda pos: distance(pioneer.pos, pos),
    )
    if distance(pioneer.pos, task_pos) <= 1:
        if turn.llm_response:
            commands[pioneer.unit_id] = submit_answer_command(
                turn.llm_response,
            )
            LOGGER.info(
                "task-flow state=submit_answer pioneer=%s task_pos=%s answer_len=%s",
                pioneer.unit_id,
                task_pos.dump(),
                len(turn.llm_response),
            )
        else:
            LOGGER.info(
                "task-flow state=wait_llm pioneer=%s task_pos=%s prompt_len=%s",
                pioneer.unit_id,
                task_pos.dump(),
                len(_task_prompt(turn)),
            )
        return _task_prompt(turn)
    step = step_toward(turn, pioneer, task_pos, claimed)
    if step is not None:
        commands[pioneer.unit_id] = move_command(step)
        LOGGER.info(
            "task-flow state=return_to_task pioneer=%s task_pos=%s step=%s",
            pioneer.unit_id,
            task_pos.dump(),
            step.dump(),
        )
    else:
        LOGGER.info(
            "task-flow state=active_task_unreachable pioneer=%s task_pos=%s",
            pioneer.unit_id,
            task_pos.dump(),
        )
    return _task_prompt(turn)


def _task_prompt(turn: Turn) -> str:
    if not turn.phase_task or turn.llm_response:
        return ""
    return (
        "你正在参加游戏里的自进化任务。请根据任务要求完成推理或生成答案。"
        "如果任务要求查询、计算、解析文本或总结，请直接给出可提交的最终答案；"
        "如果任务明确要求固定格式，请严格按该格式输出。不要输出解释、步骤或多余文本。\n\n"
        f"{turn.phase_task}"
    )
