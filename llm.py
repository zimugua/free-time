"""
大模型调用模块
统一封装对 OpenAI-compatible API 的调用，读取 config.yaml 获取配置
"""
import os
from pathlib import Path
from typing import List, Dict, Optional

import yaml
from prompts import INTENT_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT, build_plan_user_prompt

# ---------- 配置加载 ----------
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------- LLM 客户端 ----------
class LLMClient:
    """
    统一的大模型调用客户端。
    使用 openai SDK（兼容 DeepSeek / 智谱 / 通义 / Moonshot 等所有 OpenAI 兼容接口）。
    """

    def __init__(self):
        cfg = load_config()
        llm_cfg = cfg.get("llm", {})
        self.api_key = llm_cfg.get("api_key", "")
        self.base_url = llm_cfg.get("base_url", "https://api.openai.com/v1")
        self.model = llm_cfg.get("model", "gpt-4o-mini")
        self.timeout = llm_cfg.get("timeout", 30)
        self.temperature = llm_cfg.get("temperature", 0.7)
        self.max_tokens = llm_cfg.get("max_tokens", 2000)

        # 延迟导入，避免未安装 openai 时启动报错
        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
            self._available = True
        except ImportError:
            self._available = False
            print("[WARN] openai 包未安装，LLM 功能不可用，将使用规则模式")
        except Exception as e:
            self._available = False
            print(f"[WARN] LLM 客户端初始化失败：{e}，将使用规则模式")

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """
        发起对话请求。
        :param messages: [{"role": "system/user/assistant", "content": "..."}]
        :return: 模型回复文本
        """
        if not self._available:
            return ""
        if not self.api_key or self.api_key.startswith("sk-your"):
            print("[WARN] config.yaml 中的 api_key 尚未配置，将使用规则模式")
            return ""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[WARN] LLM 调用失败：{e}，将使用规则模式")
            return ""

    def chat_stream(self, messages: List[Dict[str, str]]):
        """
        流式对话请求，逐 token yield 文本片段。
        :param messages: [{"role": "system/user/assistant", "content": "..."}]
        :yield: str 每次产出一段文本片段
        """
        if not self._available or not self.api_key or self.api_key.startswith("sk-your"):
            return
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
            for chunk in resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            print(f"[WARN] LLM 流式调用失败：{e}，将使用规则模式")

    def parse_intent(self, user_input: str) -> dict:
        """
        用大模型解析用户意图，提取场景/人数/约束等结构化信息。
        若 LLM 不可用则返回空字典（由 Agent 降级到规则解析）。
        """
        if not self._available or not self.api_key or self.api_key.startswith("sk-your"):
            return {}

        messages = [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]
        result = self.chat(messages)
        if not result:
            return {}
        try:
            import json
            # 去除可能的 markdown 代码块标记
            result = result.strip().strip("```json").strip("```").strip()
            return json.loads(result)
        except Exception:
            return {}

    def generate_plan_text(self, context: dict) -> str:
        """
        用大模型生成自然语言计划方案。
        若 LLM 不可用则返回空字符串（由 Agent 降级到模板生成）。
        """
        if not self._available or not self.api_key or self.api_key.startswith("sk-your"):
            return ""

        messages = [
            {"role": "system", "content": PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": build_plan_user_prompt(context)},
        ]
        return self.chat(messages)

    def generate_plan_text_stream(self, context: dict):
        """
        流式生成自然语言计划方案，逐 token yield 文本片段。
        若 LLM 不可用则 yield 空字符串（由调用方降级到模板生成）。
        """
        if not self._available or not self.api_key or self.api_key.startswith("sk-your"):
            return

        messages = [
            {"role": "system", "content": PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": build_plan_user_prompt(context)},
        ]
        yield from self.chat_stream(messages)


# 单例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
