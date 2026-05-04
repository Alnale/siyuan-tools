/**
 * 公共工具函数
 */

/**
 * Git Bash 会将 /开头的参数 转换为 Windows 路径（如 /Claude Code → C:/Program Files/Git/Claude Code）
 * 此函数检测并还原被转换的路径
 */
function fixGitBashPath(p) {
  if (!p) return p;
  const m = p.match(/^[A-Z]:\/(?:Program Files\/Git|msys64|usr)\/(.+)/i);
  if (m) return "/" + m[1];
  return p;
}

/**
 * 解析命令行参数
 * @param {string[]} argv - process.argv
 * @param {Object} [extraFlags] - 额外的标志定义，格式: { "--flag": "camelCaseKey" | true }
 *   值为字符串时表示需要参数，值为 true 表示布尔标志
 * @returns {{ _: string[], [key: string]: any }}
 */
function parseArgs(argv, extraFlags = {}) {
  const args = { _: [] };
  let i = 2;
  while (i < argv.length) {
    const arg = argv[i];
    // 公共标志
    if (arg === "--user" && argv[i + 1]) { args.user = argv[++i]; }
    else if (arg === "--notebook" && argv[i + 1]) { args.notebook = argv[++i]; }
    else if (arg === "--path" && argv[i + 1]) { args.path = fixGitBashPath(argv[++i]); }
    else if (arg === "--pipeline" && argv[i + 1]) { args.pipeline = argv[++i]; }
    else if (arg === "--no-process") { args.noProcess = true; }
    else if (arg === "--help" || arg === "-h") { args.help = true; }
    // 额外标志
    else if (arg in extraFlags) {
      const key = extraFlags[arg];
      if (key === true) {
        const camelKey = arg.replace(/^--/, "").replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        args[camelKey] = true;
      } else if (argv[i + 1]) {
        args[key] = argv[++i];
      } else {
        args._.push(arg);
      }
    }
    else { args._.push(arg); }
    i++;
  }
  return args;
}

module.exports = { fixGitBashPath, parseArgs };
