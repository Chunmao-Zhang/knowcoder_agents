# KnowCoder Agents

基于 LLM 的多业务智能体框架，通过统一的 `harness` 驱动不同 Agent 完成任务。每个业务独立放在 `workspaces/` 下，拥有自己的 prompt、skills、tools 和前端界面。

## 项目结构

```
.
├── harness.json              # 全局配置（模型、Agent 列表）
├── harness/                  # 统一运行框架
├── workspaces/
│   ├── otology_skill/        # Excel → 业务本体建模 Agent
│   ├── deepagents_kbqa_general/  # 通用图谱 KBQA Agent
│   └── deepagents_kbqa_freebase/ # Freebase 风格 KBQA Agent
├── data/                     # 数据目录
│   ├── otology_skill/raw/    # 原始 Excel 表
│   └── metaqa/               # MetaQA 数据集
└── test_models.py            # 模型连通性测试
```

## 环境准备

1. 安装依赖：

   ```
   pip install -r requirements.txt
   ```
2. 在 `harness.json` 的 `providers` 中配置 API Key（DeepSeek API Key 获取地址：https://platform.deepseek.com/api_keys）。

## 使用方式

### 命令行运行

```bash
# 使用默认 Agent（otology_skill）
PYTHONPATH=. python3 -m harness.run --message "你的任务"

# 指定 Agent
PYTHONPATH=. python3 -m harness.run --agent deepagents_kbqa_general --message "你的任务"

# 从文件读取任务
PYTHONPATH=. python3 -m harness.run --agent otology_skill --message-file task.txt

# 多轮对话（指定 thread ID）
PYTHONPATH=. python3 -m harness.run --agent otology_skill --thread-id my-session --message "继续上次任务"

# 详细输出模式
PYTHONPATH=. python3 -m harness.run -v --message "你的任务"
```

### 前端界面

**Excel To Ontology Agent**（端口 8091）：

```bash
PYTHONPATH=. python3 workspaces/otology_skill/frontend/app.py
```

打开 `http://127.0.0.1:8091`，可上传 Excel 工作簿、管理案例、进行本体建模对话。

**Code On Graph Agent**（端口 8093）：

```bash
PYTHONPATH=. python3 workspaces/deepagents_kbqa_general/frontend/app.py
```

打开 `http://127.0.0.1:8093`，可上传知识图谱三元组、选择图谱范围、进行 KBQA 对话。

## Agent 说明

| Agent ID                                               | 名称                     | 功能                                                             |
| ------------------------------------------------------ | ------------------------ | ---------------------------------------------------------------- |
| `otology_skill`                                      | Excel To Ontology Agent  | Excel 表结构 → Python dataclass → 业务本体重构 → 多域本体合并 |
| `deepagents_kbqa_general`                            | Code On Graph Agent      | 通用图谱 KBQA，支持上传三元组、向量检索、子图推理                |
| `deepagents_kbqa_freebase(暂时不用，未设计前端页面)` | DeepAgents KBQA Freebase | Freebase 风格 KBQA（单跳/多跳/零样本）                           |
