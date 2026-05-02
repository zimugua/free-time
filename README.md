# 🗓️ 活动规划 Agent

> 基于美团场景的本地短时活动规划智能体 —— 输入一句话，自动生成「活动 + 用餐 + 路程」的完整行程方案。

## ✨ 功能特性

- **自然语言理解**：直接说「周六下午带孩子出去玩，顺便吃晚饭」，Agent 自动解析场景、人数、时间
- **全流程自动化**：活动搜索 → 餐厅匹配 → 座位检查 → 时间排布 → 冲突检测 → 自动预订 → 行程生成，一气呵成
- **双模式降级**：LLM 不可用时自动切换规则引擎，服务不中断
- **多方案对比**：最多生成 3 个差异化方案，用户复选后一键预订
- **等待智能处理**：活动结束到用餐窗口之间有空档时，自动推荐游逛/购物等等待建议
- **流式行程文案**：LLM 实时流式输出行程描述，体验丝滑

## 🖥️ 界面预览

启动后访问 `http://localhost:7860`，Gradio Web UI 界面，交互全程中文。

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| UI 框架 | [Gradio](https://gradio.app/) ≥ 4.0 |
| LLM 接入 | OpenAI 兼容接口（DeepSeek / OpenAI / 通义 / 智谱 / Moonshot） |
| 配置管理 | PyYAML |
| 运行环境 | Python 3.9+ |

## 📁 项目结构

```
.
├── agent.py          # 核心 Agent 逻辑（九阶段 Pipeline）
├── app.py            # Gradio UI & 交互控制
├── llm.py            # LLM 封装（流式输出 + 规则降级）
├── main.py           # 启动入口
├── config.yaml       # LLM & 应用配置
├── data/             # Mock 数据（活动、餐厅）
├── tools/            # 工具集（搜索/路程/预订/用户/用餐）
├── prompts/          # LLM Prompt 模板
└── docs/             # 设计文档
```

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/your-username/activity-planner-agent.git
cd activity-planner-agent
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 LLM

编辑 `config.yaml`，填入你的 API Key：

```yaml
llm:
  provider: "deepseek"          # 可选: openai / deepseek / zhipu / qwen / moonshot
  api_key: "sk-your-api-key"   # 替换为你的 Key
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-chat"
```

> **不配置 LLM 也能跑**：Agent 会自动降级到规则模式，功能正常，只是行程文案为模板格式。

### 4. 启动

```bash
python main.py
```

浏览器访问 `http://localhost:7860` 即可使用。

## 💬 使用示例

在输入框中输入：

```
周六下午两点，我和朋友想去密室逃脱，之后吃顿火锅
```

Agent 将自动完成：

1. 解析意图：场景=朋友、活动=密室逃脱、时间=14:00、餐厅=火锅
2. 搜索匹配的密室和火锅餐厅
3. 检查座位，计算路程
4. 生成多个方案供你选择
5. 确认后自动预订，输出完整行程文案

## ⚙️ 配置说明

`config.yaml` 支持以下 LLM 服务商：

| 服务商 | provider 值 | 推荐模型 |
|--------|------------|---------|
| DeepSeek | `deepseek` | `deepseek-chat` |
| OpenAI | `openai` | `gpt-4o-mini` |
| 通义千问 | `qwen` | `qwen-turbo` |
| 智谱 AI | `zhipu` | `glm-4-flash` |
| Moonshot | `moonshot` | `moonshot-v1-8k` |

## 📐 架构说明

详见 [`docs/design.docx`](docs/design.docx)，涵盖：

- **Planning 策略**：双模式意图解析 + 九阶段流水线 + 时间计算规则
- **工具调用链路**：7 个工具的职责、输入输出与完整调用顺序
- **异常处理机制**：LLM 降级、搜索兜底、时间冲突检测、UI 状态保护

## 📝 开发说明

- Mock 数据在 `data/` 目录下，可自由扩充活动和餐厅数据
- 所有工具继承自 `tools/base.py`，添加新工具只需实现 `execute()` 方法
- Prompt 模板在 `prompts/` 目录，支持独立调试

## 📄 License

MIT License
