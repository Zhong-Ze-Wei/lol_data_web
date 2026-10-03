# 项目协作约定

- 默认中文沟通；先理解现有实现，小步修改，遵循现有风格。
- `match_id` 表示 ScoreGG 单局 resultID；系列赛编号单独存 `series_id`。
- 选手和战队表保存逐局出场记录，不能把记录数当作实体数量。
- 百分比使用 0–100，时长使用秒；未知指标保持 null，不用 0 伪装缺失。
- legacy 数据没有游戏类型证据，必须标记未核验；updated_at 不能冒充开赛时间。
- 自动采集有请求和时长预算、明确来源类型、持久重试与幂等事务。
- 测试使用临时 SQLite 与公开小样本；不得在测试中调用付费 AI 或批量联网采集。
- 分支先使用 feat/、fix/、refactor/、docs/；禁止直接在 master 上 commit。
- 每个 commit 前运行根目录 `npm run build` 和 `npm test`。
- 原子提交；验证后切回 master，通过 `git merge --no-ff <branch>` 合并并推送。
- 不提交 .env、密钥、原始私有日志、数据库、依赖、IDE 会话或构建产物。
