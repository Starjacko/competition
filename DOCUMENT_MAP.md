# 文档地图

本表是项目事实文档的入口。它只负责导航，不复制产品或技术内容。

| 职责 | 实际路径 | 更新触发条件 |
|---|---|---|
| 项目协作契约 | `AGENTS.md` | 协作规则或验证流程变化 |
| 文档地图 | `DOCUMENT_MAP.md` | 文档或目录新增、移动、替换 |
| 产品事实来源（任务书） | `docs/任务书.md` | 比赛范围、规则、流程或验收变化 |
| 技术接口事实来源 | `docs/接口文档.md` | HTTP 请求/响应或动作协议变化 |
| 技术实现来源 | `Demo/CoreGeek/pyproject.toml`、`Demo/CoreGeek/src/agent/` | 运行环境、模块或实现变化 |
| 需求台账 | `Requirements/LEDGER.md` | 每个非 Bug 需求 |
| 详细需求记录 | `Requirements/REQ-*.md` | 复杂、长期或跨模块需求 |
| 决策台账 | `Decisions/LEDGER.md` | API、架构、运行时或难以回退的方案 |
| Bug 台账 | `docs/BUG_TRACKER.md` | 发现、修复或验证 Bug |
| 项目总进度 | `docs/PROGRESS.md` | 项目交付状态或里程碑变化 |
| 待完成任务 | `docs/待完成任务.md` | 待完成事项、阻塞条件或任务证据变化 |
| 技术设计 | `docs/技术设计.md` | 语言、技术、架构、模块或运行边界变化 |
| 功能实现说明 | `docs/功能实现说明.md` | 功能实现范围、代码映射或改进计划变化 |
| 接口实现说明 | `docs/接口实现说明.md` | 接口字段、启动方式、提交或服务器验收流程变化 |
| 功能进度台账 | `Progress/LEDGER.md` | 大任务创建、状态或归档变化 |
| 功能进度记录 | `Progress/PROG-*.md` | 大任务阶段、证据、风险或阻塞变化 |
| 测试与验证说明 | `docs/验证与测试说明.md` | 测试范围、本地检查、服务器验证或真实对局结果变化 |
| 自动化测试 | 当前未发现测试目录或测试文件 | 新增或修改测试时更新 |
| UI 指南 | 不适用：当前仓库未发现 UI | 出现 UI 后建立 |

## 首次接入记录

- 接入日期：2026-09-15
- 沿用的既有文档：`docs/任务书.md`、`docs/接口文档.md`、`docs/request.txt`、`docs/response.txt`
- 新建的缺失职责：`AGENTS.md`、`DOCUMENT_MAP.md`、`Requirements/`、`Decisions/`、`Progress/`、`docs/PROGRESS.md`、`docs/BUG_TRACKER.md`、`docs/验证与测试说明.md`、`docs/待完成任务.md`、`docs/技术设计.md`
- 不适用职责：UI 指南、数据库设计、业务系统权限文档；原因是当前仓库只包含比赛机器人和 HTTP 接口实现
