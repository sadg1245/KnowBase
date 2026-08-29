# 第四阶段：知识卡片与复习中心补齐设计

## 1. 背景与目标

当前系统已经具备卡片基础表、到期查询、四档评分、从知识点和 AI 回答创建卡片，以及一个可翻面的复习页，但尚未形成完整的卡片管理和长期复习闭环。

本阶段在保留现有数据和接口兼容性的前提下完成以下目标：

1. 用户能够创建、查看、编辑和删除知识卡片。
2. 卡片完整保存来源、知识库、标签、难度、掌握度和复习调度信息。
3. 用户能够从知识点、AI 回答、原文选段和手动输入创建卡片。
4. 复习中心提供每日概览、卡片管理和快速复习三个完整入口。
5. 四档评分更新复习间隔、卡片掌握度、知识点掌握度和下一次复习时间。
6. 记录每次复习的真实耗时和掌握变化。
7. 桌面键盘和手机触摸操作都能完成完整复习流程。

## 2. 范围

### 2.1 本期包含

- 原位扩展 `Flashcard` 和 `ReviewLog`，不创建平行卡片系统。
- SQLite 兼容迁移和全新数据库建表支持。
- 卡片 CRUD、批量知识点生成、原文选段生成、复习概览和评分 API。
- 复习中心概览、卡片库、卡片表单、快速复习和结果页。
- 文档原文选段创建卡片。
- 知识库知识点批量生成卡片。
- 掌握度、掌握状态、真实耗时和复习活动同步。
- 后端、前端状态逻辑和浏览器交互专项测试。

### 2.2 本期不包含

- FSRS、完整 SM-2 或云端第三方算法服务。
- 多用户隔离模型重构。
- 离线优先同步、跨设备冲突解决。
- 自动推送提醒和后台定时通知。
- LLM 逐张改写卡片。知识点卡片使用已经由 AI 提取的结构化知识点生成，避免额外模型调用和不稳定性。

## 3. 设计原则

- **兼容现有数据**：新增列都有安全默认值；现有卡片无需重建即可继续复习。
- **单一事实来源**：卡片调度状态保存在 `Flashcard`，每次变化追加到 `ReviewLog`。
- **可升级调度**：第一版保留当前简化算法，同时保存算法版本和扩展状态。
- **服务端负责一致性**：掌握度、状态、间隔和日志在同一数据库事务中更新。
- **前端负责真实交互时间**：卡片展示时开始计时，评分时上报秒数；服务端负责范围校验。
- **渐进式交互**：概览引导开始复习，卡片管理承载 CRUD，快速复习保持专注。

## 4. 数据模型

### 4.1 Flashcard

保留现有字段并增加：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `tags` | JSON | `[]` | 用户可编辑标签 |
| `difficulty` | Integer | `2` | 1–5 难度 |
| `mastery` | Float | `0.0` | 0–1 数值掌握度 |
| `mastery_status` | String(20) | `not_started` | `not_started`、`learning`、`mastered` |
| `source_type` | String(30) | `manual` | `manual`、`knowledge_point`、`answer`、`selection` |
| `source_snapshot` | JSON | `null` | 文件、页码、标题、原文片段、消息等结构化来源 |
| `algorithm_version` | String(20) | `simple_v1` | 调度算法版本 |
| `scheduler_data` | JSON | `{}` | 为 repetitions、lapses 等后续字段预留 |
| `last_reviewed_at` | DateTime | `null` | 最近复习时间 |
| `total_review_seconds` | Integer | `0` | 累计真实复习秒数 |
| `updated_at` | DateTime | 当前时间 | 最近更新时间 |

继续使用现有 `workspace_id`、`knowledge_point_id`、`origin_message_id`、`front`、`back`、`source_label`、`due_at`、`interval_days`、`ease` 和 `review_count`。

### 4.2 ReviewLog

在现有评分、间隔和时间字段上增加：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `duration_seconds` | Integer | `0` | 本张卡实际耗时，范围 0–3600 |
| `previous_mastery` | Float | `0.0` | 评分前掌握度 |
| `next_mastery` | Float | `0.0` | 评分后掌握度 |
| `previous_status` | String(20) | `not_started` | 评分前状态 |
| `next_status` | String(20) | `learning` | 评分后状态 |
| `algorithm_version` | String(20) | `simple_v1` | 本次使用的算法 |

### 4.3 迁移

`run_compat_migrations` 为 SQLite 安装逐列补齐字段和默认值。新字段只做增加，不重写用户数据。现有卡片的 `source_type` 默认为 `manual`；存在 `origin_message_id` 的历史数据在读取时仍可识别为回答来源，但迁移不执行高成本回填。

PostgreSQL 和新 SQLite 数据库继续通过 SQLAlchemy metadata 创建完整结构。

## 5. 掌握与调度规则

### 5.1 间隔算法

保留现有 `schedule_review(previous, ease, rating)` 的确定性规则：

- 1 忘记了：回到 1 天并降低 ease。
- 2 有点模糊：小幅增加间隔并降低 ease。
- 3 记住了：按当前 ease 扩展间隔。
- 4 非常熟练：更大幅增加间隔并提高 ease。

`due_at` 使用服务器当前 UTC 时间加新间隔。`algorithm_version` 为 `simple_v1`，以后升级算法时旧日志仍可解释。

### 5.2 掌握度变化

沿用当前变化幅度以保持体验连续：

- 1：`-0.12`
- 2：`+0.02`
- 3：`+0.12`
- 4：`+0.20`

结果限制在 0–1。状态规则为：

- 从未复习且掌握度为 0：`not_started`
- 已复习且掌握度低于 0.8：`learning`
- 掌握度达到 0.8：`mastered`

每次评分先更新卡片掌握度和状态。卡片关联知识点时，再用同一增量更新知识点，并按相同阈值同步 `mastery_status`。回答卡片或手动卡片没有知识点关联时，只更新卡片本身。

### 5.3 真实耗时

进入一张卡时，前端保存 `performance.now()`。评分时计算整数秒并发送 `duration_seconds`。后端接受 0–3600 秒；旧客户端不传时默认为 0。

评分成功后：

- `ReviewLog.duration_seconds` 保存本次耗时。
- `Flashcard.total_review_seconds` 累加耗时。
- `StudyActivity.duration_seconds` 使用真实耗时，不再固定为 30 秒。
- 结果页使用本轮前端累计值展示总耗时和平均耗时。

## 6. API 设计

### 6.1 卡片 CRUD

- `GET /api/learning/cards`
  - 保留 `workspace_id` 和 `due_only`。
  - 增加 `source_type`、`tag`、`query`、`limit`、`offset`。
  - 返回扩展后的完整卡片结构。
- `POST /api/learning/cards`
  - 手动创建，`source_type` 固定为 `manual`。
- `PUT /api/learning/cards/{card_id}`
  - 可修改正面、背面、知识库、标签、难度、来源显示文本和到期时间。
  - 不允许直接伪造复习次数和日志。
- `DELETE /api/learning/cards/{card_id}`
  - 保持现有语义并返回 204。

### 6.2 卡片生成

- `POST /api/learning/knowledge-points/{point_id}/card`
  - 保持现有接口，补充完整来源快照和卡片字段。
  - 对同一知识点采用幂等语义：已有卡片时返回现有卡片，避免重复点击生成重复卡。
- `POST /api/learning/workspaces/{workspace_id}/cards/generate`
  - 请求可包含知识点 ID 列表；为空时选择当前知识库中尚无卡片的知识点。
  - 每个知识点生成一张卡，并返回创建数量和卡片列表。
- `POST /api/learning/cards/from-selection`
  - 接收知识库、文档、原文片段、正面问题、背面答案、页码和章节。
  - `source_type=selection`，结构化保存选段来源。
- `POST /api/chat/messages/{message_id}/card`
  - 保持幂等；补充 `source_type=answer` 和来源快照。

### 6.3 复习概览

`GET /api/learning/review/summary?timezone_offset_minutes=480`

返回：

```json
{
  "due_count": 12,
  "new_count": 4,
  "completed_today": 8,
  "estimated_minutes": 6,
  "streak_days": 5,
  "overdue_count": 3,
  "weak_points": [],
  "daily_target": 10
}
```

统计口径：

- `due_count`：`due_at <= now` 的卡片。
- `new_count`：到期且 `review_count == 0` 的卡片。
- `completed_today`：用户本地今日范围内的 ReviewLog 数量。
- `estimated_minutes`：优先使用最近 30 次复习的平均耗时；无历史时按每张 30 秒，向上取整。
- `streak_days`：按用户本地日期计算连续存在 ReviewLog 或 StudyActivity 的天数；今天没有活动时允许从昨天开始计算。
- `overdue_count`：`due_at` 早于用户本地今日零点的卡片。
- `weak_points`：关联知识点且掌握度最低的最多 5 项，优先重点知识点。
- `daily_target`：来自用户配置。

`timezone_offset_minutes` 表示本地时间相对 UTC 的分钟偏移，例如中国标准时间为 `480`。前端传入 `-new Date().getTimezoneOffset()`。

### 6.4 评分

`POST /api/learning/cards/{card_id}/review`

请求：

```json
{
  "rating": 3,
  "duration_seconds": 18
}
```

响应除完整卡片外增加本次变化摘要：

```json
{
  "card": {},
  "change": {
    "previous_mastery": 0.42,
    "next_mastery": 0.54,
    "previous_status": "learning",
    "next_status": "learning",
    "previous_interval": 3,
    "next_interval": 8
  }
}
```

## 7. 前端信息架构

### 7.1 复习中心概览

`/review` 初始显示：

- 今日待复习主数字和“开始复习”主按钮。
- 新卡片、今日完成、预计时长、连续学习、逾期卡片五项紧凑统计。
- 薄弱知识点列表。
- “管理卡片”入口。
- 无到期卡片时显示下一步操作，而不是自动进入空白复习页。

视觉继续使用现有“拾光”纸张和青绿色体系。页面的识别性元素是“记忆轨迹”：概览中的到期卡、今日完成和下一次复习以一条克制的时间轨迹连接；不引入新的全局字体或无关装饰。

### 7.2 卡片管理

卡片库支持：

- 按知识库、来源、标签和关键词筛选。
- 查看正反面摘要、标签、难度、掌握状态和下次复习时间。
- 新建和编辑共用一个表单抽屉或弹窗。
- 删除前使用确认对话框。
- 在窄屏上使用纵向卡片列表，不使用必须横向滚动的数据表格。

### 7.3 快速复习

复习会话从当前到期卡片快照开始，避免过程中因评分更新到期时间而改变总数。

- 点击、Enter 或 Space：翻面/隐藏答案。
- 答案显示后按 1、2、3、4：对应四档评分。
- 手机向上滑：翻面。
- 答案显示后向左滑：忘记了。
- 答案显示后向右滑：记住了。
- 四个可见按钮始终保留，模糊和非常熟练不依赖手势。
- 手势阈值 56px；垂直滚动优先，未达到阈值不触发评分。
- 提交期间锁定操作，防止双击产生重复日志。
- 单张失败时保留当前卡并显示可重试错误。

### 7.4 结果页

完成后展示：

- 完成张数。
- 四档评分分布。
- 总耗时和平均每张耗时。
- 本轮卡片平均掌握度变化。
- 返回概览和再次查看卡片两个操作。

## 8. 原文选段流程

文档详情的原文区域监听浏览器文本选择。只有选择内容属于当前原文容器且去除空白后非空时，显示“生成卡片”操作。

点击后打开卡片表单：

- 背面默认填入选中文本。
- 正面留空并要求用户填写问题。
- 自动带入知识库、文档、页码、章节和原文片段。
- 用户可补充标签和难度。

选择状态在关闭表单、切换文档或创建成功后清除。PDF iframe 内部选择不在本期支持范围；支持系统解析后显示的文本原文区域。

## 9. 错误处理与并发

- API 对不存在的卡片、知识点、文档和知识库返回 404。
- 创建卡片时校验知识点或文档属于指定知识库。
- 更新卡片知识库时，关联知识点必须属于目标知识库，否则返回 400。
- 批量生成逐个去重，并在同一事务中提交。
- 评分提交期间前端禁用按钮和快捷键。
- 评分接口不保证对任意重复请求幂等；前端防重复，数据库事务保证单次更新完整。未来若需要离线同步，再增加客户端 review token。
- 概览加载失败与卡片列表加载失败分别呈现，不阻断其他区域。

## 10. 代码边界

后端把统计和评分逻辑从路由中提取到 `backend/app/services/review_service.py`：

- `mastery_after_review`
- `mastery_status_for`
- `review_card`
- `build_review_summary`

路由负责参数解析和 HTTP 错误映射，服务负责事务内业务一致性。

前端把复习状态从页面中提取到 `frontend/src/features/review/`：

- `types.ts`：会话和统计类型。
- `reviewSession.ts`：当前卡、计时、评分结果和完成状态的纯逻辑。
- `gestures.ts`：触摸位移到动作的纯函数。

页面组件拆分为概览、卡片库、卡片表单、复习卡和结果面板，避免继续扩大单文件 `ReviewCenter.tsx`。

## 11. 测试策略

### 11.1 后端

- 模型和 SQLite 兼容迁移包含所有新增列。
- 创建、读取、更新和删除卡片。
- 手动、知识点、回答和选段四种来源。
- 知识点批量生成去重。
- 四档评分的间隔、ease、到期时间和掌握度变化。
- 卡片与知识点掌握状态同步。
- ReviewLog 和 StudyActivity 使用真实耗时。
- 概览的今日、新卡、完成、预计时长、连续天数、逾期和薄弱知识点统计。
- 时区跨日边界。
- 非法耗时、跨知识库关联和不存在资源。

### 11.2 前端

- API 类型和请求参数。
- 复习会话计时、评分累计和结果汇总。
- Enter/Space 翻面与数字键评分。
- 触摸阈值、方向和垂直滚动保护。
- 概览、空状态、卡片表单、删除确认和结果页渲染。
- 原文选择创建卡片状态。
- 320px、390px 和桌面布局无横向溢出。

### 11.3 验收浏览器流程

1. 创建手动卡片，编辑后删除。
2. 从知识点批量生成卡片。
3. 从 AI 回答和原文选段生成卡片。
4. 查看复习概览并开始复习。
5. 用键盘翻面和评分，确认下一张出现。
6. 用手机视口滑动翻面和评分。
7. 完成后核对结果统计。
8. 刷新概览，确认完成数、待复习数、耗时和掌握状态变化。

## 12. 验收标准

- 用户能够在复习中心完成卡片创建、编辑、删除和筛选。
- 四种卡片来源都保存明确的 `source_type` 和可展示来源。
- 复习概览完整显示需求中的八类信息。
- 四档评分产生确定且合理的间隔和下次复习时间。
- 每次评分记录真实耗时和掌握变化。
- 关联知识点的 `mastery` 与 `mastery_status` 同步更新。
- 键盘和手机触摸均可完成一轮复习。
- 320px 宽度无横向滚动，进度数字不再竖排。
- 新增专项测试与现有完整测试、前端构建全部通过。
