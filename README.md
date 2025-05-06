# LOL Data Site

一个用于爬取、分析并展示英雄联盟职业赛事数据的网站。

## 🔧 项目结构

lol_data_site/
│
├── app/                        # Flask 主程序目录
│   ├── __init__.py             # 初始化 Flask 应用
│   ├── routes/                 # 各路由模块
│   │   ├── __init__.py
│   │   ├── match.py            # 比赛相关数据接口
│   │   └── analysis.py         # 分析结果展示接口
│   ├── models/                 # SQLAlchemy 模型定义
│   │   ├── __init__.py
│   │   └── player.py
│   ├── services/               # 爬虫和业务逻辑模块
│   │   ├── __init__.py
│   │   └── spider.py           # LOLSpider 代码放这
│   ├── templates/              # Jinja2 模板目录
│   │   └── index.html
│   └── static/                 # CSS / JS / 图片
│
├── scripts/                    # 一些数据导入、测试脚本
│   └── import_data.py
│
├── .env                        # 数据库和环境变量配置
├── config.py                   # 配置项（可区分 dev/prod）
├── run.py                      # Flask 启动文件
├── requirements.txt            # Python依赖包列表
└── README.md

## ✨ 功能说明

- **数据爬取**：爬取英雄联盟职业联赛比赛、选手、战队、英雄等信息。
- **数据存储**：使用 MySQL 数据库，并通过 SQLAlchemy 管理数据模型。
- **数据分析**：提供基础统计与可扩展的数据分析模块。
- **数据展示**：使用 Flask 提供 API 和前端网页，展示选手表现、战队对比等内容。
---
## 🚀 快速开始

### 1️⃣ 克隆项目

```bash
git clone https://github.com/yourusername/lol_data_site.git
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
```
默认访问地址为：
```
http://127.0.0.1:5000
```
---
## ⚙️ 技术栈
后端框架：Flask

数据库：MySQL + SQLAlchemy

前端模板：Jinja2

数据采集：requests + json + lxml

可视化建议：echarts / chart.js（可扩展）

---

## 📌 TODO
 增加数据可视化模块（选手雷达图、战队胜率图等）

 丰富比赛分析逻辑（时长、击杀、经济对比等）

 英雄与装备信息爬取

 添加搜索、筛选和分页功能

 管理后台功能（登录权限等）

---

# 🧑‍💻 作者
zhong-ze-wei

---

# 📄 License
### 本项目仅供学习与交流使用，如需商业用途请联系作者。