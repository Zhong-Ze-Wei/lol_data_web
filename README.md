# LOL Data Site

一个用于爬取、分析并展示英雄联盟职业赛事数据的网站。

## 🔧 项目结构

```
lol_data_site/
│
├── app/                        # Flask 主程序目录
│   ├── __init__.py             # 初始化 Flask 应用
│   ├── routes/                 # 各路由模块
│   │   ├── match/              # 比赛相关路由
│   │   ├── player/             # 选手相关路由
│   │   ├── team/               # 战队相关路由
│   │   └── hero/               # 英雄相关路由
│   ├── models/                 # SQLAlchemy 模型定义
│   │   ├── match.py            # 比赛模型
│   │   ├── player.py           # 选手模型
│   │   └── team.py             # 战队模型
│   ├── services/               # 爬虫和业务逻辑模块
│   │   └── spider.py           # LOLSpider 代码放这
│   ├── templates/              # Jinja2 模板目录，也就是前端设计
│   │   └── ...                 # HTML 模板文件
│   ├── static/                 # CSS / JS / 图片
│   │   └── ...                 # 静态文件（样式、脚本等）
│   └── __init__.py             # 整个应用程序的初始化文件
│
├── scripts/                    # 数据导入、测试脚本
│   └── import_data.py          # 数据导入脚本
│
├── .env                        # 数据库和环境变量配置（自定义文件）
├── config.py                   # 配置项
├── run.py                      # Flask 启动文件
├── requirements.txt            # Python依赖包列表
└── README.md                   # 项目说明文件
```

## ✨ 功能说明

- **数据爬取**：爬取英雄联盟职业联赛比赛、选手、战队、英雄等信息。
- **数据存储**：使用 MySQL 数据库，并通过 SQLAlchemy 管理数据模型。
- **数据分析**：提供基础统计与可扩展的数据分析模块。
- **数据展示**：使用 Flask 提供 API 和前端网页，展示选手表现、战队对比等内容。

## 📊 数据模型

### Match（比赛）
- 比赛ID、日期、赛区、比赛时长
- 蓝方/红方战队、选手、英雄选择
- 比赛结果、经济差、击杀数等统计数据

### Player（选手）
- 选手ID、姓名、位置
- 所属战队、参与比赛场次
- KDA、击杀、死亡、助攻等个人数据

### Team（战队）
- 战队ID、名称、赛区
- 胜率、场次、选手阵容
- 经济、视野、团战等团队数据

## 🔌 API接口

### 比赛相关接口
- `GET /match/api/list`：获取比赛列表（支持分页和筛选）
- `GET /match/api/<match_id>`：获取特定比赛详情

### 选手相关接口
- `GET /player/api/list`：获取选手列表（支持分页和筛选）
- `GET /player/api/<player_name>`：获取特定选手详情和统计数据

### 战队相关接口
- `GET /team/api/distinct`：获取不重复的战队名称（支持分页和模糊搜索）
- `GET /team/api/<team_name>`：获取特定战队的统计信息及最近选手阵容

### 英雄相关接口
- `GET /hero/`：获取英雄列表（待开发）

---
## 🚀 快速开始

### 1️⃣ 克隆项目

```bash
git clone https://github.com/Zhong-Ze-Wei/lol_data_web.git
cd lol_data_site
```

### 2️⃣ 安装依赖
建议使用虚拟环境：
```bash
python -m venv venv
source venv/bin/activate  # Windows 用 venv\Scripts\activate
pip install -r requirements.txt
```

### 3️⃣ 配置环境变量
创建 .env 文件，并写入如下内容（根据你本地 MySQL 设置进行修改）：
```bash
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=yourpassword
DB_NAME=lol_data
```

### 4️⃣ 初始化数据库（如有）
```bash
python scripts/import_data.py
```
或使用 SQLAlchemy 自动建表逻辑。

### 5️⃣ 运行项目
```bash
python run.py

cd frontend
npm run serve
```
默认访问地址为：
```
http://127.0.0.1:5000
```

## 穿透部署方案
使用nginx
 ```
 cd /d E:\nginx\nginx-1.28.0
 start nginx
 ```
 使用ngrok
 ```
ngrok http 80
 ```
---
## ⚙️ 技术栈
- **后端框架**：Flask
- **数据库**：MySQL + SQLAlchemy
- **前端框架**：Vue.js + Element UI
- **前端模板**：Jinja2
- **数据采集**：requests + json + lxml + BeautifulSoup4
- **可视化**：ECharts / Chart.js

---

## 📌 TODO
- [ ] 增加数据可视化模块（选手雷达图、战队胜率图等）
- [ ] 丰富比赛分析逻辑（时长、击杀、经济对比等）
- [ ] 英雄与装备信息爬取
- [ ] 添加搜索、筛选和分页功能
- [ ] 管理后台功能（登录权限等）
- [ ] 优化数据爬取效率和稳定性
- [ ] 添加数据导出功能（CSV、Excel等）

## 🔄 更新日志
### v0.1.0 (2023-10-01)
- 初始版本发布
- 实现基本的数据采集和展示功能

---

## 🧑‍💻 作者
zhong-ze-wei

---

## 📄 License
### 本项目仅供学习与交流使用，如需商业用途请联系作者。
