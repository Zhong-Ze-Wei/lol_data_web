# 历史队名的有限修复

本入口只修复明确指定的已核验 ScoreGG 单局的 `Match.red_team_name/blue_team_name/win_team_name/team_name_provenance`、`Team.team_name` 和 `Player.team_name`。不重放指标、昵称、头像、日期、来源状态、名单或任务，不删除任何行，也不提供新名称参数。赛程标签来自实际归档的同 BO、双方相同来源 ID，不据此推断俱乐部沿革、转会或正式历史名称。

默认只读审计，必须给出数据库、原件、报告目录和单局范围：

```powershell
.venv\Scripts\python.exe -X utf8 -m scripts.repair_team_names --database .\data\lol-data.db --raw-dir .\data\raw --reports-dir .\data\reports --result-ids 66845 --dry-run
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
