#!/usr/bin/env node
/**
 * 思源笔记爬虫导入工具
 *
 * 支持网页抓取、RSS/Atom 订阅源、分页爬取，自动转换为 Markdown 并导入思源笔记
 *
 * 用法:
 *   node crawler.js url <URL>                  抓取单个网页并导入
 *   node crawler.js urls <json文件>             批量抓取多个 URL
 *   node crawler.js feed <RSS URL>             抓取 RSS/Atom 订阅源
 *   node crawler.js target <id>                执行指定抓取目标
 *   node crawler.js targets                    列出所有抓取目标
 *   node crawler.js run                        执行所有启用的目标
 *   node crawler.js extract <URL>              仅提取内容（不导入）
 *   node crawler.js schedule                   启动定时抓取守护进程
 */

const fs = require("fs");
const path = require("path");
const { loadConfig, getUser, SiYuanClient, TextProcessor } = require("./import");
const { parseArgs: baseParseArgs } = require("./utils");
const cheerio = require("cheerio");
const TurndownService = require("turndown");

// ═══════════════════════════════════════════════════════════════════════════════
// 配置加载
// ═══════════════════════════════════════════════════════════════════════════════

const TARGETS_PATH = path.join(__dirname, "crawl-targets.json");

function loadTargets() {
  if (!fs.existsSync(TARGETS_PATH)) return [];
  const data = JSON.parse(fs.readFileSync(TARGETS_PATH, "utf-8"));
  return data.targets || [];
}

function saveTargets(targets) {
  fs.writeFileSync(TARGETS_PATH, JSON.stringify({ targets }, null, 2), "utf-8");
}

// ═══════════════════════════════════════════════════════════════════════════════
// 限速请求器
// ═══════════════════════════════════════════════════════════════════════════════

class RateLimitedFetcher {
  constructor(options = {}) {
    this.delay = options.delay || 2000;
    this.maxConcurrent = options.maxConcurrent || 3;
    this.timeout = options.timeout || 30000;
    this.maxRetries = options.maxRetries || 3;
    this.retryDelay = options.retryDelay || 5000;
    this.userAgent = options.userAgent || "SiYuanCrawler/1.0";
    this.lastRequestTime = 0;
    this.activeRequests = 0;
    this.queue = [];
  }

  async fetch(url, options = {}) {
    await this._waitForSlot();
    await this._waitForDelay();

    let lastError;
    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      try {
        this.activeRequests++;
        this.lastRequestTime = Date.now();
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        const headers = {
          "User-Agent": this.userAgent,
          Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          ...options.headers,
        };
        if (options.cookies) headers["Cookie"] = options.cookies;

        const response = await fetch(url, { headers, signal: controller.signal, redirect: "follow" });
        clearTimeout(timeoutId);

        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

        const contentType = response.headers.get("content-type") || "";
        const body = await response.text();
        this.activeRequests--;
        this._processQueue();
        return { url, status: response.status, contentType, body };
      } catch (err) {
        this.activeRequests--;
        lastError = err;
        if (attempt < this.maxRetries) {
          console.log(`  重试 ${attempt}/${this.maxRetries}: ${url}`);
          await this._sleep(this.retryDelay * attempt);
        }
      }
    }
    this._processQueue();
    throw lastError;
  }

  async _waitForSlot() {
    if (this.activeRequests < this.maxConcurrent) return;
    return new Promise((resolve) => this.queue.push(resolve));
  }

  async _waitForDelay() {
    const elapsed = Date.now() - this.lastRequestTime;
    if (elapsed < this.delay) await this._sleep(this.delay - elapsed);
  }

  _processQueue() {
    if (this.queue.length > 0 && this.activeRequests < this.maxConcurrent) this.queue.shift()();
  }

  _sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
}

// ═══════════════════════════════════════════════════════════════════════════════
// HTML 内容提取器
// ═══════════════════════════════════════════════════════════════════════════════

class HtmlExtractor {
  constructor(htmlCleanup = {}) {
    this.removeSelectors = htmlCleanup.removeSelectors || [];
    this.removeTags = htmlCleanup.removeTags || ["script", "style", "noscript", "iframe"];
  }

  extract(html, selectors = {}, url = "") {
    const $ = cheerio.load(html);

    for (const tag of this.removeTags) $(tag).remove();

    const title = selectors.title
      ? $(selectors.title).first().text().trim()
      : $("title").text().trim() || $("h1").first().text().trim();

    let contentEl;
    if (selectors.content) {
      contentEl = $(selectors.content).first();
      // 选择器未匹配时，尝试拆分（如 "#main-content .entry-content" -> ".entry-content"）
      if (!contentEl.length && selectors.content.includes(" ")) {
        const parts = selectors.content.split(/\s+/);
        for (let i = parts.length - 1; i >= 0; i--) {
          contentEl = $(parts.slice(i).join(" ")).first();
          if (contentEl.length) break;
        }
      }
      if (!contentEl.length) contentEl = $("article").first();
    } else {
      contentEl = $("article").first() || $(".post-content").first() || $(".entry-content").first() || $("main").first() || $("body");
    }

    if (selectors.exclude) for (const ex of selectors.exclude) contentEl.find(ex).remove();
    for (const rs of this.removeSelectors) contentEl.find(rs).remove();

    // 相对 URL 转绝对路径
    contentEl.find("a[href]").each((_, el) => {
      const href = $(el).attr("href");
      if (href && !href.startsWith("http") && !href.startsWith("mailto:") && !href.startsWith("#")) {
        try { $(el).attr("href", new URL(href, url).href); } catch {}
      }
    });
    contentEl.find("img[src]").each((_, el) => {
      const src = $(el).attr("src");
      if (src && !src.startsWith("http") && !src.startsWith("data:")) {
        try { $(el).attr("src", new URL(src, url).href); } catch {}
      }
    });

    const contentHtml = contentEl.html() || "";

    const author = selectors.author
      ? $(selectors.author).first().text().trim()
      : $('meta[name="author"]').attr("content") || "";

    let date = "";
    if (selectors.date) {
      const dateEl = $(selectors.date).first();
      date = dateEl.attr("datetime") || dateEl.attr("content") || dateEl.text().trim();
    }
    if (!date) date = $('meta[property="article:published_time"]').attr("content") || $("time[datetime]").first().attr("datetime") || "";

    return { title, contentHtml, author, date, url };
  }

  extractLinks(html, listSelectors, baseUrl) {
    const $ = cheerio.load(html);
    const links = [];

    if (listSelectors.itemSelector) {
      $(listSelectors.itemSelector).each((_, item) => {
        const el = $(item);
        const linkEl = listSelectors.linkSelector ? el.find(listSelectors.linkSelector).first() : el.is("a") ? el : el.find("a").first();
        const href = linkEl.attr("href");
        const linkTitle = listSelectors.titleSelector ? el.find(listSelectors.titleSelector).first().text().trim() : linkEl.text().trim();
        if (href) {
          try { links.push({ url: new URL(href, baseUrl).href, title: linkTitle }); } catch {}
        }
      });
    }
    return links;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// HTML → Markdown 转换器
// ═══════════════════════════════════════════════════════════════════════════════

class MarkdownConverter {
  constructor(turndownOptions = {}) {
    this.turndown = new TurndownService({
      headingStyle: turndownOptions.headingStyle || "atx",
      codeBlockStyle: turndownOptions.codeBlockStyle || "fenced",
      bulletListMarker: turndownOptions.bulletListMarker || "-",
      emDelimiter: "*",
      strongDelimiter: "**",
      linkStyle: "inlined",
    });

    // 去空元素
    this.turndown.addRule("removeEmpty", {
      filter: (node) => node.textContent.trim() === "" && !["img", "br", "hr"].includes(node.nodeName.toLowerCase()),
      replacement: () => "",
    });

    // 懒加载图片
    this.turndown.addRule("lazyImages", {
      filter: "img",
      replacement: (content, node) => {
        const src = node.getAttribute("data-src") || node.getAttribute("data-original") || node.getAttribute("data-lazy-src") || node.getAttribute("src");
        const alt = node.getAttribute("alt") || "";
        if (!src || src.startsWith("data:")) return "";
        return `![${alt}](${src})`;
      },
    });

    // figure/figcaption
    this.turndown.addRule("figure", {
      filter: "figure",
      replacement: (content, node) => {
        const img = node.querySelector("img");
        const caption = node.querySelector("figcaption");
        if (!img) return content;
        const src = img.getAttribute("src") || "";
        const alt = caption ? caption.textContent.trim() : img.getAttribute("alt") || "";
        return `\n\n![${alt}](${src})\n\n`;
      },
    });
  }

  convert(html, metadata = {}) {
    let markdown = this.turndown.turndown(html);
    // 用引用块添加元数据（不用 --- frontmatter，避免被思源误解析为表格）
    const meta = [];
    if (metadata.author) meta.push(`作者: ${metadata.author}`);
    if (metadata.date) meta.push(`日期: ${metadata.date}`);
    if (metadata.url) meta.push(`来源: ${metadata.url}`);
    if (meta.length > 0) markdown = `> ${meta.join("\n> ")}\n\n${markdown}`;
    return markdown;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// RSS / Atom 解析器
// ═══════════════════════════════════════════════════════════════════════════════

class FeedParser {
  static parse(xml, feedUrl) {
    if (xml.includes("<feed") && xml.includes("<entry")) return FeedParser._parseAtom(xml, feedUrl);
    return FeedParser._parseRSS(xml, feedUrl);
  }

  static _parseRSS(xml, feedUrl) {
    const items = [];
    const itemRegex = /<item>([\s\S]*?)<\/item>/gi;
    let match;
    while ((match = itemRegex.exec(xml)) !== null) {
      const x = match[1];
      items.push({
        title: FeedParser._decode(FeedParser._tag(x, "title")),
        link: FeedParser._tag(x, "link") || feedUrl,
        content: FeedParser._tag(x, "content:encoded") || FeedParser._tag(x, "description") || "",
        date: FeedParser._tag(x, "pubDate") || FeedParser._tag(x, "dc:date") || "",
        author: FeedParser._decode(FeedParser._tag(x, "dc:creator") || FeedParser._tag(x, "author")),
      });
    }
    return items;
  }

  static _parseAtom(xml, feedUrl) {
    const items = [];
    const entryRegex = /<entry>([\s\S]*?)<\/entry>/gi;
    let match;
    while ((match = entryRegex.exec(xml)) !== null) {
      const x = match[1];
      let link = "";
      const lm = x.match(/<link[^>]*href="([^"]*)"[^>]*\/?>/i);
      if (lm) link = lm[1];
      if (!link) link = FeedParser._tag(x, "link");
      const authorMatch = x.match(/<author>\s*<name>(.*?)<\/name>/s);
      items.push({
        title: FeedParser._decode(FeedParser._tag(x, "title")),
        link: link || feedUrl,
        content: FeedParser._tag(x, "content") || FeedParser._tag(x, "summary") || "",
        date: FeedParser._tag(x, "published") || FeedParser._tag(x, "updated") || "",
        author: authorMatch ? FeedParser._decode(authorMatch[1]) : "",
      });
    }
    return items;
  }

  static _tag(xml, tagName) {
    const cdataRe = new RegExp(`<${tagName}[^>]*>\\s*<!\\[CDATA\\[([\\s\\S]*?)\\]\\]>\\s*</${tagName}>`, "i");
    const cm = xml.match(cdataRe);
    if (cm) return cm[1].trim();
    const re = new RegExp(`<${tagName}[^>]*>([\\s\\S]*?)</${tagName}>`, "i");
    const m = xml.match(re);
    return m ? m[1].trim() : "";
  }

  static _decode(str) {
    return str.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#039;/g, "'").replace(/&#x27;/g, "'").replace(/&#(\d+);/g, (_, c) => String.fromCharCode(parseInt(c)));
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 分页处理器
// ═══════════════════════════════════════════════════════════════════════════════

class PaginationHandler {
  constructor(fetcher, extractor) {
    this.fetcher = fetcher;
    this.extractor = extractor;
  }

  async resolveUrls(target) {
    const { pagination, request, listSelectors } = target;
    const allLinks = [];

    if (pagination.type === "url-template") {
      for (let page = pagination.startPage || 1; page <= pagination.maxPages; page++) {
        const url = request.baseUrl.replace(/\{page\}/g, page).replace(/\{offset\}/g, String((page - 1) * 20));
        try {
          const result = await this.fetcher.fetch(url, { headers: request.headers, cookies: request.cookies });
          if (pagination.stopCondition?.type === "empty-content") {
            const $ = cheerio.load(result.body);
            if ($(pagination.stopCondition.selector).length === 0) { console.log(`  第 ${page} 页无内容，停止`); break; }
          }
          if (listSelectors) {
            const links = this.extractor.extractLinks(result.body, listSelectors, url);
            allLinks.push(...links);
            console.log(`  第 ${page} 页: ${links.length} 个链接`);
          }
        } catch (err) { console.error(`  第 ${page} 页失败: ${err.message}`); if (pagination.stopCondition?.type === "error") break; }
      }
    } else if (pagination.type === "next-page") {
      let currentUrl = request.baseUrl || request.url;
      let pageCount = 0;
      while (currentUrl && pageCount < (pagination.maxPages || 50)) {
        pageCount++;
        try {
          const result = await this.fetcher.fetch(currentUrl, { headers: request.headers, cookies: request.cookies });
          if (listSelectors) {
            const links = this.extractor.extractLinks(result.body, listSelectors, currentUrl);
            allLinks.push(...links);
            console.log(`  第 ${pageCount} 页: ${links.length} 个链接`);
          }
          const $ = cheerio.load(result.body);
          const nextEl = $(pagination.nextSelector).first();
          const nextHref = nextEl.attr("href");
          if (nextHref) currentUrl = new URL(nextHref, currentUrl).href;
          else { console.log(`  未找到下一页，停止`); currentUrl = null; }
          if (pagination.stopCondition?.type === "no-next-link" && !nextHref) break;
        } catch (err) { console.error(`  第 ${pageCount} 页失败: ${err.message}`); break; }
      }
    }
    return allLinks;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 爬取管道编排器
// ═══════════════════════════════════════════════════════════════════════════════

class CrawlPipeline {
  constructor(config, client, processor) {
    this.config = config;
    this.client = client;
    this.processor = processor;
    const cc = config.crawler || {};
    this.fetcher = new RateLimitedFetcher({
      delay: cc.requestDelay || 2000, maxConcurrent: cc.maxConcurrent || 3,
      timeout: cc.timeout || 30000, maxRetries: cc.maxRetries || 3,
      retryDelay: cc.retryDelay || 5000, userAgent: cc.userAgent || "SiYuanCrawler/1.0",
    });
    this.extractor = new HtmlExtractor(cc.htmlCleanup);
    this.converter = new MarkdownConverter();
    this.pagination = new PaginationHandler(this.fetcher, this.extractor);
  }

  async crawlTarget(target) {
    const results = [];
    console.log(`\n[${target.id}] ${target.name} (${target.type})`);

    switch (target.type) {
      case "page": results.push(...await this._crawlPages(target, [target.request.url])); break;
      case "list": results.push(...await this._crawlPages(target, target.request.urls)); break;
      case "paginated":
        const links = await this.pagination.resolveUrls(target);
        console.log(`  共 ${links.length} 个链接`);
        results.push(...await this._crawlPages(target, links.map((l) => l.url)));
        break;
      case "rss": results.push(...await this._crawlFeed(target)); break;
    }
    return results;
  }

  async _crawlPages(target, urls) {
    const results = [];
    const notebook = target.notebook || this.config.crawler?.defaultNotebook;
    const basePath = target.path || this.config.crawler?.defaultPath || "/网页采集";

    for (let i = 0; i < urls.length; i++) {
      const url = urls[i];
      try {
        console.log(`  [${i + 1}/${urls.length}] ${url}`);
        const response = await this.fetcher.fetch(url, { headers: target.request?.headers, cookies: target.request?.cookies });
        const extracted = this.extractor.extract(response.body, target.selectors, url);
        const markdown = this.converter.convert(extracted.contentHtml, { title: extracted.title, author: extracted.author, date: extracted.date, url: extracted.url });
        const processed = this._applyProcessing(markdown, target);
        const safeTitle = this._sanitize(extracted.title || `网页_${i + 1}`);

        if (notebook) {
          if (await this._exists(notebook, basePath, safeTitle)) { console.log(`    跳过(已存在): ${safeTitle}`); results.push({ url, title: extracted.title, status: "skipped" }); continue; }
          const docId = await this.client.createDocWithMd(notebook, `${basePath}/${safeTitle}`, processed.text);
          console.log(`    导入: ${safeTitle} (ID: ${docId})`);
          results.push({ url, title: extracted.title, docId, status: "success" });
        } else {
          console.log(`    提取: ${safeTitle} (${processed.text.length} 字符)`);
          results.push({ url, title: extracted.title, markdown: processed.text, status: "extracted" });
        }
      } catch (err) { console.error(`    失败: ${err.message}`); results.push({ url, error: err.message, status: "error" }); }
    }
    return results;
  }

  async _crawlFeed(target) {
    const feedUrl = target.request.url;
    console.log(`  获取 RSS: ${feedUrl}`);
    const response = await this.fetcher.fetch(feedUrl, { headers: target.request.headers, cookies: target.request.cookies });
    let items = FeedParser.parse(response.body, feedUrl);

    const opts = target.rssOptions || {};
    if (opts.sinceDays) {
      const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - opts.sinceDays);
      items = items.filter((item) => { if (!item.date) return true; const d = new Date(item.date); return !isNaN(d.getTime()) && d >= cutoff; });
    }
    if (opts.maxItems) items = items.slice(0, opts.maxItems);
    console.log(`  共 ${items.length} 篇文章`);

    if (opts.fetchFullContent) {
      const fullResults = [];
      for (const item of items) {
        try {
          console.log(`  获取全文: ${item.title}`);
          const pageResp = await this.fetcher.fetch(item.link, { headers: target.request.headers });
          const contentSel = opts.contentSelector || target.selectors?.content || "article";
          const extracted = this.extractor.extract(pageResp.body, { content: contentSel, exclude: target.selectors?.exclude }, item.link);
          fullResults.push({ title: item.title || extracted.title, contentHtml: extracted.contentHtml, author: item.author || extracted.author, date: item.date || extracted.date, url: item.link });
        } catch (err) {
          console.error(`    获取全文失败: ${err.message}`);
          fullResults.push({ title: item.title, contentHtml: item.content, author: item.author, date: item.date, url: item.link });
        }
      }
      return this._importItems(target, fullResults);
    }
    return this._importItems(target, items.map((item) => ({ title: item.title, contentHtml: item.content, author: item.author, date: item.date, url: item.link })));
  }

  async _importItems(target, items) {
    const results = [];
    const notebook = target.notebook || this.config.crawler?.defaultNotebook;
    const basePath = target.path || this.config.crawler?.defaultPath || "/网页采集";

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      try {
        const markdown = this.converter.convert(item.contentHtml, { title: item.title, author: item.author, date: item.date, url: item.url });
        const processed = this._applyProcessing(markdown, target);
        const safeTitle = this._sanitize(item.title || `文章_${i + 1}`);

        if (notebook) {
          if (await this._exists(notebook, basePath, safeTitle)) { console.log(`    跳过(已存在): ${safeTitle}`); results.push({ title: item.title, status: "skipped" }); continue; }
          const docId = await this.client.createDocWithMd(notebook, `${basePath}/${safeTitle}`, processed.text);
          console.log(`    导入: ${safeTitle} (ID: ${docId})`);
          results.push({ title: item.title, docId, status: "success" });
        } else {
          console.log(`    提取: ${safeTitle} (${processed.text.length} 字符)`);
          results.push({ title: item.title, markdown: processed.text, status: "extracted" });
        }
      } catch (err) { console.error(`    失败: ${err.message}`); results.push({ title: item.title, error: err.message, status: "error" }); }
    }
    return results;
  }

  _applyProcessing(markdown, target) {
    if (this.config.crawler?.skipProcess || target.skipProcess) return { text: markdown, applied: [] };
    const pipelineName = target.pipeline || this.config.crawler?.defaultPipeline;
    if (pipelineName && this.config.pipelines?.[pipelineName]) return this.processor.process(markdown, { rules: this.config.pipelines[pipelineName].rules });
    return this.processor.process(markdown);
  }

  async _exists(notebook, basePath, title) {
    try {
      if (!/^[0-9a-f-]+$/.test(notebook)) return false;
      const safeTitle = title.replace(/\\/g, "\\\\").replace(/'/g, "''");
      const rows = await this.client.query(`SELECT * FROM blocks WHERE content = '${safeTitle}' AND type = 'd' AND path LIKE '/${notebook}/${safeTitle}%' LIMIT 1`);
      return rows && rows.length > 0;
    } catch { return false; }
  }

  _sanitize(title) {
    return title.replace(/[<>:"/\\|?*]/g, "_").replace(/\s+/g, " ").replace(/\.+$/g, "").trim().substring(0, 200);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 轻量 Cron 匹配器
// ═══════════════════════════════════════════════════════════════════════════════

class CronMatcher {
  static match(cronExpr, date) {
    const parts = cronExpr.split(/\s+/);
    if (parts.length !== 5) return false;
    const [min, hour, dom, month, dow] = parts;
    return CronMatcher._field(min, date.getMinutes()) && CronMatcher._field(hour, date.getHours()) && CronMatcher._field(dom, date.getDate()) && CronMatcher._field(month, date.getMonth() + 1) && CronMatcher._field(dow, date.getDay());
  }

  static _field(field, value) {
    if (field === "*") return true;
    if (field.includes(",")) return field.split(",").some((f) => CronMatcher._field(f.trim(), value));
    if (field.includes("-")) { const [lo, hi] = field.split("-").map(Number); return value >= lo && value <= hi; }
    if (field.includes("/")) { const [range, step] = field.split("/"); const s = parseInt(step); return range === "*" ? value % s === 0 : CronMatcher._field(range, value) && value % s === 0; }
    return parseInt(field) === value;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// CLI 参数解析
// ═══════════════════════════════════════════════════════════════════════════════

function parseArgs(argv) {
  return baseParseArgs(argv, {
    "--selector": "selector",
    "--title-selector": "titleSelector",
    "--output": "output",
    "--verbose": true,
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// 命令分发
// ═══════════════════════════════════════════════════════════════════════════════

async function main() {
  const args = parseArgs(process.argv);
  const config = loadConfig();

  if (args.help || args._.length === 0) {
    console.log(`
思源笔记爬虫导入工具 v1.0

命令:
  node crawler.js url <URL>                    抓取单个网页并导入
  node crawler.js urls <json文件>               批量抓取多个 URL
  node crawler.js feed <RSS URL>               抓取 RSS/Atom 订阅源
  node crawler.js target <id>                  执行指定抓取目标
  node crawler.js targets                      列出所有抓取目标
  node crawler.js run                          执行所有启用的目标
  node crawler.js extract <URL>                仅提取内容输出到 stdout
  node crawler.js schedule                     启动定时抓取守护进程

选项:
  --user <用户名>         指定配置用户（默认: ${config.defaultUser}）
  --notebook <ID>         覆盖目标笔记本
  --path <路径>           覆盖导入路径
  --pipeline <名称>       覆盖处理管道
  --selector <CSS>        覆盖内容选择器
  --title-selector <CSS>  覆盖标题选择器
  --output <文件>         输出到文件而非导入
  --no-process            跳过文本处理
  --verbose               详细输出
  -h, --help              显示帮助信息

示例:
  node crawler.js url "https://example.com/article" --selector "article"
  node crawler.js url "https://example.com" --notebook abc123 --path "/网页/技术"
  node crawler.js feed "https://example.com/feed.xml" --notebook abc123
  node crawler.js extract "https://example.com/article" --selector ".content"
  node crawler.js targets
  node crawler.js target blog
  node crawler.js run
  node crawler.js schedule
`);
    return;
  }

  const user = getUser(config, args.user);
  const client = new SiYuanClient(user.endpoint, user.token);
  const processor = new TextProcessor(config);
  const command = args._[0];

  try {
    const version = await client.version();
    console.log(`已连接: ${user.name} (${user.endpoint}) - 思源 v${version}`);

    switch (command) {
      case "url": {
        const url = args._[1];
        if (!url) { console.error("错误: 请指定 URL"); process.exit(1); }
        const target = {
          id: "ad-hoc", name: url, type: "page", enabled: true,
          notebook: args.notebook || config.crawler?.defaultNotebook || user.defaultNotebook,
          path: args.path || config.crawler?.defaultPath || "/网页采集",
          pipeline: args.pipeline || config.crawler?.defaultPipeline || "",
          request: { url },
          selectors: { title: args.titleSelector, content: args.selector },
          skipProcess: args.noProcess,
        };
        const pipeline = new CrawlPipeline(config, client, processor);
        const results = await pipeline.crawlTarget(target);
        const succ = results.filter((r) => r.status === "success").length;
        const fail = results.filter((r) => r.status === "error").length;
        console.log(`\n完成: 成功 ${succ}, 失败 ${fail}`);
        break;
      }

      case "urls": {
        const jsonPath = args._[1];
        if (!jsonPath) { console.error("错误: 请指定 JSON 文件"); process.exit(1); }
        const data = JSON.parse(fs.readFileSync(path.resolve(jsonPath), "utf-8"));
        const urls = Array.isArray(data) ? data : data.urls || [];
        if (urls.length === 0) { console.error("错误: JSON 中未找到 URL 列表"); process.exit(1); }
        const target = {
          id: "batch", name: `批量 (${urls.length} 个)`, type: "list", enabled: true,
          notebook: args.notebook || config.crawler?.defaultNotebook || user.defaultNotebook,
          path: args.path || config.crawler?.defaultPath || "/网页采集",
          pipeline: args.pipeline || config.crawler?.defaultPipeline || "",
          request: { urls: urls.map((u) => (typeof u === "string" ? u : u.url)) },
          selectors: { title: args.titleSelector, content: args.selector },
          skipProcess: args.noProcess,
        };
        const pipeline = new CrawlPipeline(config, client, processor);
        const results = await pipeline.crawlTarget(target);
        const succ = results.filter((r) => r.status === "success").length;
        const fail = results.filter((r) => r.status === "error").length;
        console.log(`\n批量完成: 成功 ${succ}, 失败 ${fail}`);
        break;
      }

      case "feed": {
        const feedUrl = args._[1];
        if (!feedUrl) { console.error("错误: 请指定 RSS URL"); process.exit(1); }
        const target = {
          id: "ad-hoc-rss", name: feedUrl, type: "rss", enabled: true,
          notebook: args.notebook || config.crawler?.defaultNotebook || user.defaultNotebook,
          path: args.path || config.crawler?.defaultPath || "/网页采集",
          pipeline: args.pipeline || config.crawler?.defaultPipeline || "",
          request: { url: feedUrl },
          rssOptions: { maxItems: 20, fetchFullContent: true, contentSelector: args.selector },
          selectors: { content: args.selector },
          skipProcess: args.noProcess,
        };
        const pipeline = new CrawlPipeline(config, client, processor);
        const results = await pipeline.crawlTarget(target);
        const succ = results.filter((r) => r.status === "success").length;
        const fail = results.filter((r) => r.status === "error").length;
        console.log(`\nRSS 完成: 成功 ${succ}, 失败 ${fail}`);
        break;
      }

      case "extract": {
        const url = args._[1];
        if (!url) { console.error("错误: 请指定 URL"); process.exit(1); }
        const fetcher = new RateLimitedFetcher(config.crawler || {});
        const extractor = new HtmlExtractor(config.crawler?.htmlCleanup);
        const converter = new MarkdownConverter();
        console.log(`\n  获取: ${url}`);
        const response = await fetcher.fetch(url);
        const selectors = { title: args.titleSelector, content: args.selector };
        const extracted = extractor.extract(response.body, selectors, url);
        const markdown = converter.convert(extracted.contentHtml, { title: extracted.title, author: extracted.author, date: extracted.date, url: extracted.url });
        const { text } = args.noProcess ? { text: markdown } : processor.process(markdown);
        if (args.output) { fs.writeFileSync(args.output, text, "utf-8"); console.log(`  已输出到: ${args.output}`); }
        else process.stdout.write(text);
        break;
      }

      case "targets": {
        const targets = loadTargets();
        if (targets.length === 0) { console.log("\n暂无抓取目标。请编辑 crawl-targets.json 添加目标。"); return; }
        console.log("\n抓取目标:\n");
        for (const t of targets) {
          const status = t.enabled ? "[启用]" : "[禁用]";
          const schedule = t.schedule?.enabled ? ` 定时: ${t.schedule.cron}` : "";
          console.log(`  ${status} ${t.id.padEnd(20)} ${t.type.padEnd(12)} ${t.name}${schedule}`);
          console.log(`       路径: ${t.path || "默认"}  管道: ${t.pipeline || "默认"}`);
          if (t.request?.url) console.log(`       URL: ${t.request.url}`);
          if (t.request?.urls) console.log(`       URLs: ${t.request.urls.length} 个`);
          if (t.request?.baseUrl) console.log(`       模板: ${t.request.baseUrl}`);
          console.log();
        }
        break;
      }

      case "target": {
        const targetId = args._[1];
        if (!targetId) { console.error("错误: 请指定目标 ID"); process.exit(1); }
        const targets = loadTargets();
        const target = targets.find((t) => t.id === targetId);
        if (!target) { console.error(`错误: 未找到目标 "${targetId}"`); process.exit(1); }
        if (args.notebook) target.notebook = args.notebook;
        if (args.path) target.path = args.path;
        if (args.pipeline) target.pipeline = args.pipeline;
        if (args.noProcess) target.skipProcess = true;
        const pipeline = new CrawlPipeline(config, client, processor);
        const results = await pipeline.crawlTarget(target);
        const succ = results.filter((r) => r.status === "success").length;
        const skip = results.filter((r) => r.status === "skipped").length;
        const fail = results.filter((r) => r.status === "error").length;
        console.log(`\n完成: 成功 ${succ}, 跳过 ${skip}, 失败 ${fail}`);
        break;
      }

      case "run": {
        const targets = loadTargets().filter((t) => t.enabled);
        if (targets.length === 0) { console.log("\n没有启用的目标"); return; }
        console.log(`\n执行 ${targets.length} 个启用的目标\n`);
        const pipeline = new CrawlPipeline(config, client, processor);
        let totalSucc = 0, totalFail = 0;
        for (const target of targets) {
          try {
            const results = await pipeline.crawlTarget(target);
            totalSucc += results.filter((r) => r.status === "success").length;
            totalFail += results.filter((r) => r.status === "error").length;
          } catch (err) { console.error(`  [${target.id}] 失败: ${err.message}`); totalFail++; }
        }
        console.log(`\n全部完成: 成功 ${totalSucc}, 失败 ${totalFail}`);
        break;
      }

      case "schedule": {
        const targets = loadTargets().filter((t) => t.enabled && t.schedule?.enabled);
        if (targets.length === 0) { console.log("\n没有启用的定时目标"); return; }
        console.log(`\n定时任务: ${targets.length} 个目标已注册，每分钟检查一次...\n`);
        const pipeline = new CrawlPipeline(config, client, processor);
        const history = {};
        setInterval(async () => {
          const now = new Date();
          for (const target of targets) {
            if (!CronMatcher.match(target.schedule.cron, now)) continue;
            const key = `${target.id}_${now.getFullYear()}${now.getMonth()}${now.getDate()}${now.getHours()}${now.getMinutes()}`;
            if (history[key]) continue;
            history[key] = true;
            console.log(`\n[${now.toISOString()}] 触发: ${target.id}`);
            try { await pipeline.crawlTarget(target); } catch (err) { console.error(`定时任务失败: ${err.message}`); }
          }
        }, 60000);
        // 保持进程运行
        process.on("SIGINT", () => { console.log("\n定时任务已停止"); process.exit(0); });
        break;
      }

      default:
        console.error(`未知命令: ${command}`);
        console.error("运行 node crawler.js --help 查看帮助");
        process.exit(1);
    }
  } catch (e) {
    console.error(`\n错误: ${e.message}`);
    if (e.message.includes("ECONNREFUSED")) console.error("提示: 请确保思源笔记已启动");
    process.exit(1);
  }
}

main();
