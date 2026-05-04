#!/usr/bin/env node
/**
 * 思源笔记导入工具 v2.0
 *
 * 功能:
 *   - 支持所有思源笔记内容块格式（段落、标题、代码块、数学公式、表格、列表、引用、任务列表等）
 *   - 内置文本处理管道（LaTeX转换、标点符号转换、空白清理、自动链接等）
 *   - 多用户 API 配置
 *
 * 用法:
 *   node import.js file <文件路径>              导入单个文件
 *   node import.js dir <目录路径>               递归导入目录下所有文件
 *   node import.js text <标题> <内容>           导入纯文本为新文档
 *   node import.js batch <json文件>             批量导入（JSON定义多个文档）
 *   node import.js notebooks                   列出所有笔记本
 *   node import.js process <文件路径>           仅执行文本处理，输出结果不导入
 *   node import.js --user <用户名>              指定用户
 *   node import.js --notebook <笔记本ID>        指定目标笔记本
 *   node import.js --path <路径>                指定导入路径
 *   node import.js --no-process                 跳过文本处理
 *   node import.js --pipeline <名称>            使用指定处理管道
 */

const fs = require("fs");
const path = require("path");
const { fixGitBashPath, parseArgs: baseParseArgs } = require("./utils");
const http = require("http");
const https = require("https");

// ═══════════════════════════════════════════════════════════════════════════════
// 配置加载
// ═══════════════════════════════════════════════════════════════════════════════

const CONFIG_PATH = path.join(__dirname, "config.json");

function loadConfig() {
  if (!fs.existsSync(CONFIG_PATH)) {
    console.error(`错误: 找不到配置文件 ${CONFIG_PATH}`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"));
}

function getUser(config, userName) {
  const name = userName || config.defaultUser;
  if (!name || !config.users[name]) {
    const available = Object.keys(config.users).join(", ");
    console.error(`错误: 用户 "${name}" 不存在。可用用户: ${available}`);
    process.exit(1);
  }
  return { name, ...config.users[name] };
}

// ═══════════════════════════════════════════════════════════════════════════════
// HTTP 请求
// ═══════════════════════════════════════════════════════════════════════════════

function request(endpoint, token, apiPath, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(apiPath, endpoint);
    const isHttps = url.protocol === "https:";
    const transport = isHttps ? https : http;
    const payload = JSON.stringify(body || {});
    const options = {
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Token ${token}`,
        "Content-Length": Buffer.byteLength(payload),
      },
    };
    const req = transport.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try {
          const json = JSON.parse(data);
          if (json.code !== 0) {
            reject(new Error(`API 错误 [${json.code}]: ${json.msg}`));
          } else {
            resolve(json.data);
          }
        } catch (e) {
          reject(new Error(`解析响应失败: ${data.substring(0, 200)}`));
        }
      });
    });
    req.on("error", reject);
    req.setTimeout(60000, () => { req.destroy(); reject(new Error("请求超时")); });
    req.write(payload);
    req.end();
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// SiYuan API 客户端
// ═══════════════════════════════════════════════════════════════════════════════

class SiYuanClient {
  constructor(endpoint, token) {
    this.endpoint = endpoint;
    this.token = token;
  }

  async call(api, body) { return request(this.endpoint, this.token, api, body); }

  // 笔记本
  async listNotebooks() {
    const data = await this.call("/api/notebook/lsNotebooks");
    return data.notebooks.filter((nb) => !nb.closed);
  }
  async createNotebook(name) { return this.call("/api/notebook/createNotebook", { name }); }
  async openNotebook(id) { return this.call("/api/notebook/openNotebook", { notebook: id }); }
  async closeNotebook(id) { return this.call("/api/notebook/closeNotebook", { notebook: id }); }

  // 文档
  async createDocWithMd(notebook, docPath, markdown) {
    return this.call("/api/filetree/createDocWithMd", { notebook, path: docPath, markdown });
  }
  async renameDocByID(id, title) { return this.call("/api/filetree/renameDocByID", { id, title }); }
  async removeDocByID(id) { return this.call("/api/filetree/removeDocByID", { id }); }
  async moveDocsByID(fromIDs, toID) { return this.call("/api/filetree/moveDocsByID", { fromIDs, toID }); }
  async getHPathByID(id) { return this.call("/api/filetree/getHPathByID", { id }); }
  async getPathByID(id) { return this.call("/api/filetree/getPathByID", { id }); }

  // 块操作
  async insertBlock(dataType, data, parentID, previousID, nextID) {
    return this.call("/api/block/insertBlock", {
      dataType, data,
      parentID: parentID || "", previousID: previousID || "", nextID: nextID || "",
    });
  }
  async prependBlock(dataType, data, parentID) {
    return this.call("/api/block/prependBlock", { dataType, data, parentID });
  }
  async appendBlock(dataType, data, parentID) {
    return this.call("/api/block/appendBlock", { dataType, data, parentID });
  }
  async updateBlock(dataType, data, id) {
    return this.call("/api/block/updateBlock", { dataType, data, id });
  }
  async deleteBlock(id) { return this.call("/api/block/deleteBlock", { id }); }
  async moveBlock(id, previousID, parentID) {
    return this.call("/api/block/moveBlock", { id, previousID: previousID || "", parentID: parentID || "" });
  }
  async getBlockKramdown(id) { return this.call("/api/block/getBlockKramdown", { id }); }
  async getChildBlocks(id) { return this.call("/api/block/getChildBlocks", { id }); }

  // 属性
  async setBlockAttrs(id, attrs) { return this.call("/api/attr/setBlockAttrs", { id, attrs }); }
  async getBlockAttrs(id) { return this.call("/api/attr/getBlockAttrs", { id }); }

  // SQL
  async query(sql) { return this.call("/api/query/sql", { stmt: sql }); }

  // 文件
  async uploadAsset(filePath, assetsDirPath) {
    return new Promise((resolve, reject) => {
      const url = new URL("/api/asset/upload", this.endpoint);
      const isHttps = url.protocol === "https:";
      const transport = isHttps ? https : http;
      const boundary = "----SiYuanImport" + Date.now();
      const fileName = path.basename(filePath);
      const fileData = fs.readFileSync(filePath);
      const parts = [];
      parts.push(
        `--${boundary}\r\nContent-Disposition: form-data; name="assetsDirPath"\r\n\r\n${assetsDirPath || "/assets/"}`
      );
      parts.push(
        `--${boundary}\r\nContent-Disposition: form-data; name="file[]"; filename="${fileName}"\r\nContent-Type: application/octet-stream\r\n\r\n`
      );
      const pre = Buffer.from(parts.join("\r\n") + "\r\n");
      const suf = Buffer.from(`\r\n--${boundary}--\r\n`);
      const body = Buffer.concat([pre, fileData, suf]);
      const options = {
        hostname: url.hostname, port: url.port || (isHttps ? 443 : 80),
        path: url.pathname, method: "POST",
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          Authorization: `Token ${this.token}`,
          "Content-Length": body.length,
        },
      };
      const req = transport.request(options, (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          try {
            const json = JSON.parse(data);
            json.code !== 0 ? reject(new Error(json.msg)) : resolve(json.data);
          } catch (e) { reject(new Error(`解析失败: ${data.substring(0, 200)}`)); }
        });
      });
      req.on("error", reject);
      req.write(body);
      req.end();
    });
  }

  // 系统
  async version() { return this.call("/api/system/version"); }
  async pushMsg(msg, timeout) { return this.call("/api/notification/pushMsg", { msg, timeout: timeout || 7000 }); }
  async pushErrMsg(msg, timeout) { return this.call("/api/notification/pushErrMsg", { msg, timeout: timeout || 7000 }); }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 文本处理引擎
// ═══════════════════════════════════════════════════════════════════════════════

class TextProcessor {
  constructor(config) {
    this.config = config.textProcess || {};
    this.rules = [];
    this._registerBuiltinRules();
  }

  // 注册内置处理规则
  _registerBuiltinRules() {
    // ── LaTeX 公式转换 ──
    this.addRule("latex_display", {
      name: "LaTeX 行间公式转换",
      category: "formula",
      description: "\\[...\\] 转换为 $$...$$",
      enabled: this.config.latexDisplay !== false,
      priority: 10,
      fn: (text) => text.replace(/\\\[(.*?)\\\]/gs, "\n$$$$$1$$$$\n"),
    });
    this.addRule("latex_inline", {
      name: "LaTeX 行内公式转换",
      category: "formula",
      description: "\\(...\\) 转换为 $...$",
      enabled: this.config.latexInline !== false,
      priority: 11,
      fn: (text) => text.replace(/\\\((.*?)\\\)/g, "$$$1$$"),
    });
    this.addRule("latex_display_to_inline", {
      name: "LaTeX 行间转行内",
      category: "formula",
      description: "$$...$$ 转换为 $...$（单行时）",
      enabled: this.config.latexDisplayToInline === true,
      priority: 12,
      fn: (text) => text.replace(/\$\$(.*?)\$\$/gs, (m, p1) => {
        return p1.includes("\n") ? m : `$${p1.trim()}$`;
      }),
    });

    // ── 空白与换行处理 ──
    this.addRule("remove_newlines", {
      name: "去除多余换行",
      category: "whitespace",
      description: "去除 PDF 复制的多余换行（仅合并段落内的换行，保留 Markdown 结构）",
      enabled: this.config.removeNewlines === true,
      priority: 20,
      fn: (text) => {
        const lines = text.split("\n");
        const result = [];
        let inCodeBlock = false;
        let inMathBlock = false;
        let paraBuffer = [];

        const flush = () => {
          if (paraBuffer.length > 0) {
            result.push(paraBuffer.join(" "));
            paraBuffer = [];
          }
        };

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith("```")) { flush(); inCodeBlock = !inCodeBlock; result.push(line); continue; }
          if (inCodeBlock) { result.push(line); continue; }
          if (trimmed.startsWith("$$")) { flush(); inMathBlock = !inMathBlock; result.push(line); continue; }
          if (inMathBlock) { result.push(line); continue; }
          // Markdown 结构行不合并
          if (!trimmed || /^#{1,6}\s/.test(trimmed) || /^[-*+]\s/.test(trimmed) || /^\d+\.\s/.test(trimmed)
            || /^>/.test(trimmed) || /^\|/.test(trimmed) || /^[-*_]{3,}\s*$/.test(trimmed)
            || /^```/.test(trimmed) || /^\$\$/.test(trimmed)) {
            flush();
            result.push(line);
          } else {
            paraBuffer.push(trimmed);
          }
        }
        flush();
        return result.join("\n");
      },
    });
    this.addRule("remove_spaces", {
      name: "去除多余空格",
      category: "whitespace",
      description: "去除中文间的多余空格（跳过代码块、行内代码，保留英文单词间空格）",
      enabled: this.config.removeSpaces === true,
      priority: 21,
      fn: (text) => {
        // 保护引用块语法
        if (text.match(/\(\([0-9]{14}-[a-zA-Z0-9]{7}\s+'[^']+'\)\)/)) return text;
        if (text.match(/<<\s*assets\/[^>]*\s+"[^"]*"\s*>>/)) return text;
        // 保护代码块和行内代码
        const placeholders = [];
        let safe = text;
        safe = safe.replace(/```[\s\S]*?```/g, (m) => { placeholders.push(m); return `\x00CB${placeholders.length - 1}\x00`; });
        safe = safe.replace(/`[^`]+`/g, (m) => { placeholders.push(m); return `\x00IC${placeholders.length - 1}\x00`; });
        // 中文字符间去空格
        safe = safe.replace(/([一-龥])\s+([一-龥])/g, "$1$2");
        // 中文与标点间去空格
        safe = safe.replace(/([一-龥])\s+([，。！？；：）】》」』"'、])/g, "$1$2");
        safe = safe.replace(/([（【《「『"'、])\s+([一-龥])/g, "$1$2");
        // 还原
        safe = safe.replace(/\x00(CB|IC)(\d+)\x00/g, (_, __, i) => placeholders[parseInt(i)]);
        return safe;
      },
    });
    this.addRule("remove_empty_lines", {
      name: "去除空行",
      category: "whitespace",
      description: "减少连续空行为一行，保留 Markdown 结构间的空行",
      enabled: this.config.removeEmptyLines === true,
      priority: 22,
      fn: (text) => {
        // 连续空行合并为一行，但不完全删除（保留结构分隔）
        return text.replace(/\n{3,}/g, "\n\n");
      },
    });
    this.addRule("add_empty_lines", {
      name: "添加空行",
      category: "whitespace",
      description: "在段落间添加空行，确保每段成为一个独立的块",
      enabled: this.config.addEmptyLines === true,
      priority: 23,
      fn: (text) => text.replace(/([^\n])\n([^\n])/g, "$1\n\n$2"),
    });
    this.addRule("normalize_newlines", {
      name: "规范化换行",
      category: "whitespace",
      description: "将 \\r\\n 统一为 \\n",
      enabled: this.config.normalizeNewlines !== false,
      priority: 2,
      fn: (text) => text.replace(/\r\n/g, "\n").replace(/\r/g, "\n"),
    });
    this.addRule("trim_trailing_spaces", {
      name: "去除行尾空格",
      category: "whitespace",
      description: "移除每行末尾的多余空格",
      enabled: this.config.trimTrailingSpaces !== false,
      priority: 3,
      fn: (text) => text.replace(/[ \t]+$/gm, ""),
    });

    // ── 标点符号转换 ──
    this.addRule("en_to_cn_punctuation", {
      name: "英文标点转中文标点",
      category: "punctuation",
      description: "将英文逗号、句号、分号等转换为中文标点（跳过代码块、行内代码、URL）",
      enabled: this.config.enToCnPunctuation === true,
      priority: 30,
      fn: (text) => {
        // 先保护代码块、行内代码和 URL，处理完再还原
        const placeholders = [];
        let safe = text;
        // 保护代码块
        safe = safe.replace(/```[\s\S]*?```/g, (m) => { placeholders.push(m); return `\x00CB${placeholders.length - 1}\x00`; });
        // 保护行内代码
        safe = safe.replace(/`[^`]+`/g, (m) => { placeholders.push(m); return `\x00IC${placeholders.length - 1}\x00`; });
        // 保护 URL
        safe = safe.replace(/https?:\/\/[^\s一-龥<>"'\])]+/g, (m) => { placeholders.push(m); return `\x00URL${placeholders.length - 1}\x00`; });
        // 保护 Markdown 链接的 URL 部分
        safe = safe.replace(/\]\(([^)]+)\)/g, (m, url) => { placeholders.push(url); return `](\x00URL${placeholders.length - 1}\x00)`; });
        // 执行标点转换
        let inSingle = false, inDouble = false;
        const map = { ",": "，", ";": "；", ":": "：", "!": "！", "?": "？", "(": "（", ")": "）" };
        safe = safe.replace(/['",;:!?()]/g, (ch) => {
          if (ch === "'") { inSingle = !inSingle; return inSingle ? "‘" : "’"; }
          if (ch === '"') { inDouble = !inDouble; return inDouble ? "“" : "”"; }
          return map[ch] || ch;
        }).replace(/(?<!\d)\.(?!\d)/g, "。");
        // 还原
        safe = safe.replace(/\x00(CB|IC|URL)(\d+)\x00/g, (_, __, i) => placeholders[parseInt(i)]);
        return safe;
      },
    });
    this.addRule("cn_to_en_punctuation", {
      name: "中文标点转英文标点",
      category: "punctuation",
      description: "将中文标点转换为英文标点",
      enabled: this.config.cnToEnPunctuation === true,
      priority: 31,
      fn: (text) => {
        const map = { "。": ".", "，": ",", "；": ";", "！": "!", "？": "?", "（": "(", "）": ")", "：": ":", "‘": "'", "’": "'", "“": '"', "”": '"', "【": "[", "】": "]", "｛": "{", "｝": "}" };
        // 保护代码块和行内代码
        const placeholders = [];
        let safe = text;
        safe = safe.replace(/```[\s\S]*?```/g, (m) => { placeholders.push(m); return `\x00CB${placeholders.length - 1}\x00`; });
        safe = safe.replace(/`[^`]+`/g, (m) => { placeholders.push(m); return `\x00IC${placeholders.length - 1}\x00`; });
        safe = safe.replace(/[。，；！？（）：""''【】｛｝]/g, (ch) => map[ch] || ch);
        safe = safe.replace(/\x00(CB|IC)(\d+)\x00/g, (_, __, i) => placeholders[parseInt(i)]);
        return safe;
      },
    });

    // ── 全角半角转换 ──
    this.addRule("fullwidth_to_halfwidth", {
      name: "全角转半角",
      category: "encoding",
      description: "将全角英文字母、数字、符号转换为半角",
      enabled: this.config.fullwidthToHalfwidth === true,
      priority: 40,
      fn: (text) => text.replace(/[ -​  　＀-￯]/g, (ch) => {
        const code = ch.charCodeAt(0);
        if (code >= 8192 && code <= 8203 || code === 8239 || code === 8287 || code === 12288) return " ";
        if (code >= 65281 && code <= 65374 || code >= 65296 && code <= 65305) return String.fromCharCode(code - 65248);
        return ch;
      }),
    });
    this.addRule("halfwidth_to_fullwidth", {
      name: "半角转全角",
      category: "encoding",
      description: "将半角英文字母、数字、符号转换为全角（保留小数点）",
      enabled: this.config.halfwidthToFullwidth === true,
      priority: 41,
      fn: (text) => {
        const convert = (ch) => {
          if (ch === " ") return "　";
          const code = ch.charCodeAt(0);
          if (code >= 65 && code <= 90 || code >= 97 && code <= 122 || code >= 48 && code <= 57) return ch;
          if (code >= 33 && code <= 126) return String.fromCharCode(code + 65248);
          return ch;
        };
        let result = "";
        for (let i = 0; i < text.length; i++) {
          const ch = text[i];
          if (ch === "." && i > 0 && i < text.length - 1 && /\d/.test(text[i - 1]) && /\d/.test(text[i + 1])) {
            result += ch;
          } else {
            result += convert(ch);
          }
        }
        return result;
      },
    });

    // ── 链接处理 ──
    this.addRule("auto_link", {
      name: "自动链接",
      category: "link",
      description: "将裸 URL 转换为 Markdown 链接",
      enabled: this.config.autoLink === true,
      priority: 50,
      fn: (text) => {
        return text.replace(/(?<![[\(\]])(https?:\/\/[^\s一-龥<>"'\]]+)(?![\]\)])/g, "[$1]($1)");
      },
    });
    this.addRule("remove_links", {
      name: "去除链接",
      category: "link",
      description: "去除 Markdown 链接格式，保留文本",
      enabled: this.config.removeLinks === true,
      priority: 51,
      fn: (text) => text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1"),
    });
    this.addRule("remove_html_links", {
      name: "去除 HTML 链接",
      category: "link",
      description: "去除 HTML 超链接标签，保留文本",
      enabled: this.config.removeLinks === true,
      priority: 52,
      fn: (text) => text.replace(/<a[^>]*>(.*?)<\/a>/gi, "$1"),
    });

    // ── 上标去除 ──
    this.addRule("remove_superscript", {
      name: "去除上标",
      category: "cleanup",
      description: "去除 HTML 上标标签和 Unicode 上标字符",
      enabled: this.config.removeSuperscript === true,
      priority: 60,
      fn: (text) => {
        text = text.replace(/<sup[^>]*>[\s\S]*?<\/sup>/gi, "");
        text = text.replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻ]/g, "");
        return text;
      },
    });

    // ── 特殊清理 ──
    this.addRule("remove_html_tags", {
      name: "去除 HTML 标签",
      category: "cleanup",
      description: "去除所有 HTML 标签（保留纯文本）",
      enabled: this.config.removeHtmlTags === true,
      priority: 70,
      fn: (text) => text.replace(/<[^>]+>/g, ""),
    });
    this.addRule("remove_markdown_images", {
      name: "去除 Markdown 图片",
      category: "cleanup",
      description: "去除 Markdown 图片语法",
      enabled: this.config.removeImages === true,
      priority: 71,
      fn: (text) => text.replace(/!\[([^\]]*)\]\([^)]+\)/g, ""),
    });
    this.addRule("normalize_dashes", {
      name: "规范化破折号",
      category: "cleanup",
      description: "将连续的 -- 或 --- 转换为标准破折号",
      enabled: this.config.normalizeDashes === true,
      priority: 72,
      fn: (text) => text.replace(/---/g, "—").replace(/--/g, "–"),
    });

    // ── 结构化处理 ──
    this.addRule("heading_level_adjust", {
      name: "标题层级调整",
      category: "structure",
      description: "将标题层级整体调整（如把 # 变为 ##）",
      enabled: typeof this.config.headingLevelShift === "number" && this.config.headingLevelShift !== 0,
      priority: 80,
      fn: (text) => {
        const shift = this.config.headingLevelShift || 0;
        return text.replace(/^(#{1,6})\s/gm, (_, hashes) => {
          const level = Math.max(1, Math.min(6, hashes.length + shift));
          return "#".repeat(level) + " ";
        });
      },
    });
    this.addRule("list_bullet_convert", {
      name: "列表符号转 Markdown",
      category: "structure",
      description: "将特殊列表符号（• ○ ▪ 等）转换为 Markdown 列表",
      enabled: this.config.listBulletConvert === true,
      priority: 81,
      fn: (text) => {
        return text.replace(/(^|\n)[•○▪▫◆◇►▻❖✦✴✿❀⚪■☐]\s*/g, "$1- ");
      },
    });
    this.addRule("checkbox_normalize", {
      name: "任务列表符号规范化",
      category: "structure",
      description: "将 ☑☐ 等符号规范化为 Markdown 任务列表",
      enabled: this.config.checkboxNormalize === true,
      priority: 82,
      fn: (text) => {
        text = text.replace(/^[☐]\s*/gm, "- [ ] ");
        text = text.replace(/^[☑✓✔]\s*/gm, "- [x] ");
        return text;
      },
    });
  }

  addRule(id, rule) {
    this.rules.push({ id, ...rule });
  }

  // 按优先级排序后执行所有启用的规则
  process(text, options = {}) {
    if (!text) return text;
    const enabledOnly = options.rules
      ? this.rules.filter((r) => options.rules.includes(r.id))
      : this.rules.filter((r) => r.enabled);
    const sorted = enabledOnly.sort((a, b) => a.priority - b.priority);
    let result = text;
    const applied = [];
    for (const rule of sorted) {
      const before = result;
      result = rule.fn(result);
      if (result !== before) applied.push(rule.name);
    }
    return { text: result, applied };
  }

  // 获取规则列表
  listRules() {
    return this.rules.map((r) => ({
      id: r.id, name: r.name, category: r.category,
      description: r.description, enabled: r.enabled, priority: r.priority,
    }));
  }

  // 切换规则启用状态
  toggleRule(id, enabled) {
    const rule = this.rules.find((r) => r.id === id);
    if (rule) rule.enabled = enabled;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Markdown 块类型解析器
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * 支持的思源笔记块类型:
 *
 * NodeDocument      - 文档块
 * NodeParagraph     - 段落块
 * NodeHeading       - 标题块 (h1-h6)
 * NodeCodeBlock     - 代码块
 * NodeMathBlock     - 数学公式块
 * NodeTable         - 表格块
 * NodeList          - 列表块 (有序/无序)
 * NodeListItem      - 列表项块
 * NodeBlockquote    - 引用块
 * NodeSuperBlock    - 超级块
 * NodeHorizontalRule- 水平分割线
 * NodeIFrame        - iframe
 * NodeWidget        - 挂件
 * NodeVideo         - 视频
 * NodeAudio         - 音频
 *
 * 内联标记:
 * **粗体**          - strong
 * *斜体*            - em / italic
 * ~~删除线~~        - s / del
 * `行内代码`        - code
 * $行内公式$        - inline math
 * [链接](url)       - a
 * ![图片](url)      - img
 * ==高亮==          - mark
 * ~下标~            - sub
 * ^上标^            - sup
 */

class MarkdownParser {
  /**
   * 解析 Markdown 文本，返回块类型统计
   */
  static analyze(markdown) {
    const stats = {
      total: 0,
      paragraphs: 0,
      headings: { h1: 0, h2: 0, h3: 0, h4: 0, h5: 0, h6: 0 },
      codeBlocks: 0,
      mathBlocks: 0,
      tables: 0,
      lists: { ordered: 0, unordered: 0, task: 0 },
      blockquotes: 0,
      horizontalRules: 0,
      images: 0,
      links: 0,
      inlineMath: 0,
      inlineCode: 0,
      bold: 0,
      italic: 0,
      strikethrough: 0,
      highlight: 0,
    };

    const lines = markdown.split("\n");
    let inCodeBlock = false;
    let inMathBlock = false;
    let inTable = false;
    let inBlockquote = false;

    for (const line of lines) {
      const trimmed = line.trim();

      // 代码块
      if (trimmed.startsWith("```")) {
        if (inCodeBlock) { inCodeBlock = false; stats.total++; }
        else { inCodeBlock = true; stats.codeBlocks++; }
        continue;
      }
      if (inCodeBlock) continue;

      // 数学公式块
      if (trimmed.startsWith("$$")) {
        if (inMathBlock) { inMathBlock = false; stats.total++; }
        else { inMathBlock = true; stats.mathBlocks++; }
        continue;
      }
      if (inMathBlock) continue;

      // 空行跳过
      if (!trimmed) { inTable = false; inBlockquote = false; continue; }

      // 水平分割线
      if (/^[-*_]{3,}\s*$/.test(trimmed)) { stats.horizontalRules++; stats.total++; continue; }

      // 标题
      const headingMatch = trimmed.match(/^(#{1,6})\s/);
      if (headingMatch) {
        const level = headingMatch[1].length;
        stats.headings[`h${level}`]++;
        stats.total++;
        continue;
      }

      // 表格
      if (trimmed.includes("|") && trimmed.startsWith("|")) {
        if (!inTable) { inTable = true; stats.tables++; stats.total++; }
        continue;
      }

      // 列表
      if (/^\d+\.\s/.test(trimmed)) { stats.lists.ordered++; stats.total++; }
      else if (/^[-*+]\s/.test(trimmed)) {
        if (/^[-*+]\s*\[[ xX]\]/.test(trimmed)) { stats.lists.task++; }
        else { stats.lists.unordered++; }
        stats.total++;
      }
      // 引用
      else if (trimmed.startsWith(">")) {
        if (!inBlockquote) { inBlockquote = true; stats.blockquotes++; stats.total++; }
      }
      // 段落
      else { stats.paragraphs++; stats.total++; }

      // 统计内联元素
      stats.images += (trimmed.match(/!\[[^\]]*\]\([^)]+\)/g) || []).length;
      stats.links += (trimmed.match(/(?<!!)\[[^\]]+\]\([^)]+\)/g) || []).length;
      stats.inlineMath += (trimmed.match(/\$[^$\n]+\$/g) || []).length;
      stats.inlineCode += (trimmed.match(/`[^`]+`/g) || []).length;
      stats.bold += (trimmed.match(/\*\*[^*]+\*\*/g) || []).length;
      stats.italic += (trimmed.match(/(?<!\*)\*(?!\*)[^*]+\*(?!\*)/g) || []).length;
      stats.strikethrough += (trimmed.match(/~~[^~]+~~/g) || []).length;
      stats.highlight += (trimmed.match(/==[^=]+==/g) || []).length;
    }

    return stats;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Git Bash 路径修复
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// 参数解析
// ═══════════════════════════════════════════════════════════════════════════════

function parseArgs(argv) {
  return baseParseArgs(argv, { "--analyze": true });
}

// ═══════════════════════════════════════════════════════════════════════════════
// 文件扫描
// ═══════════════════════════════════════════════════════════════════════════════

function scanFiles(dirPath, extensions) {
  const results = [];
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) results.push(...scanFiles(fullPath, extensions));
    else if (entry.isFile() && extensions.includes(path.extname(entry.name).toLowerCase())) results.push(fullPath);
  }
  return results;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 导入核心逻辑
// ═══════════════════════════════════════════════════════════════════════════════

function printBlockStats(stats) {
  console.log("\n  内容块分析:");
  console.log(`    段落: ${stats.paragraphs}  标题: ${Object.values(stats.headings).reduce((a, b) => a + b, 0)}  代码块: ${stats.codeBlocks}  数学块: ${stats.mathBlocks}`);
  console.log(`    表格: ${stats.tables}  列表: ${stats.lists.ordered + stats.lists.unordered + stats.lists.task}  引用: ${stats.blockquotes}  分割线: ${stats.horizontalRules}`);
  console.log(`    图片: ${stats.images}  链接: ${stats.links}  行内公式: ${stats.inlineMath}  行内代码: ${stats.inlineCode}`);
  console.log(`    粗体: ${stats.bold}  斜体: ${stats.italic}  删除线: ${stats.strikethrough}  高亮: ${stats.highlight}`);
  console.log(`    总块数: ${stats.total}`);
}

function applyProcessing(content, processor, args, config) {
  if (args.noProcess) return { text: content, applied: [] };
  const pipelineName = args.pipeline || config.import?.defaultPipeline;
  if (pipelineName && config.pipelines?.[pipelineName]) {
    const pipeline = config.pipelines[pipelineName];
    return processor.process(content, { rules: pipeline.rules });
  }
  return processor.process(content);
}

async function importFile(client, filePath, notebook, basePath, processor, args, config) {
  let content = fs.readFileSync(filePath, "utf-8");
  const fileName = path.basename(filePath, path.extname(filePath));
  const docPath = basePath ? `${basePath}/${fileName}` : `/${fileName}`;

  console.log(`\n  文件: ${filePath}`);
  console.log(`  目标: [${notebook}] ${docPath}`);

  if (args.analyze) {
    const stats = MarkdownParser.analyze(content);
    printBlockStats(stats);
  }

  const { text, applied } = applyProcessing(content, processor, args, config);
  if (applied.length > 0) console.log(`  处理: ${applied.join(", ")}`);

  const docId = await client.createDocWithMd(notebook, docPath, text);
  console.log(`  完成: 文档 ID = ${docId}`);
  return docId;
}

async function importDir(client, dirPath, notebook, basePath, processor, args, config) {
  const extensions = config.import?.supportedExtensions || [".md", ".txt", ".markdown"];
  const files = scanFiles(dirPath, extensions);

  if (files.length === 0) {
    console.log(`目录 ${dirPath} 下没有找到可导入的文件`);
    return [];
  }

  console.log(`找到 ${files.length} 个文件，开始导入...\n`);
  const results = [];

  for (const file of files) {
    try {
      const relPath = path.relative(dirPath, file);
      const dirPart = path.dirname(relPath);
      const fileName = path.basename(file, path.extname(file));
      let docPath;
      if (dirPart === ".") docPath = basePath ? `${basePath}/${fileName}` : `/${fileName}`;
      else {
        const sub = dirPart.replace(/\\/g, "/");
        docPath = basePath ? `${basePath}/${sub}/${fileName}` : `/${sub}/${fileName}`;
      }

      let content = fs.readFileSync(file, "utf-8");
      const { text, applied } = applyProcessing(content, processor, args, config);

      console.log(`  [${results.length + 1}/${files.length}] ${relPath}`);
      if (applied.length > 0) console.log(`    处理: ${applied.join(", ")}`);

      const docId = await client.createDocWithMd(notebook, docPath, text);
      console.log(`    ID: ${docId}`);
      results.push({ file: relPath, docId });
    } catch (e) {
      console.error(`    失败: ${e.message}`);
      results.push({ file: path.relative(dirPath, file), error: e.message });
    }
  }
  return results;
}

async function importText(client, title, markdown, notebook, basePath, processor, args, config) {
  const docPath = basePath ? `${basePath}/${title}` : `/${title}`;

  console.log(`\n  标题: "${title}"`);
  console.log(`  目标: [${notebook}] ${docPath}`);

  if (args.analyze) {
    const stats = MarkdownParser.analyze(markdown);
    printBlockStats(stats);
  }

  const { text, applied } = applyProcessing(markdown, processor, args, config);
  if (applied.length > 0) console.log(`  处理: ${applied.join(", ")}`);

  const docId = await client.createDocWithMd(notebook, docPath, text);
  console.log(`  完成: 文档 ID = ${docId}`);
  return docId;
}

async function importBatch(client, jsonPath, notebook, basePath, processor, args, config) {
  const batch = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
  const items = batch.documents || batch;
  if (!Array.isArray(items)) {
    console.error("错误: 批量 JSON 格式不正确，需要是数组或 { documents: [...] }");
    process.exit(1);
  }

  console.log(`批量导入: ${items.length} 个文档\n`);
  const results = [];

  for (const item of items) {
    try {
      const title = item.title || item.name || `文档_${results.length + 1}`;
      const content = item.content || item.markdown || "";
      const itemPath = item.path || "";
      const docPath = basePath
        ? `${basePath}/${itemPath}/${title}`.replace(/\/+/g, "/")
        : `/${itemPath}/${title}`.replace(/\/+/g, "/");

      const { text, applied } = applyProcessing(content, processor, args, config);
      console.log(`  [${results.length + 1}/${items.length}] ${title}`);
      if (applied.length > 0) console.log(`    处理: ${applied.join(", ")}`);

      const docId = await client.createDocWithMd(notebook, docPath, text);
      console.log(`    ID: ${docId}`);
      results.push({ title, docId });
    } catch (e) {
      console.error(`    失败: ${e.message}`);
      results.push({ title: item.title, error: e.message });
    }
  }
  return results;
}

async function listNotebooks(client) {
  const notebooks = await client.listNotebooks();
  console.log("笔记本列表:\n");
  for (const nb of notebooks) {
    console.log(`  ${nb.closed ? "[关闭]" : "[打开]"} ${nb.name}`);
    console.log(`    ID: ${nb.id}`);
    if (nb.icon) console.log(`    图标: ${nb.icon}`);
    console.log();
  }
  return notebooks;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 主流程
// ═══════════════════════════════════════════════════════════════════════════════

async function main() {
  const args = parseArgs(process.argv);
  const config = loadConfig();

  if (args.help || args._.length === 0) {
    console.log(`
思源笔记导入工具 v2.0

命令:
  node import.js file <文件路径>                导入单个文件
  node import.js dir <目录路径>                 递归导入目录下所有文件
  node import.js text <标题> <内容>             导入纯文本为新文档
  node import.js text <标题> --stdin            从 stdin 读取内容创建文档
  node import.js batch <json文件>               批量导入（JSON 定义多个文档）
  node import.js notebooks                     列出所有笔记本
  node import.js process <文件路径>             仅执行文本处理，输出到 stdout
  node import.js rules                         列出所有文本处理规则

选项:
  --user <用户名>       指定配置文件中的用户（默认: ${config.defaultUser}）
  --notebook <ID>       指定目标笔记本 ID
  --path <路径>         指定文档导入路径
  --pipeline <名称>     使用指定处理管道
  --no-process          跳过文本处理
  --analyze             显示内容块分析
  -h, --help            显示帮助信息

处理管道（可在 config.json 中配置）:
  pdf-clean      - PDF 复制文本清理
  web-paste      - 网页粘贴清理
  formula        - 仅公式转换
  full-clean     - 全面清理
  custom         - 自定义管道

示例:
  node import.js notebooks
  node import.js file README.md --notebook abc123 --analyze
  node import.js dir ./docs --path /项目文档 --pipeline pdf-clean
  node import.js text "会议记录" "讨论了..." --notebook abc123
  node import.js batch docs.json --notebook abc123
  cat paper.md | node import.js text "论文" --stdin --pipeline formula
  node import.js process input.md --pipeline web-paste
  node import.js rules
`);
    return;
  }

  const user = getUser(config, args.user);
  const client = new SiYuanClient(user.endpoint, user.token);
  const processor = new TextProcessor(config);
  const command = args._[0];
  let notebook = args.notebook || user.defaultNotebook;
  const basePath = args.path || config.import?.defaultPath || "";

  try {
    const version = await client.version();
    console.log(`已连接: ${user.name} (${user.endpoint}) - 思源 v${version}`);

    switch (command) {
      case "notebooks":
        await listNotebooks(client);
        break;

      case "rules": {
        const rules = processor.listRules();
        const categories = {};
        for (const r of rules) {
          (categories[r.category] = categories[r.category] || []).push(r);
        }
        console.log("\n文本处理规则:\n");
        for (const [cat, catRules] of Object.entries(categories)) {
          console.log(`  【${cat}】`);
          for (const r of catRules) {
            const status = r.enabled ? "  [x]" : "  [ ]";
            console.log(`    ${status} ${r.id.padEnd(28)} ${r.description}`);
          }
          console.log();
        }
        console.log("在 config.json 的 textProcess 中设置规则启用/禁用");
        break;
      }

      case "process": {
        const filePath = args._[1];
        if (!filePath) { console.error("错误: 请指定文件路径"); process.exit(1); }
        const absPath = path.resolve(filePath);
        if (!fs.existsSync(absPath)) { console.error(`错误: 文件不存在: ${absPath}`); process.exit(1); }
        const content = fs.readFileSync(absPath, "utf-8");
        if (args.analyze) {
          const stats = MarkdownParser.analyze(content);
          printBlockStats(stats);
        }
        const { text, applied } = applyProcessing(content, processor, args, config);
        if (applied.length > 0) console.error(`已应用: ${applied.join(", ")}\n`);
        process.stdout.write(text);
        break;
      }

      case "file": {
        const filePath = args._[1];
        if (!filePath) { console.error("错误: 请指定文件路径"); process.exit(1); }
        const absPath = path.resolve(filePath);
        if (!fs.existsSync(absPath)) { console.error(`错误: 文件不存在: ${absPath}`); process.exit(1); }
        if (!notebook) { console.error("错误: 未指定笔记本。使用 --notebook <ID> 或设置 defaultNotebook"); process.exit(1); }
        await importFile(client, absPath, notebook, basePath, processor, args, config);
        break;
      }

      case "dir": {
        const dirPath = args._[1];
        if (!dirPath) { console.error("错误: 请指定目录路径"); process.exit(1); }
        const absDir = path.resolve(dirPath);
        if (!fs.existsSync(absDir) || !fs.statSync(absDir).isDirectory()) { console.error(`错误: 目录不存在: ${absDir}`); process.exit(1); }
        if (!notebook) { console.error("错误: 未指定笔记本。使用 --notebook <ID> 或设置 defaultNotebook"); process.exit(1); }
        const results = await importDir(client, absDir, notebook, basePath, processor, args, config);
        const succ = results.filter((r) => r.docId).length;
        const fail = results.filter((r) => r.error).length;
        console.log(`\n导入完成: 成功 ${succ}, 失败 ${fail}`);
        break;
      }

      case "text": {
        const title = args._[1];
        if (!title) { console.error("错误: 请指定文档标题"); process.exit(1); }
        let content;
        if (args._.includes("--stdin")) content = fs.readFileSync(0, "utf-8");
        else content = args._.slice(2).join(" ");
        if (!content || content.trim() === "") { console.error("错误: 内容为空"); process.exit(1); }
        if (!notebook) { console.error("错误: 未指定笔记本。使用 --notebook <ID> 或设置 defaultNotebook"); process.exit(1); }
        await importText(client, title, content, notebook, basePath, processor, args, config);
        break;
      }

      case "batch": {
        const jsonPath = args._[1];
        if (!jsonPath) { console.error("错误: 请指定 JSON 文件路径"); process.exit(1); }
        const absJson = path.resolve(jsonPath);
        if (!fs.existsSync(absJson)) { console.error(`错误: 文件不存在: ${absJson}`); process.exit(1); }
        if (!notebook) { console.error("错误: 未指定笔记本。使用 --notebook <ID> 或设置 defaultNotebook"); process.exit(1); }
        const results = await importBatch(client, absJson, notebook, basePath, processor, args, config);
        const succ = results.filter((r) => r.docId).length;
        const fail = results.filter((r) => r.error).length;
        console.log(`\n批量导入完成: 成功 ${succ}, 失败 ${fail}`);
        break;
      }

      default:
        console.error(`未知命令: ${command}`);
        console.error("运行 node import.js --help 查看帮助");
        process.exit(1);
    }
  } catch (e) {
    console.error(`\n错误: ${e.message}`);
    if (e.message.includes("ECONNREFUSED")) console.error("提示: 请确保思源笔记已启动，且 API 地址正确");
    process.exit(1);
  }
}

module.exports = { SiYuanClient, TextProcessor, MarkdownParser, loadConfig, getUser };

if (require.main === module) main();
