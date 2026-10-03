# LOL Data

统一的英雄联盟赛事数据工作区：赛程发现、单局采集、历史 CSV 迁移、数据库、选手与战队分析、Vue 网站和每日更新。

本项目延续 [lol_data_web](https://github.com/Zhong-Ze-Wei/lol_data_web) 的提交历史。原先 `lol爬虫` 的采集和 `lol_data_show` 的雷达分析已纳入同一流程，目录可以命名为 `lol-data`。旧原始资料与 Notebook 保存在本机数据/研究目录，敏感配置、数据库和原始日志不上传 Git。

## 快速启动

需要 Python 3.12+、Node.js 22.12+。Windows PowerShell：

```powershell
git clone https://github.com/Zhong-Ze-Wei/lol_data_web.git lol-data
cd lol-data
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
npm --prefix frontend ci
npm run build
npm start
```

访问 <http://127.0.0.1:5100>。默认使用 `data/lol-data.db`，无需 MySQL 系统服务。后端通过 Waitress 提供前端与 API，开发时可另开 `npm run dev` 使用 Vite 热更新。

Linux 使用 `.venv/bin/python` 安装依赖；其余 npm 命令相同。

首次克隆不包含本机历史数据库，可采集公开单局作为开始：

```powershell
.venv/Scripts/python.exe -m scripts.pipeline backfill --start 66845 --end 66846 --max-requests 10 --max-seconds 120
```

## 每日流程

```text
ScoreGG 赛事列表 → 阶段/周赛程 → 系列赛 → 单局 resultID
  → 原始 JSON → 验证与规范化 → 原子幂等入库
  → 网页查询 / 英雄统计 / 同位置雷达 / 趋势与战队比较
```

```powershell
# 默认回看最近14天，补到延迟发布和更正结果
npm run sync

# 限制网络请求与运行时间
.venv/Scripts/python.exe -m scripts.pipeline daily --max-requests 400 --max-seconds 900

# 处理持久失败队列和待采的单局结果
.venv/Scripts/python.exe -m scripts.pipeline retry --max-requests 100 --max-seconds 300

# 明确的单局编号范围；不会遇到连续空ID就提前停止
.venv/Scripts/python.exe -m scripts.pipeline backfill --start 61779 --end 61789
```

官网有些比赛已有比分，但 `is_publist=0` 表示战报仍在更新。这类系列赛与尚未开赛的比赛保持 `pending`，由每天的 `daily` 读取最新发布标志再处理；`retry` 不盲目请求待发布系列的缺失缓存。来源确认战报已发布但请求失败时，才记录失败并返回非零。

Windows 每天香港时间08:00运行（需要用户登录、电脑开机联网）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-schedule.ps1 -At 08:00
Get-ScheduledTaskInfo -TaskName 'LOL Data Daily Sync'
```

任务先备份本地 SQLite（保留最近7份），然后采集；单实例锁避免重叠。任务状态从 `/api/sync/status` 查看，日志在 `logs/daily-YYYY-MM-DD.log`。如需云端全天运行，应把同一 CLI 部署到持久存储的服务器；GitHub CI负责构建测试，不假设临时runner能访问本机数据库。

## 历史资料迁移

将原有选手/队伍 CSV 放入 `data/raw/`，然后：

```powershell
 npm run import:legacy
```

迁移逐行识别无表头的23/26列格式、转换分秒拼接时长、按自然键去重，并报告冲突、非法字段、缺少双方或选手、未核验记录。`all.csv` 缺少可靠比赛ID，仅作原始档案。重复执行不会累加相同出场记录；文件校验值未变化时直接复用已有报告，`--force` 才重新解析。

分批在线核验旧数据，补齐来源字段；明确不属于 LOL 的旧衍生记录会移除，原件与审计保留：

```powershell
.venv/Scripts/python.exe -m scripts.pipeline verify-legacy --limit 20 --max-requests 70 --max-seconds 180
```

`data/legacy-manifest.json` 记录已归档资料的校验值；迁移与采集报告保存在 `data/reports/`，原始公开JSON保存在 `data/raw/scoregg/`。

### 数据口径

- `match_id` 是单局 `resultID`；系列赛的 `matchID` 保存为 `series_id`。
- 一局对应1条比赛、2条战队和10条选手出场记录；实体数量按名称去重统计。
- 在线采集按来源 `gameID=1` 验证LOL，中文队名同样可以合法。
- 旧CSV不保存游戏类型，使用 `source=legacy / verified=false` 标记，不宣称全部为官方LOL全量数据。
- `date_source=updated_at` 仅表示来源更新时间；赛程时间使用对应来源标记，不根据日期猜测赛区、赛季或版本。
- 百分比为0–100、时长为秒、缺失值为null。雷达在同位置、同日期区间、满足最低场次的选手之间计算百分位；承伤占比描述风格，不作为综合实力分。
- Spark旧实验使用赛后指标且没有可靠训练结果，只保留研究档案，不提供赛前预测服务。

## 网站与接口

首页提供统计、排行和可选AI查询；选手、比赛、战队和英雄均有列表/详情；分析页提供五位置雷达、月度趋势和战队比较。

| 接口 | 用途 |
|---|---|
| `/api/health` | 服务与数据库状态 |
| `/api/stats` | 比赛、不同选手、不同战队数量 |
| `/match/api/list`、`/match/api/<match_id>` | 比赛筛选与单局详情 |
| `/player/api/list`、`/player/api/<name>` | 选手档案与历史表现 |
| `/team/api/distinct`、`/team/api/<name>` | 战队档案与阵容 |
| `/hero/api/list`、`/hero/api/<name>` | 按实际选用记录聚合英雄 |
| `/api/analytics/players` | 同位置六轴与最低样本筛选 |
| `/player/api/<name>/analytics` | 月度趋势、常用英雄与雷达 |
| `/api/analytics/teams` | 战队对比与直接交手 |
| `/api/sync/status` | 最近运行、任务队列、数据范围、调度状态 |
| `POST /api/ai/query` | 自然语言→只读SQL→基于结果回答 |

列表支持 `page/per_page`，单页最多100条；详情统计覆盖全部已收录记录，明细分页。错误返回JSON，空列表为200，参数错误400，缺实体404。

AI通过 OpenAI 兼容接口调用，默认使用 AI Ping 的 `DeepSeek-V4.1-Flash`。在本机 `.env` 设置：

```dotenv
AI_API_KEY=填写自己的密钥
AI_BASE_URL=https://aiping.cn/api/v1
AI_MODEL=DeepSeek-V4.1-Flash
AI_MAX_TOKENS=2048
AI_TIMEOUT=45
```

配置后重启 `npm start`。调用地址为 `AI_BASE_URL/chat/completions`，密钥只在后端使用；`.env` 不提交 Git。接口按 [AI Ping 官方文档](https://aiping.cn/docs/API/text-models) 使用 Bearer 鉴权、非流式请求，并关闭思考输出以减少问答等待。

没有密钥时返回明确的未配置状态；不会生成模拟答案，也不会在数据查询失败时改用常识冒充数据库结果。SQL有单语句、只读、表范围、结果条数与SQLite执行时间约束。鉴权失败、限流、超时、空回复和截断回复均返回中文错误；不会自动重试付费请求。

MySQL可通过 `.env` 的 `DATABASE_URL=mysql+pymysql://...` 显式选择。请使用符合新模型的新库；原版数据库不会自动改表。旧模板、静态图片和迁移文件已保存在本机 `research/legacy/web-old/`，不用于新版本运行。

## 目录

```text
app/                 Flask模型、查询、分析、采集与AI
frontend/            Vue3 + Vite + ECharts
scripts/             统一CLI、每日任务、备份
tests/               临时数据库、公开小样本回归测试
data/raw/            原始CSV与来源JSON（本机）
data/processed/      旧SQL快照等资料（本机）
data/reports/        迁移/采集问题报告（本机）
data/backups/        SQLite备份（本机）
research/legacy/     旧Notebook档案（本机）
docs/                数据口径、整合与运行记录
```

## 开发与验证

```powershell
npm run build
npm test
.venv/Scripts/python.exe -m ruff check app scripts tests
```

测试不依赖真实MySQL、外部采集或付费AI。GitHub Actions在Windows和Linux执行同样构建与测试。Python与前端依赖分别锁定在 `requirements-lock.txt`、`frontend/package-lock.json`。

在 `feat/`、`fix/`、`refactor/` 或 `docs/` 分支开发，验证后原子提交，通过 `--no-ff` 合并到master并推送。
