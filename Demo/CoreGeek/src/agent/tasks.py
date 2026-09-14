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


def pioneer_day(
    turn: Turn,
    pioneer: Unit,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    step_toward: StepToward,
) -> None:
    """处理开拓者到达任务点、接取任务和提交答案的流程。"""
    if pioneer.kind != PIONEER:
        return
    active_task = next(
        (
            (pos, task) for pos, task in turn.task_points()
            if task.get("isValid")
            and int(task.get("coldDownRounds") or 0) == 0
        ),
        None,
    )
    if active_task is None:
        return
    task_pos, _ = active_task
    if distance(pioneer.pos, task_pos) <= 1:
        # 当前接口只提供上一轮 LLM 结果，因此仅提交已有结果。
        if turn.phase_task and turn.llm_response:
            commands[pioneer.unit_id] = submit_answer_command(
                turn.llm_response,
            )
        elif not turn.phase_task:
            commands[pioneer.unit_id] = accept_task_command()
        return
    step = step_toward(turn, pioneer, task_pos, claimed)
    if step is not None:
        commands[pioneer.unit_id] = move_command(step)
