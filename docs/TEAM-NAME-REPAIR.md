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

6,713 局候选在新隔离 SQLite 中审计、实际应用和重复应用均通过：applied 6,713，blocked/failed 0；重复 changed/applied 0、noop 6,713，无新备份。独立逐字段比较整库，12,114,415 个受保护字段和 443,951 条记录身份保持一致；另有 161,104 项来源 ID/名称核对，使用 635 份赛程原件版本。受保护字段计数包含范围外的名称，所有非名称指标均不允许改变。未写生产库、未调用上游或模型。详情文件路径和实际字节 SHA 的 6,713 个完整配对另行核对，不能把计数自身当作独立证据。

香港时间 05:17:47，主库同一范围实际应用并通过独立核验。真实采集锁覆盖修复、修复后在线一致快照以及可变来源原件的 ID/SHA 核验；锁外只比较两个冻结数据库，后续采集不会混入验收。全库 12,140,286 个受保护字段、445,123 条记录身份、schema 和所有来源/任务字段不变，applied 6,713、blocked/failed 0。修复前完整备份 SHA 为 `f33255dac48edc9c674f59e92246634051318a77a438b07388487a2c2168e8c8`；备份使用独立名称前缀继续保留。

随后主库只读复查 changed 0、noop 6,713、blocked/failed 0。实际 `/match/34` 接口和页面显示 RNG/SKT，双方击杀 8/21、时长 1,812 秒与出场归属一致；1440px 桌面和 390px 手机没有文档横向溢出、NaN 或浏览器错误，此次页面验证零 AI 请求。

本机完整证明为 `artifacts/historical-team-names-global-isolated-v1-proof.json`、`artifacts/historical-team-names-global-production-v1-proof.json`，原始逐局计划、事务结果及只读复查分别保存在 `data/reports/global-team-names-v1/` 和 `data/reports/global-team-names-repeat-v1/`。这些本地数据、备份及报告不上传 Git。源码完整构建、680 个 Python 与 62 个前端测试、Ruff 和 diffcheck 通过；合并版本 `9ac8eed` 的 Windows/Ubuntu CI 均通过。该范围不能升级为全库已修复、官方历史队名或全历史已补齐。

## 明确备用 BO 的 70 局补充验收

旧范围中另有 4,031 局缺主块 BO。政策 v2 只在主块真正缺失时采用来源明确给出的 `max_beiguo.match_id`，冲突和非法值仍阻断；完整边界见 `BO-IDENTITY.md`。实际原件分为 3,953 局名称已一致、70 局存在名称差异、5 局双方或胜方身份冲突、3 局两块均无 BO。另 52 局缺持久赛程原行，单独保留。这些分类不是已完成应用的证明；旧记录没有详情历史 SHA 时，只能证明本次实际读取的详情字节，不能声称它从未变化。

70 局经过独立 ID 映射复核、新隔离库实际应用与重复应用验证。香港时间 06:12:59，正式库应用 70、blocked/failed 0；同一真实采集锁覆盖修复、修复后快照和独立来源核验。全库 12,505,249 个受保护字段、455,438 条记录身份、所有来源和采集任务字段不变；2,100 项独立来源/逐行归属核对使用 7 份绑定赛程版本，没有调用名称选择政策作为核验答案。

变化涉及 71 个颜色侧：SP→APK 1、AST→OG 9、EG→EF 4、DIG→CG 1、CEC→YC 56。胜方名称按原双方归属映射，成绩、选手昵称、日期和指标均未重放。修复前完整备份 SHA 为 `e42af92de596b50a18627b741f272e1f0d0b226b574186dcf1187dc8c2bd900d`。隔离库重复实际应用、主库重复只读检查均为 70 noop、零差异、无新备份。该入口本次零上游和 AI 请求。

本地证据分别保存在 `artifacts/bo-fallback-name-isolated-v2-proof.json`、`artifacts/bo-fallback-name-production-v2-proof.json`；逐局事务在 `data/reports/bo-fallback-team-names-v2/`。生产 `/match/19825` 的 HLE/APK、40:36 时长、16/10 击杀及选手归属经实际接口和 1440/390px 页面抽查，页面无文档溢出、NaN、浏览器错误或 AI 请求。此处的名称表示该局绑定赛程的来源标签，不构成全局俱乐部别名。

## 同名 3,953 局仅补证据

另一批明确同名的 3,953 局经过新副本审计、实际应用、独立原件核验和重复应用。香港时间 06:45:41 正式应用完成，applied 3,953、blocked/failed 0，唯一变化列为 `matches.team_name_provenance`；所有队名、胜方、指标、主键、schema、选手及来源/采集任务字段均保持一致。全库核对 462,073 条记录身份和 12,614,798 个受保护字段，再额外强制所有名称字段也不能改变。

正式执行在原采集锁内先对当前库做只读预检，确认每局计划仅涉及证据；同锁内完成原件重新核验、完整备份、实际应用、修复后在线快照和独立来源核验。独立核验使用 99 份绑定赛程版本、实际备用 BO 和双方 ID，未调用名称选择政策作为答案。释放锁后只比较两个冻结数据库，再对主库只读复查，3,953 局全部 noop；后台恢复第47批，执行器会话与进程保留。

备份 SHA 为 `77623299179ad77c359d9fe3f1e5eba8fe795dee25004aad1529664bf2222811`。本地证明为 `artifacts/bo-proof-only-isolated-v2-proof.json`、`artifacts/bo-proof-only-production-v2-proof.json`，完整来源配对另存 `artifacts/bo-proof-only-production-v2-sources.json`，逐局事务在 `data/reports/bo-proof-only-v2/`。本次零上游、AI 请求及原件写入；最早冻结记录没有详情历史 SHA 的限制继续保留，不能把本次字节核验宣称为原件从未变化。

52 局缺赛程绑定的只读审计实际核验 1,243 份现存原件，目标 14 个 BO 均没有唯一赛程原行，当前可离线恢复为 0。34 局已有明确赛事 ID（1009、1010、1011、1021），这4个目录仍 queued 且无阶段原件；另18局赛事归属缺失。保留已导入单局，等待后续真实目录提供绑定，不凭名称或日期补造归属；完整范围与 SHA 见本地 `artifacts/audit-missing-schedule-bindings-v2.json`。

## 明确主 BO 的 7,330 局仅补证据

固定旧范围中另有 7,330 局来源队名一致，但尚无持久来源证明。新副本的实际审计、应用、独立原件核验和重复应用均通过；香港时间 2026-10-04 07:26:21，正式库同范围 applied 7,330、blocked/failed 0。八表 467,957 条记录身份、schema 和 12,707,040 个受保护字段保持一致；唯一变化为这 7,330 行 `matches.team_name_provenance`，所有名称、数值、选手与来源/采集任务均未改变。

正式执行沿用真实采集锁，在同锁内完成当前计划只读预检、完整备份、逐局事务、修复后在线快照和独立原件核验；锁外只比较冻结数据库。独立来源核验 7,330 局、695 份绑定赛程版本，全部主 `max_mvp.match_id` 明确，备用块同 BO，双方 ID、胜方、实际字节 SHA 和唯一赛程原行一致，没有调用选择政策作为答案。释放锁后主库只读复查全部 noop；副本重复实际应用也全为 noop，数据库物理 SHA 不变且无新备份。

完整备份 SHA 为 `816e98390af89697c9390c122024dc08d36d606fcf384ede43372c24a4102282`。本地证明为 `artifacts/primary-proof-only-isolated-v2-proof.json`、`artifacts/primary-proof-only-production-v2-proof.json`，来源配对另存 `artifacts/primary-proof-only-production-v2-sources.json`。本次零上游、AI 请求及原件写入；最早记录缺详情历史 SHA，证明只绑定本次实际读取的字节，不能宣称来源历来未变。采集执行器会话与进程保留，解除锁后恢复第52批。

原固定 NULL 证据范围共 18,138 局，其中 18,066 局现已通过上述有限修复或补证据，仍有 72 局保留未确认：5 局明确双方或胜方冲突、另12局双方 ID 集合不一致、3局两块均缺 BO、52局缺赛程绑定。各集合实际互斥且并集覆盖剩余范围；最早另行修复的20局 QG 记录在该范围之外。12局新审计中BO和胜方均有效，但详情和赛程双方集合不同，不按同BO或单边ID猜另一队；证据为 `artifacts/audit-twelve-identity-conflicts-v2.json` 与 `artifacts/original-name-scope-resolution-v2.json`。这不是全库来源身份核验完成，也不表示全历史已经补齐。
