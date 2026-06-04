"""otology_skill 工具实现包。

作用：
- 收纳 workspace-local tools 的具体实现逻辑。
- `tools/` 目录只放 LangChain BaseTool 包装器；本包负责真正的解析、生成、合并、渲染、验证和路径处理。

主要输入：
- 各工具实现函数接收来自对应 tool wrapper 的参数。

主要输出：
- 各工具实现函数返回结构化 dict 或 JSON 字符串，供 agent 工具调用链消费。
"""
