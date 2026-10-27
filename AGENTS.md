# 仓库协作规则

## 默认语言

- 本仓库的一方 Markdown 文档默认使用简体中文（`zh-CN`）。新增或修改 `README.md`、`SKILL.md`、`docs/**/*.md`、`references/**/*.md`、贡献与安全说明以及 GitHub Markdown 模板时，说明性文字应使用简体中文。
- 需要保留英文版本时，使用明确的英文路径，例如 `README.en.md` 或 `references/en/`；`README.md` 和未带语言后缀的 references 始终作为简体中文默认入口。
- 保持语言切换链接可用。兼容路径（例如 `README.zh-CN.md` 和 `references/zh-CN/`）不得在没有迁移方案时删除。

## 不翻译的内容

- 不翻译代码、命令、API 名称、配置键、环境变量、状态值、占位符、文件路径、URL 和程序输出。
- 修改 `SKILL.md` 时，保留 YAML frontmatter 的字段、字段顺序和现有值；仅将 Markdown 正文的说明性内容本地化。
- 不修改第三方许可证、依赖代码、生成物或与当前任务无关的外部材料。

## 验证要求

- 文档链接或语言入口变化后，更新并运行相关文档测试。
- 修改 Skill 后运行 Skill 结构验证、Python 语法检查和完整单元测试。
- 提交前检查差异，确保没有凭据、运行数据库、私有日志或客户产物。
