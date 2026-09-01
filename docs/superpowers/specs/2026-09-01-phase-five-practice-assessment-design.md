# 第五阶段：练习、测验、错题本与薄弱知识设计

## 背景

当前项目已有基础练习页、固定模板题、逐题提交、最后一次答题状态和基于掌握度的简单薄弱知识列表。这些能力可以继续兼容，但不足以满足第五阶段：题型不完整、缺少 AI 生成和主观评分、没有测验卷和逐次作答记录、错题数据不完整，薄弱知识也没有综合计算或改变复习安排。

本设计在现有 FastAPI、SQLAlchemy、SQLite/PostgreSQL、React 和 Ant Design 架构内新增独立的测验域，不拆分微服务，不删除已有题目或学习数据。

## 目标

1. 从指定知识库、资料、章节或知识点生成六类 AI 练习题。
2. 支持逐题和整卷答题、真实计时、自动评分、AI 主观评价、结果汇总和重新作答。
3. 自动维护包含完整学习证据的错题记录。
4. 综合答题与复习行为计算薄弱程度，并提供可执行建议。
5. 让薄弱知识进入近期学习任务，并影响后续针对性练习与复习顺序。
6. 保留现有练习、错题入口和历史数据的可访问性。

## 非目标

- 不引入独立测验微服务。
- 不实现多人、班级、教师阅卷或排行榜。
- 不实现远程监考、防作弊或证书体系。
- 不在大模型不可用时把固定模板题标记为 AI 题。
- 不自动删除旧题、旧错题或旧学习记录。

## 核心决策

### AI 可用性

AI 生成和主观评分必须使用当前已配置的大模型。模型未配置、调用失败、返回结构不合法或严格资料模式下证据不足时，接口返回面向用户的明确错误。系统不以模板题静默降级。

客观题评分不依赖大模型。已生成题目的客观题仍可在模型不可用时完成评分；主观题提交保留为待评价状态，用户可稍后重试 AI 评价。

### 兼容策略

采用增量数据库迁移：保留 `quiz_questions` 及现有接口，将其扩展为题库实体；新增测验卷、作答记录、错题记录、薄弱知识状态和学习任务表。旧题视为没有所属测验卷的历史题，仍可在现有错题入口查看和重做。

### 来源证据

每道 AI 题必须保存结构化引用快照，至少包含：

- `document_id`
- 文件名
- `chunk_id`
- 页码（可空）
- 章节路径（可空）
- 原文片段

严格资料模式只允许依据检索证据生成答案、解析和评分规则。证据不足以生成指定数量时，接口返回实际缺口并且不创建不完整测验卷。

## 数据模型

### QuizSet

表示一次生成的测验卷：

- `id`, `workspace_id`, `title`
- `document_ids`, `knowledge_point_ids`, `section_filters`
- `question_count`, `difficulty`, `question_types`, `strict_sources`
- `answer_mode`: `sequential | full_paper`
- `duration_limit_seconds`（可空）
- `status`: `generating | ready | failed`
- `generation_model`, `generation_error`
- `created_at`, `updated_at`

### QuizRun

表示同一测验卷的一轮独立作答，重新作答时创建新记录：

- `id`, `quiz_set_id`, `round_number`
- `answer_mode`: `sequential | full_paper`
- `status`: `not_started | in_progress | submitted`
- `started_at`, `submitted_at`, `elapsed_seconds`
- `score`, `max_score`, `correct_count`, `graded_count`
- `created_at`, `updated_at`

同一测验卷的 `round_number` 单调递增。服务端计时、结果汇总和题目作答都归属于 `QuizRun`，不得覆盖上一轮。

### QuizQuestion 扩展

继续使用现有表并增加：

- `quiz_set_id`, `document_id`
- `question_type`: `single_choice | multiple_choice | true_false | fill_blank | short_answer | concept_explanation`
- `difficulty`: `easy | medium | hard`
- `answer_payload`: JSON；保存单值、多值或关键词答案
- `grading_rubric`: JSON；保存主观题评分维度、关键点和满分
- `source_snapshot`: JSON 数组
- `strict_sources`, `generation_model`, `position`

旧字段 `answer`、`options`、`source_label` 保留，用于兼容旧客户端和旧数据。新题同时写入可兼容的 `answer` 文本；旧 `choice` 和 `short` 题型分别映射为 `single_choice` 和 `short_answer`。新接口优先使用结构化字段。

### QuizAttempt

每次提交均创建不可覆盖的作答记录：

- `id`, `quiz_set_id`, `quiz_run_id`, `question_id`
- `attempt_number`
- `user_answer`: JSON
- `is_correct`（主观题待评价时可空）
- `score`, `max_score`
- `evaluation_status`: `graded | pending_ai | grading_failed`
- `feedback`, `error_reason`
- `duration_seconds`
- `submitted_at`

不得再用题目表上的 `last_answer` 代替完整作答历史。兼容字段仍同步为最近一次作答状态。

### MistakeRecord

每个题目最多一个当前错题记录：

- `id`, `question_id`, `knowledge_point_id`, `workspace_id`
- `latest_attempt_id`
- `user_answer_snapshot`, `correct_answer_snapshot`
- `error_reason`
- `source_snapshot`
- `wrong_count`, `redo_count`, `consecutive_correct`
- `mastery_status`: `unresolved | improving | mastered`
- `first_wrong_at`, `last_wrong_at`, `last_redone_at`, `resolved_at`

首次答错自动创建；重复答错累计 `wrong_count`；从错题入口提交累计 `redo_count`。连续两次重做正确后标记 `mastered`，再次答错则恢复 `unresolved`。

### WeakKnowledgeState

每个知识点保存最近一次薄弱度计算结果：

- `knowledge_point_id`, `workspace_id`
- `weakness_score`: 0–100，越高越薄弱
- `accuracy_component`
- `repeat_error_component`
- `review_feedback_component`
- `response_time_component`
- `recency_component`
- `evidence`: JSON 统计快照
- `recommended_actions`: JSON
- `calculated_at`

### LearningTask

保存近期可执行学习任务：

- `id`, `workspace_id`, `knowledge_point_id`
- `task_type`: `reread | simple_explanation | new_example | targeted_practice | review`
- `title`, `path`, `payload`
- `due_at`, `priority`, `status`: `pending | completed | dismissed`
- `created_at`, `completed_at`

同一知识点、同一类型的未完成任务保持幂等，不重复创建。

## AI 生成流程

1. 验证知识库以及所有资料、章节和知识点均属于当前范围。
2. 按资料和知识点范围检索原始证据；严格模式不使用模型常识补充。
3. 将数量、难度、题型配比、证据和结构化输出模式发送给已配置模型。
4. 使用 Pydantic 校验模型输出：题型、选项、答案、解析、评分规则和引用都必须合法。
5. 校验引用只能指向本次检索结果；校验客观题答案确实存在于选项中。
6. 所有题目验证成功后，在一个事务中创建测验卷和题目。任何题目不合法则整卷不落库。

六种题型规则：

- 单选：恰好一个正确选项。
- 多选：至少两个正确选项，答案按集合比较。
- 判断：允许正确或错误陈述，不能固定为“正确”。
- 填空：支持一个或多个可接受答案及标准化比较。
- 简答：保存关键点与评分规则，由 AI 评分。
- 概念解释：按准确性、覆盖度和表达清晰度由 AI 评分。

## 答题与评分

### 测验模式

- 逐题模式：每题提交后立即展示结果、参考答案、解析和引用。
- 整卷模式：全部答案统一提交，提交前不显示答案；提交后展示总分、正确率、耗时和逐题结果。
- 计时从首次开始答题时记录，页面刷新后根据服务端 `started_at` 恢复，不依赖前端内存计时。
- 重新作答创建新的作答轮次，不覆盖历史记录。

### 评分

- 单选、判断：标准化后精确匹配。
- 多选：按无序集合精确匹配。
- 填空：逐空匹配可接受答案，支持大小写、空白和标点标准化。
- 简答、概念解释：AI 根据保存的评分规则和来源证据返回分数、命中关键点、缺失点、错误原因和改进建议。
- AI 主观评分失败时保存 `pending_ai` 或 `grading_failed`，不得判为错误；支持重试评价。

## 薄弱度计算

每次作答、卡片复习或相关学习任务完成后重新计算受影响知识点。默认权重：

- 正确率：35%。最近 20 次作答采用时间衰减加权。
- 重复错误：25%。未解决错题和连续错误贡献更高。
- 复习反馈：15%。卡片评分 1/2 增加薄弱度，3/4 降低薄弱度。
- 回答耗时：10%。相对该题型和难度的个人历史中位数归一化。
- 学习间隔：15%。距离最近一次作答、复习或学习任务越久，分数越高。

分数限制在 0–100：

- 0–29：稳定
- 30–59：需要巩固
- 60–79：薄弱
- 80–100：优先处理

计算结果必须保存各组成项和统计证据，便于解释和测试，不使用不可解释的单次 AI 判断代替数值算法。

## 推荐与复习联动

对于分数不低于 60 的知识点，系统生成以下动作：

- 重新阅读：跳到最高相关度引用位置。
- 通俗讲解：打开 AI 学习页并预设知识点和通俗模式。
- 新例子：打开 AI 学习页并预设生成例子的请求。
- 针对性练习：打开练习页并限定该知识点。
- 近期复习：创建三天内到期的 `LearningTask`。

薄弱度影响后续安排：

- 今日任务按 `priority` 和 `due_at` 展示薄弱知识任务。
- 新测验默认优先抽取薄弱分数高的知识点。
- 复习中心在到期卡片中优先排列高薄弱度知识点；不提前篡改间隔重复算法计算出的到期时间。
- 没有关联卡片时创建学习任务，而不是自动生成用户未确认的卡片。

## API 设计

- `POST /api/learning/quiz-sets/generate`：按完整配置生成测验卷。
- `GET /api/learning/quiz-sets/{id}`：返回测验卷、题目和最近作答状态；提交前隐藏答案。
- `POST /api/learning/quiz-sets/{id}/runs`：创建新的答题轮次，或在显式恢复时返回尚未提交的一轮。
- `POST /api/learning/quiz-runs/{id}/start`：幂等开始或恢复服务端计时。
- `POST /api/learning/quiz-runs/{id}/questions/{question_id}/submit`：逐题提交。
- `POST /api/learning/quiz-runs/{id}/submit`：整卷提交。
- `POST /api/learning/quiz-runs/{id}/retry`：为同一测验卷建立下一轮作答。
- `POST /api/learning/attempts/{id}/retry-grading`：重试主观评价。
- `GET /api/learning/mistakes`：按知识库、资料、知识点和状态筛选错题。
- `POST /api/learning/mistakes/{id}/redo`：提交错题重做。
- `GET /api/learning/weak-knowledge`：返回薄弱列表、组成分和推荐动作。
- `POST /api/learning/weak-knowledge/recalculate`：重新计算指定范围。
- `GET /api/learning/tasks`：返回近期学习任务。
- `POST /api/learning/tasks/{id}/complete`：完成任务。

现有 `/api/learning/quizzes/*` 接口保留，并映射到兼容行为；新前端只使用新接口。

## 前端设计

练习页分为四个状态：

1. 生成配置：知识库、文件、章节/知识点、数量、难度、题型、严格资料模式、逐题/整卷模式和可选时限。
2. 答题：稳定计时器、题目导航、答题保存状态和未答提示。
3. 结果：总分、正确率、真实耗时、逐题答案、解析、AI 反馈和可打开的资料引用。
4. 错题本：筛选、掌握状态、错误原因、重做次数和重做入口。

薄弱知识页或现有复习中心扩展区展示分数组成、最近证据和五种推荐动作。移动端保持单列布局，整卷题目导航使用可横向滚动的紧凑控件。

前端不使用题目表的兼容答案字段提前显示正确答案。切换知识库或资料范围时继续使用请求版本保护，防止旧请求覆盖新范围。

## 错误处理

- AI 未配置：返回 409，并引导用户前往模型设置。
- AI 调用失败：返回 503，测验卷记录失败原因，不创建部分题目。
- 严格模式证据不足：返回 422，说明可生成数量和缺少的题型。
- 引用或结构化输出无效：服务端最多自动修复重试一次，仍失败则返回 502。
- 主观评分失败：保留作答并标记可重试，不计入正确率或错题状态，直到评价完成。
- 页面刷新或网络中断：已提交答案和服务端计时可恢复；未提交文本保存在当前页面会话状态中。

## 安全与数据边界

- 所有资料、知识点、题目、测验和任务引用必须验证属于目标知识库。
- 来源文本作为不可信数据嵌入提示词，明确禁止其改变系统指令或输出格式。
- 答案仅在允许的提交阶段返回。
- AI 评分只能使用题目、用户答案、保存的评分规则和引用快照。
- 导出功能新增测验卷、逐次作答、错题、薄弱状态和学习任务数据。

## 测试与验收

### 后端

- 数据模型默认值和 SQLite 兼容迁移幂等测试。
- 六种题型的结构化生成、校验和引用约束测试。
- AI 未配置、失败、无效输出和严格资料不足测试。
- 六种题型评分测试，包括主观评分失败及重试。
- 测验计时、整卷提交、逐题提交和重新作答状态机测试。
- 错题创建、重复错误、重做和掌握状态测试。
- 薄弱度五个组成项、边界值和时间衰减测试。
- 薄弱任务幂等、首页任务和复习排序联动测试。

### 前端

- 配置序列化和六种题型输入控件测试。
- 逐题、整卷、刷新恢复、计时与重新作答状态测试。
- 结果页、AI 待评价、错误重试和引用跳转测试。
- 错题筛选、重做和掌握状态测试。
- 薄弱知识组成项及推荐动作测试。
- 桌面和手机视口的真实浏览器流程验证。

### 验收标准映射

- 用户可以按知识库和难度生成练习：由生成配置和 `QuizSet` 保证。
- 每题都有答案、解析和资料引用：由 AI 输出验证和 `source_snapshot` 保证。
- 答错自动进入错题本：由作答事务更新 `MistakeRecord` 保证。
- 错题可以重新练习：由错题重做接口和状态机保证。
- 系统能够生成薄弱知识列表：由可解释薄弱度计算保证。
- 薄弱知识影响后续复习安排：由学习任务、出题优先级和复习排序保证。

## 交付顺序

1. 数据模型和兼容迁移。
2. 评分、错题和薄弱度纯业务服务。
3. AI 生成和主观评价适配层。
4. 新测验、错题、薄弱知识和任务 API。
5. 前端生成、答题、结果、错题和薄弱知识体验。
6. 全量自动化测试、生产构建和真实浏览器验收。
