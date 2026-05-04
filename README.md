# 思源笔记工具集

这是一个完整的思源笔记辅助工具集合，包含文本处理插件、文件导入工具、网页爬虫和文档格式转换器。

## 目录

- [功能概述](#功能概述)
- [项目结构](#项目结构)
- [安装与配置](#安装与配置)
- [使用指南](#使用指南)
  - [文本处理插件](#文本处理插件)
  - [导入工具](#导入工具)
  - [爬虫工具](#爬虫工具)
  - [文档转换器](#文档转换器)

## 功能概述

### 📝 文本处理插件

思源笔记浏览器插件，提供：

- **自动粘贴处理**：LaTeX公式转换、Office列表适配、去除多余换行/空格/上标/链接等
- **块操作**：合并块、拆分块、列表符号转换等
- **选中文本处理**：格式调整、符号转换等
- **批量操作**：批量设置代码语言、图片宽度等

### 📥 导入工具

Node.js命令行工具，支持：

- 单个/批量Markdown文件导入
- 目录递归导入
- 纯文本导入
- JSON批量导入
- 内容块分析
- 文本处理管道

### 🕸️ 爬虫工具

Node.js网页爬取工具，支持：

- 单个/批量网页抓取
- RSS/Atom订阅源抓取
- 分页爬取
- 定时抓取（支持Cron表达式）
- 自动HTML转Markdown

### 📄 文档转换器

Python GUI应用，支持：

- DOC/DOCX → Markdown
- DOC/DOCX → PDF → Markdown
- PDF → Markdown
- 拖拽文件导入
- 实时预览
- 思源笔记集成

## 项目结构

```
siyuan-tools/
├── siyuan-plugin-text-process/  # 思源笔记文本处理插件
├── converter/                    # Python文档转换器（GUI）
│   ├── core/                    # 核心转换逻辑
│   ├── gui/                     # GUI界面组件
│   ├── main.py                  # 入口文件
│   └── requirements.txt         # Python依赖
├── import.js                    # Node.js导入工具
├── crawler.js                   # Node.js爬虫工具
├── utils.js                     # 工具函数
├── crawl-targets.json           # 爬虫目标配置
├── package.json                 # Node.js项目配置
└── README.md                    # 本文档
```

## 安装与配置

### 前置要求

- Node.js 16+
- Python 3.8+
- 思源笔记（用于API调用）
- Pandoc（用于文档转换，可选但推荐）
- Microsoft Word（用于DOC/DOCX转换，Windows）

### Node.js工具安装

```bash
npm install
```

### Python工具安装

```bash
cd converter
pip install -r requirements.txt
```

### 配置文件

创建 `config.json` 文件：

```json
{
  "defaultUser": "main",
  "users": {
    "main": {
      "name": "主要账户",
      "endpoint": "http://127.0.0.1:6806",
      "token": "你的API令牌",
      "defaultNotebook": "笔记本ID"
    }
  },
  "import": {
    "defaultPath": "/导入文档",
    "supportedExtensions": [".md", ".txt", ".markdown"]
  },
  "crawler": {
    "defaultNotebook": "笔记本ID",
    "defaultPath": "/网页采集",
    "requestDelay": 2000,
    "maxConcurrent": 3
  },
  "textProcess": {
    "latexDisplay": true,
    "latexInline": true,
    "removeNewlines": false,
    "removeSpaces": true,
    "enToCnPunctuation": false
  },
  "pipelines": {
    "pdf-clean": {
      "rules": ["normalizeNewlines", "trimTrailingSpaces", "removeNewlines", "removeEmptyLines"]
    },
    "web-paste": {
      "rules": ["normalizeNewlines", "trimTrailingSpaces", "removeSuperscript", "removeHtmlTags"]
    },
    "formula": {
      "rules": ["latexDisplay", "latexInline"]
    }
  }
}
```

### 获取思源笔记API令牌

1. 打开思源笔记
2. 进入设置 → 关于 → API Token
3. 生成并复制令牌

## 使用指南

### 文本处理插件

详见 [siyuan-plugin-text-process/README_zh_CN.md](./siyuan-plugin-text-process/README_zh_CN.md)

### 导入工具

```bash
# 查看帮助
node import.js --help

# 列出所有笔记本
node import.js notebooks

# 导入单个文件
node import.js file README.md --notebook <笔记本ID> --analyze

# 导入整个目录
node import.js dir ./docs --path /项目文档 --pipeline pdf-clean

# 导入纯文本
node import.js text "会议记录" "今天讨论了..." --notebook <笔记本ID>

# 从stdin读取
cat paper.md | node import.js text "论文" --stdin --pipeline formula

# 仅处理文本不导入
node import.js process input.md --pipeline web-paste

# 列出所有处理规则
node import.js rules
```

### 爬虫工具

```bash
# 查看帮助
node crawler.js --help

# 抓取单个网页
node crawler.js url "https://example.com/article" --selector "article"

# 抓取RSS源
node crawler.js feed "https://example.com/feed.xml" --notebook <笔记本ID>

# 仅提取内容不导入
node crawler.js extract "https://example.com/article" --selector ".content"

# 列出所有配置的抓取目标
node crawler.js targets

# 执行指定目标
node crawler.js target blog

# 执行所有启用的目标
node crawler.js run

# 启动定时抓取
node crawler.js schedule
```

#### 配置爬虫目标

编辑 `crawl-targets.json`：

```json
{
  "targets": [
    {
      "id": "blog",
      "name": "技术博客",
      "type": "rss",
      "enabled": true,
      "notebook": "笔记本ID",
      "path": "/博客文章",
      "pipeline": "web-paste",
      "request": {
        "url": "https://example.com/feed.xml"
      },
      "rssOptions": {
        "maxItems": 20,
        "fetchFullContent": true
      },
      "schedule": {
        "enabled": true,
        "cron": "0 */6 * * *"
      }
    }
  ]
}
```

### 文档转换器

```bash
cd converter
python main.py
```

#### 功能说明

- **拖拽区域**：将DOC/DOCX/PDF文件拖入窗口
- **预览面板**：实时显示转换后的Markdown
- **处理工具**：可对转换结果进行文本清理
- **导出**：导出到文件或直接导入思源笔记

#### 依赖检查

首次运行时会检查：
- Pandoc是否安装
- Microsoft Word COM是否可用（Windows）
- 必要的Python库是否安装

## 文本处理规则

导入工具和爬虫工具支持丰富的文本处理规则：

### 公式处理
- `latexDisplay` - LaTeX行间公式（\[...\]）转$$...$$
- `latexInline` - LaTeX行内公式（\(...\)）转$...$
- `latexDisplayToInline` - 单行行间公式转行内

### 空白处理
- `removeNewlines` - 去除多余换行
- `removeSpaces` - 去除中文间多余空格
- `removeEmptyLines` - 减少连续空行
- `addEmptyLines` - 添加段落空行
- `normalizeNewlines` - 统一换行符
- `trimTrailingSpaces` - 去除行尾空格

### 标点符号
- `enToCnPunctuation` - 英文标点转中文
- `cnToEnPunctuation` - 中文标点转英文

### 全角半角
- `fullwidthToHalfwidth` - 全角转半角
- `halfwidthToFullwidth` - 半角转全角

### 链接处理
- `autoLink` - 裸URL转Markdown链接
- `removeLinks` - 去除链接格式保留文本
- `removeHtmlLinks` - 去除HTML链接

### 清理
- `removeSuperscript` - 去除上标
- `removeHtmlTags` - 去除HTML标签
- `removeMarkdownImages` - 去除Markdown图片
- `normalizeDashes` - 规范化破折号

### 结构化
- `headingLevelAdjust` - 调整标题层级
- `listBulletConvert` - 列表符号转Markdown
- `checkboxNormalize` - 任务列表规范化

## 许可证

ISC License

## 致谢

- [siyuan-plugin-text-process](https://github.com/Achuan-2/siyuan-plugin-text-process) — 思源笔记文本处理插件，本项目的文本处理引擎基于此项目整合而来。
- 感谢所有为思源笔记生态做出贡献的开发者！
