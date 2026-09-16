import logging
import re
import shlex
from dataclasses import dataclass
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

_TASK_FILE_PATTERN = re.compile(
    r"(?:阅读|读取|查看|打开)\s*([A-Za-z0-9_./-]+\.md)"
    r"|read(?:\s+(?:the\s+)?file)?\s+([A-Za-z0-9_./-]+\.md)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TaskAction:
    """开拓者任务本回合要返回给判题器的 prompt 和沙盒命令。"""

    prompt: str = ""
    execute_cmd: str = ""


def pioneer_day(
    turn: Turn,
    pioneer: Unit,
    commands: dict[int, dict[str, Any]],
    claimed: set[Pos],
    step_toward: StepToward,
) -> TaskAction:
    """处理开拓者到达任务点、接取任务和提交答案的流程。"""
    if pioneer.kind != PIONEER:
        LOGGER.info("task-flow state=not_pioneer role=%s", pioneer.unit_id)
        return TaskAction()
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
        return TaskAction()
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
        # 领取任务后等待判题器在下一回合返回 phaseTask。
        return TaskAction()
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
    return TaskAction()


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
) -> TaskAction:
    if not turn.phase_task:
        return TaskAction()
    task_points = turn.task_points()
    if not task_points:
        action = _task_action(turn)
        LOGGER.info(
            "task-flow state=active_task_no_point pioneer=%s prompt_len=%s execute_cmd=%s",
            pioneer.unit_id,
            len(action.prompt),
            bool(action.execute_cmd),
        )
        return action
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
            return TaskAction()
        else:
            action = _task_action(turn)
            LOGGER.info(
                "task-flow state=wait_llm pioneer=%s task_pos=%s prompt_len=%s execute_cmd=%s",
                pioneer.unit_id,
                task_pos.dump(),
                len(action.prompt),
                bool(action.execute_cmd),
            )
            return action
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
    return TaskAction()


def _task_action(turn: Turn) -> TaskAction:
    """把动态任务拆成：读取文件 -> 提供上下文 -> 等待答案。"""
    if not turn.phase_task or turn.llm_response:
        return TaskAction()

    task_file = _task_file(turn.phase_task)
    if task_file and not turn.last_cmd_result:
        # 判题器的沙盒工作目录就是任务文件目录，直接查看并读取目标文件。
        command = f"ls -la; cat -- {shlex.quote(task_file)}"
        LOGGER.info(
            "task-flow state=read_task_file file=%s execute_cmd=%s",
            task_file,
            command,
        )
        return TaskAction(execute_cmd=command)

    prompt = (
        "你正在参加游戏里的自进化任务。请根据任务要求完成推理或生成答案。"
        "如果任务要求查询、计算、解析文本或总结，请直接给出可提交的最终答案；"
        "如果任务明确要求固定格式，请严格按该格式输出。不要输出解释、步骤或多余文本。\n\n"
        f"任务描述：\n{turn.phase_task}\n\n"
    )
    if task_file:
        prompt += (
            f"已读取文件 {task_file}，以下是沙盒命令输出：\n"
            f"{turn.last_cmd_result}\n\n"
        )
    prompt += "请根据以上全部信息直接给出最终可提交答案。"
    return TaskAction(prompt=prompt)


def _task_file(phase_task: str) -> str | None:
    """从动态 phaseTask 中提取安全的 Markdown 相对路径。"""
    match = _TASK_FILE_PATTERN.search(phase_task)
    if match is None:
        return None
    path = match.group(1) or match.group(2)
    if path.startswith("/") or ".." in path.split("/"):
        LOGGER.warning("task-flow rejected unsafe task file=%s", path)
        return None
    return path
