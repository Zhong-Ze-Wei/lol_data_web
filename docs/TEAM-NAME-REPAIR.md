# 历史队名的有限修复

本入口只修复明确指定的已核验 ScoreGG 单局的 `Match.red_team_name/blue_team_name/win_team_name/team_name_provenance`、`Team.team_name` 和 `Player.team_name`。不重放指标、昵称、头像、日期、来源状态、名单或任务，不删除任何行，也不提供新名称参数。赛程标签来自实际归档的同 BO、双方相同来源 ID，不据此推断俱乐部沿革、转会或正式历史名称。

默认只读审计，必须给出数据库、原件、报告目录和单局范围：

```powershell
.venv\Scripts\python.exe -X utf8 -m scripts.repair_team_names --database .\data\lol-data.db --raw-dir .\data\raw --reports-dir .\data\reports --result-ids 34 --dry-run
```

也可用 `--ids-file .\artifacts\selected-result-ids.json` 替代 `--result-ids`。文件必须是非空 JSON 正整数列表；候选清单对象、布尔值、`all` 和新队名不接受。候选扫描不是已完成修复的证明。

检查实际报告后应用同一明确范围：

```powershell
.venv\Scripts\python.exe -X utf8 -m scripts.repair_team_names --database .\data\lol-data.db --raw-dir .\data\raw --reports-dir .\data\reports --ids-file .\artifacts\selected-result-ids.json --apply --wait-seconds 60
```

应用使用数据库所在目录的 `.sync.lock`，与采集流程共用锁；等待范围 `0–60` 秒，不停止采集器。审计先冻结三表完整行、持久赛程行、阶段及原件绑定，以及详情/赛程原件 SHA。应用前以 SQLite 在线备份 API 保存完整一致快照，验证完整性并记录 SHA；文件以 `repair-team-names-` 开头，不进入日常 `lol-data-*.db` 轮转。全部 blocked/noop 时不创建备份。

每局独立 `BEGIN IMMEDIATE`，更新前重查全行与双来源；仅按现有主键更新允许的名称与证据字段。名称交换先用 UUID 临时名称避开唯一键冲突。更新后再次逐字段核对计划，任何额外字段改变均回滚该局。失败继续处理其余指定单局，完整 JSON 计划和逐局 JSONL 留档；已有正确证明重复运行为 noop。

缺原件、SHA/唯一原行不匹配、BO/双方 ID 冲突、旧名称无对应来源、第三方/NULL 队名、重复或未知 Player 位置、非双方胜方会阻断，不猜测映射。已有未知胜方保持原未知值；详情昵称缺失时也不会删除或改写已恢复选手。现有 `normalize_result` 仅验证详情，不把它生成的指标和名单写入数据库。

已有已核验赛程证明先重新校验同 BO 与双方 ID，按旧 ID 映射现有 Team/Player 行。即使当前详情的红蓝颜色交换而文字名称未变，也不能据同名把旧数值行归给另一队；没有可信旧证明时才使用详情同名同色对应。旧证据即使只保留一方 ID，任何已知正 ID 与当前双方冲突也会阻断。

退出码 `0` 为审计或应用完成且无阻断失败；`2` 表示参数/文件问题或范围中存在 blocked/failed；`3` 表示采集锁被占用。报告中的 applied 才表示实际提交，ready 仅表示当次审计通过。此脚本仅支持 SQLite；测试使用临时库与本地归档，不调用上游或 AI。

## 2026-10-04 真实有限范围验收

6,713 局候选在新隔离 SQLite 中审计、实际应用和重复应用均通过：applied 6,713，blocked/failed 0；重复 changed/applied 0、noop 6,713，无新备份。独立逐字段比较整库，12,114,415 个非名称字段和 443,951 条记录身份保持一致；另有 161,104 项来源 ID/名称核对，使用 635 份赛程原件版本。未写生产库、未调用上游或模型。详情文件路径和实际字节 SHA 的 6,713 个完整配对另行核对，不能把计数自身当作独立证据。

香港时间 05:17:47，主库同一范围实际应用并通过独立核验。真实采集锁覆盖修复、修复后在线一致快照以及可变来源原件的 ID/SHA 核验；锁外只比较两个冻结数据库，后续采集不会混入验收。全库 12,140,286 个非名称字段、445,123 条记录身份、schema 和所有来源/任务字段不变，applied 6,713、blocked/failed 0。修复前完整备份 SHA 为 `f33255dac48edc9c674f59e92246634051318a77a438b07388487a2c2168e8c8`；备份使用独立名称前缀继续保留。

随后主库只读复查 changed 0、noop 6,713、blocked/failed 0。实际 `/match/34` 接口和页面显示 RNG/SKT，双方击杀 8/21、时长 1,812 秒与出场归属一致；1440px 桌面和 390px 手机没有文档横向溢出、NaN 或浏览器错误，此次页面验证零 AI 请求。

本机完整证明为 `artifacts/historical-team-names-global-isolated-v1-proof.json`、`artifacts/historical-team-names-global-production-v1-proof.json`，原始逐局计划、事务结果及只读复查分别保存在 `data/reports/global-team-names-v1/` 和 `data/reports/global-team-names-repeat-v1/`。这些本地数据、备份及报告不上传 Git。源码完整构建、680 个 Python 与 62 个前端测试、Ruff 和 diffcheck 通过；合并版本 `9ac8eed` 的 Windows/Ubuntu CI 均通过。该范围不能升级为全库已修复、官方历史队名或全历史已补齐。
