# 队名来源与赛程原件绑定的 SQLite 迁移

`Match.team_name_provenance` 是一个可空 JSON 字段，专门保存队名的赛程与战报来源证据。旧记录迁移后为 SQL `NULL`，不会制造名称证据，也不会重命名旧记录。本脚本只添加这个列，不重建表、不删除或复制旧表，不修改任务状态或原件。

以下两步迁移必须先于部署包含新字段的模型：旧网站和采集进程可以继续读取原有列；如果先部署模型，新模型查询会引用尚未存在的列。完成两步迁移后再加载新模型。

默认只读检查，也可显式写 `--dry-run`：

```powershell
.venv\Scripts\python.exe -X utf8 -m scripts.migrate_team_name_provenance --database .\data\lol-data.db --dry-run
```

确认目标路径后实际迁移：

```powershell
.venv\Scripts\python.exe -X utf8 -m scripts.migrate_team_name_provenance --database .\data\lol-data.db --apply --wait-seconds 60
```

`--database` 必填，不读取 `.env` 或创建应用、数据库与 ORM 查询。仅支持已经存在且具有预期 `matches` 身份、来源和队名字段的 SQLite 文件；MySQL 需要单独制定迁移，不把 SQLite 的 SQL 用到其他数据库。

`--apply` 使用目标数据库所在目录的 `.sync.lock`，与同目录采集进程共用现有进程锁。默认不等待，锁被占用时退出码为 `3`，不备份、不执行 DDL，也不停止补采。可设置 `0–60` 秒的有限等待，超时仍返回 `3`。如果数据库不在项目标准 `data` 目录，需先确认该数据库的写入流程也使用其所在目录的同一把锁。

新增字段之前，以 SQLite 在线备份 API 保存一致快照到同目录下的 `backups`，文件名以 `schema-team-name-provenance-` 开头，包含数据库名称、UTC 时间与唯一标识，并检查完整性、输出备份路径和 SHA-256。该前缀不匹配日常备份的 `lol-data-*.db` 轮转范围，迁移回滚原件不会被每日保留数量限制删除。备份保留旧 schema 和全部数据；新增列在显式事务中执行，失败回滚，成功备份继续保留供核对和恢复。迁移脚本不删除之前的备份。

已存在可空 JSON 字段时返回 `already_current`，不新增备份或 DDL。同名字段为其他类型、非空、主键、生成列或具有非空默认值时明确失败，不把结构冲突当作成功。退出码 `0` 表示只读检查或迁移成功，`2` 表示结构、文件或 SQLite 操作失败。默认只读检查的 `needs_migration` 仅表示需要迁移，不能据此部署新模型。

回归使用临时旧 schema 和数据，验证原记录、外键和索引保留，备份可恢复并核对哈希，重复运行幂等，真实采集锁竞争不改目标，DDL 失败回滚及模型可空 JSON 往返。测试不操作生产数据库，不调用上游或 AI。

## 第二步：系列赛程行绑定具体原件版本

`HistorySeries.schedule_raw_file`（可空 `TEXT`）和 `schedule_raw_sha256`（可空 `VARCHAR(64)`）保存该系列赛程行对应的原件版本。阶段最新清单可能更正或省略旧系列；该行不能因此改为引用不包含它的新原件。原有 `HistorySeries.raw_file/raw_sha256` 继续表示单局清单的来源，不复用为赛程阶段证据。

在第一步之后、加载新模型之前，先只读检查，再执行第二个迁移：

```powershell
.venv\Scripts\python.exe -X utf8 -m scripts.migrate_schedule_archive --database .\data\lol-data.db --dry-run
.venv\Scripts\python.exe -X utf8 -m scripts.migrate_schedule_archive --database .\data\lol-data.db --apply --wait-seconds 60
```

第二个脚本同样不加载应用、`.env` 或 ORM，默认只读。它验证现有 `history_series` 实体表，以及 `series_id/tournament_id/stage_id/source_json` 的预期身份结构；只新增缺少的两列，不改旧赛程 `source_json`、清单原件路径、SHA、任务或数据。旧行两列保持 SQL `NULL`，迁移不猜测或回填来源绑定。已有一列时仅补另一列，已存在两列且类型、可空约束与默认值匹配时返回 `already_current`，不备份或执行 DDL；不匹配则明确失败。

第二步复用第一步的 `.sync.lock`、`0–60` 秒有限等待和 SQLite 在线备份。每次实际新增列前生成独立完整备份，输出路径、完整性核验结果所对应的 SHA-256；备份使用相同 `schema-team-name-provenance-` 前缀，仍不属于日常备份轮转范围。两个 `ALTER TABLE` 位于同一 `BEGIN IMMEDIATE` 事务，第二列或迁移后校验失败时全部回滚，保留迁移前备份。退出码与第一步相同：`0` 成功、`2` 文件或结构失败、`3` 采集锁被占用。第二步的备份包含第一步已完成的 schema；两步分别有可核对的回滚边界。

第二步的临时库回归验证旧赛程原行、单局清单字段、索引和外键保留，WAL 中已提交更正进入备份，部分已存在的列和值保留，重复迁移幂等，真实进程锁竞争不改目标，以及第二条 DDL 和最终校验失败均回滚新列。测试不操作生产库。
