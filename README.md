# WhatToWatch - 流媒体智能推荐助手

从豆瓣同步你的观影偏好，快速查看想看的电影和剧集在哪个平台可以观看。

## 功能

- **豆瓣数据同步** — 自动抓取「看过」「想看」列表（电影+电视剧）
- **偏好分析** — 统计你偏好的类型、导演、演员
- **想看清单** — 想看电影 / 想看剧集 分 Tab 展示
- **平台搜索** — 点击卡片详情，一键跳转到流媒体平台搜索
- **支持平台** — 腾讯视频、iQIYI、优酷、芒果TV、Netflix、Disney+、Max

## 快速开始

### 前置要求

- Python 3.10+（[下载](https://www.python.org/downloads/)，安装时勾选 Add to PATH）

### 使用

**Windows：** 双击 `start.bat`

**Mac/Linux：**
```bash
chmod +x start.sh
./start.sh
```

浏览器自动打开 `http://127.0.0.1:8000`，输入豆瓣用户 ID → 同步 → 选平台 → 查看想看清单

> 如果豆瓣要求登录，页面上有 Cookie 粘贴引导，按提示操作即可。

## 技术栈

- **后端**: Python / FastAPI / SQLAlchemy / SQLite
- **前端**: Vue 3 + TailwindCSS（CDN，无需构建）
- **数据源**: 豆瓣（自动破解反爬挑战）

## 项目结构

```
whattowatch/
├── start.bat              ← Windows 启动
├── start.sh               ← Mac/Linux 启动
├── run.py
├── requirements.txt
└── app/
    ├── main.py            # FastAPI 入口 + 图片代理
    ├── config.py           # 平台配置
    ├── database.py         # 数据模型
    ├── routers/
    │   ├── douban.py       # 同步 API
    │   └── recommend.py    # 想看清单 API
    ├── services/
    │   ├── douban_scraper.py  # 豆瓣爬虫
    │   └── recommender.py     # 偏好分析
    └── static/
        └── index.html      # 前端单页
```

---

## 更新日志

### v0.5.0 (2026-04-09)

- 简化为想看清单模式（电影/剧集分 Tab），去掉猜你喜欢和书籍
- 新增豆瓣 Cookie 登录支持（豆瓣限制 IP 时可用）
- Cookie 粘贴引导：豆瓣登录链接 + 分步说明（Windows/Mac）
- 后端图片代理（`/api/img`）绕过豆瓣 CDN 防盗链
- 新增 Mac/Linux 启动脚本 `start.sh`

### v0.4.0 (2026-04-09)

- 电影/剧集从豆瓣详情页自动区分
- 影视推荐按电影/剧集分区展示
- 去掉平台网页搜索（太慢），改为详情弹窗内平台搜索链接一键跳转
- 修复豆瓣图片防盗链

### v0.3.0 (2026-04-09)

- 破解豆瓣 SHA-512 反爬机制，详情页数据正常获取
- 电影详情弹窗（类型、导演、演员、平台、豆瓣链接）
- 并发抓取优化（5 并发 × 15 批次）

### v0.2.0 (2026-04-09)

- 移除 TMDB 依赖，零配置即用
- 修复进度条溢出 + 系统代理连接超时

### v0.1.0 (2026-04-09)

- 首次发布：豆瓣同步、偏好分析、跨平台推荐、暗色主题界面
