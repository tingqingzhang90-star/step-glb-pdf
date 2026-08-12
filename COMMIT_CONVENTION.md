# Git 提交规范

本项目统一使用 Conventional Commits 格式，描述使用中文。

## 格式

```
<type>(<scope>): <中文描述>
```

- `type` 必填，`scope` 可选但建议填写，描述简洁说明“做了什么/为什么”
- 一次提交只做一件事；同一功能的代码与文档可以合并在一次提交

## type 取值

| type | 用途 |
|------|------|
| feat | 新功能、新能力 |
| fix | 缺陷修复 |
| refactor | 重构（不改变行为） |
| chore | 杂项（脚本、工具、依赖等） |
| docs | 仅文档变更 |
| revert | 回滚提交 |

## scope 常用取值

| scope | 对应内容 |
|-------|----------|
| drawing | 工程图总体能力 |
| drawing_engine | 后端视图生成/HLR 投影 |
| drawing_template | 模板引擎、标注模板 |
| frontend | cad-viewer-app 前端 |
| viewer | 3D 查看器 |
| tools | tools/ 下调试与提取脚本 |
| extract_anchors | 锚点提取 |

## 示例（来自历史提交）

```
feat(drawing): 并行生成标准视图并整理自研工程图方案
fix(drawing_engine): 修复工程图离群长线 - HLR 剪影数值缺陷
chore(tools): 跟踪工程图视图调试脚本
fix(frontend): 缩略图改用img标签,v-html无法渲染base64图片
```

## 约定

- 每完成一项独立可验证的工作后及时提交，不积压改动
- 提交前确认 `git status`，按文件名添加，避免 `git add -A`
- 提交信息通过 HEREDOC 传递，保证多行/中文格式正确
