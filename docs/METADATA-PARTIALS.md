# 官网基础统计与完整战报

ScoreGG BO20839 的官网 metadata 实际列出了单局 35121，并给出了双方十位选手的公开来源 ID、昵称、头像、击杀、死亡、助攻和 MVP/背锅标志，以及双方经济、大龙、小龙等基础字段。其 CDN 单局详情当时仍为 HTTP404。基础统计是另一份真实来源，不能称作 CDN 完整详情恢复。

本功能只在详情入口真实 HTTP404 后，使用同一赛程已验证且不可覆盖归档的 metadata。它不增加 metadata 请求，不猜 resultID；清单恢复的请求、预算、身份核验和原始 CDN404 依据仍由 `RESULTLIST-FALLBACK.md` 描述的共享流程负责。非404、预算退出、身份矛盾或坏档案不转成基础统计成功。

## 保存与缺项

- `Match.source='scoregg_metadata'`，`verified=True` 表示 LOL、单局、BO、双方和已结束赛程身份已有来源依据；任务仍为 `source_incomplete`，不表示完整指标已记录。
- `Player.source_player_id` 保存规范化的公开正数字 ID 字符串，每局唯一。来源的 A/B 选手数组没有角色或红蓝方依据，`position=NULL`；不根据数组排列、英雄或昵称猜位置。
- 来源只给整数分钟29，缺少完整秒数，因此三表精确时长为 NULL。个人英雄名、等级、来源 KDA 比率、伤害、承伤、经济、补刀和分均指标没有原值，均为 NULL；不乘以分钟还原总量，不从英雄图片推 Riot 编号。
- 真实击杀、死亡、助攻可以参与场均和现有自定义汇总 KDA。未知位置不进入位置过滤，缺时长/总量不进入分均指标的有效样本数。
- 现有比赛两侧物理槽保存来源 A/B：`blue_team_name` 对应 A、`red_team_name` 对应 B。公开 API 与证据明确 `side_basis='metadata_team_a_b'`，页面显示“队伍A/队伍B”，这些槽不声明真实游戏颜色。完整 CDN 详情为 `scoregg_red_blue`。

队名证明明确记录 `source_kind='scoregg_metadata'`、`source_policy='metadata_snapshot_v1'` 和 BO 锚点 `metadata.data.matchID`，不伪造 `max_mvp`。实际 metadata 响应 SHA、验证记录、单局 canonical SHA 和唯一赛程原行的档案 SHA 均可定位。实际详情404响应另存新目录，原 metadata、赛程和404原件不覆盖；JSON投影及 canonical SHA 与响应应用体字节 SHA 分开。

## 重复与完整升级

同局 metadata 重放按来源 ID 更新原出场，五个 NULL 位置不会折成一个键或反复新增出场。刷新还要求每位已知来源选手保持原战队 ID，双方来源 A/B 整体换位允许。缺失、重复、错误单局/队伍 ID、坏整数或明确的个人/战队汇总矛盾会整局回滚，失败任务按既有流程记一次计数。

完整 CDN 详情之后必须明确提供与基础统计相同的十个来源 ID、同 BO 和可验证双方身份，并且每位选手仍属于原已知战队 ID，才能按 ID 原位更新选手主键，填入真实角色、颜色、精确时长和完整字段。真实红蓝色方及角色互换允许；同一选手 ID 移到另一战队、双方 ID 缺失或不一致则拒绝升级。角色互换先腾出旧角色键，不删除后重新制造选手出场。比赛及战队主键也保留；无法证明相同来源身份时保留已存基础记录并报告失败。已核验的 `scoregg` 详情拥有更高优先级，metadata 不反向降级或覆盖它。

已有来源 ID 的完整战报刷新如果缺少已知角色槽的 ID，会整局拒绝更新并保留原出场主键和身份，不按相同昵称猜补 ID。此前没有已知来源 ID 的详情仍兼容缺项。

历史 `source_incomplete` 沿用现有终态，不自动自旋请求。近期日更或显式重试可以尝试完整详情；缓存仅从已有真实来源恢复，不凭任务标签补 publication 状态。重试任务缺少原行时使用实际持久 Series 的原行/档案，并交叉任务已知 BO、赛事与日期；没有 Series 时才从本局已核验 metadata 证明恢复。旧来源 ID 为 NULL 的完整详情按原队伍/角色键兼容；有稳定 ID 后才能作为未知角色出场的升级键。首次核验旧 CSV 不把猜测身份或指标附着到新 ID。

## SQLite 部署顺序

迁移默认只读，显式目标，不加载 `.env` 或应用：

```powershell
python -m scripts.migrate_source_player_id --database "E:\project\data\lol-data.db"
python -m scripts.migrate_source_player_id --database "E:\project\data\lol-data.db" --apply --wait-seconds 60
```

取得同一 `.sync.lock` 后，先做 SQLite 在线完整备份并记录 SHA，再同一事务新增可空 `VARCHAR(100)` 和 `uq_player_match_source_player(match_id,source_player_id)` 唯一索引。旧 NULL 行、位置唯一约束、主键、外键及所有旧业务字段不改。备份名 `schema-source-player-id-*` 与日更轮转分离；正确已有列/索引重复调用不备份、不执行 DDL，冲突结构明确失败。

生产必须先迁移，再部署新模型/启动新应用和采集批次。`create_app` 对已有 SQLite players schema 在初始化时检查一次，缺列/索引给出显式迁移命令，不自动 ALTER 或申请采集锁。空新库按现有 `create_all` 建表。此迁移脚本只支持 SQLite；其它数据库需管理员事先创建同样的可空列和唯一索引，未做真实 MySQL 迁移验收。

## 验证边界

仓库 `scoregg_bo20839_metadata_stats.json` 是实际响应 SHA `3913e2c00d1758073352a591d49889a530372354d48343454cb44deb260389f6` 的有限字段投影，仅身份、清单和基础统计，未复制账号或任务字段；投影字节 SHA `955722931d4f58d5246a7ed28088457c9ec222218bc63a906e65cd61340041f7` 单独核验并固定 LF。

测试用临时 SQLite、模拟 HTTP 和真实字段投影覆盖同 ID 幂等、NULL位置/时长/有效样本、事务回滚和公开 API。将来完整 CDN 升级测试明确是合成角色/秒数字段，用于验证 ID/PK 合同，不声称35121已有完整详情，不是付费模型、真实生产恢复或全部历史完成证明。迁移另外覆盖 WAL在线备份、错误结构、真实临时锁争用、DDL失败回滚和旧字段不变。
