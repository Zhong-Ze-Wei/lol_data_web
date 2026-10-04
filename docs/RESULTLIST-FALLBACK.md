# 官网元数据补充单局清单

CDN `match/resultlist/{BO}.json` 的 HTTP404 不能证明官网没有这场比赛的单局编号。历史发现和日更在该入口真实返回404后，可读取官网 BO 页使用的同源元数据 POST。两次请求共享现有请求数、时间、最小间隔、429/5xx重试预算；不会另开无预算的请求，不自动重置已耗尽的历史任务。

官网 `global.js` 声明的请求为 `POST https://ho.scoregg.com/services/api_url.php`，表单包含 `api_path=/services/match/match_info_new.php`、`method=post`、`platform=web`、`api_version=9.9.9`、`language_id=1` 和来源给出的 `matchID`。POST 禁止重定向，不使用用户登录、密钥或浏览器 cookies。实际源验证证明 BO20839 该调用可以匿名返回清单；不推广为所有接口的匿名可用性结论。

只有明确结束、已发布且有真实赛程归档的双方系列进入备用请求。必须验证归档字节 SHA 和唯一完整原行，来源BO、赛事、双方正ID、原始 `start_time`、赛程墙钟日期均可交叉核对。响应须明确 LOL、同BO/赛事/时间/双方、结束状态、相同已知最终比分；单局ID必须正数且唯一，单局双方与胜负方身份一致。声明的 `result_count` 必须等于实际清单长度且不超过 `game_count`；赛程已知的正 `game_count` 仅与元数据BO格式相比较，不要求实际清单凑满BO最大局数，例如BO5打成3:0只需三局。最终比分尚未覆盖的部分清单保留可用ID，系列仍待发布；空清单且计数0同样待发布。声明有结果但清单空、错误身份、API失败或非法JSON保持失败和原退避，不能用HTTP200清除失败。

原CDN404响应与每次元数据响应存入全新的 `raw/history/resultlist-fallback/{BO}/{UUID}/`，使用独占文件创建，保留实际 `requests.Response.content` 字节及SHA。该字节是应用层响应内容，不声称网络wire原字节。证据JSON记录两种来源的URL/方法/HTTP状态、赛程原件引用、验证结果与单局ID；预算在备用请求前耗尽仍能定位原404。历史系列的 `raw_file/raw_sha256` 可以明确指向元数据原响应，报告另带 `resultlist_evidence.source=scoregg_match_metadata`；不会把该响应写进普通CDN清单路径并冒充CDN200。完整且仍符合当前赛程的已归档元数据可零HTTP复用；空/部分清单会继续刷新。坏SHA和缺少来源记录不能复用。

这一功能只恢复单局清单。后续仍用现有官方 `match/result/{resultID}.json` 取完整详情；404继续是单局失败，不把元数据基本统计转换成完整战报、猜位置、补秒数或制造分均指标。官网清单另声明未知详情路径时明确失败，当前不猜备用目录。`is_publist=0` 和进行中系列保持现有待发布逻辑，没有因本功能批量补问全部旧系列。

2026-10-04 根代理实际来源验证：BO20839（S12、FNC102 对 EDG1）元数据合法给出唯一 `resultID=35121`，但官网默认详情路径仍返回404，因此尚未完整恢复。BO27625（双方2090/2091）元数据声明 `game_count=2/result_count=2`，实际 `result_list=[]`，属于计数与清单矛盾，继续保留失败。仓库测试仅保存这两份响应的业务投影，不复制公共 `member/task` 等无关字段；完整原件分别冻结在 ignored artifacts。

- BO20839 完整响应SHA：`3913e2c00d1758073352a591d49889a530372354d48343454cb44deb260389f6`；投影fixture SHA：`2490286738f7b4095bf479eaa81c8764e68d27411993ac0d2c32c4daaceceeee`。
- BO27625 完整响应SHA：`10ae455b37de3334774875b3f445e13f8d70d747c201deb639fd2602484e4640`；投影fixture SHA：`0925b6b18c2a49ac148bca89e40ffcdc0f39e0d71c5f78b2ec18270174bd8f6e`。

测试使用隔离SQLite和模拟HTTP transport，覆盖两次请求预算/限速、错误身份和计数、退避/重试响应归档、来源归档校验、空/部分清单、缓存、日更共用入口，以及发现ID后详情404仍失败。测试没有发真实上游请求、调用模型或操作生产库。
