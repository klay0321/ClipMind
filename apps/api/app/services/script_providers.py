"""PR-05 Gate A：API 侧脚本拆段解析器的装配。

与 Gate B 查询解析器一致：默认按 ``SCRIPT_PARSER`` 选择；``auto``/空 时，若 AI(mimo) 已配置
则用 mimo，否则规则拆段。mimo 失败会在解析器内部降级，本层不抛错。构造无网络副作用。
"""

from __future__ import annotations

from clipmind_shared.script.parser import (
    FakeScriptParser,
    RuleBasedScriptParser,
    ScriptParser,
    get_script_parser,
)

from app.config import Settings


def get_script_parser_for_settings(settings: Settings) -> ScriptParser:
    mode = (settings.script_parser or "").strip().lower()
    if mode == "fake":
        return FakeScriptParser()
    if mode == "rulebased":
        return RuleBasedScriptParser()
    mimo_ready = bool(settings.ai_base_url and settings.ai_api_key)
    if mode == "mimo" or (
        mode in ("", "auto")
        and (settings.ai_provider or "").strip().lower() == "mimo"
        and mimo_ready
    ):
        # 文本拆段模型：优先 script_parser_model，否则回退已配置的 ai_model（真实端点可用），
        # 最终由解析器默认 mimo-v2.5-pro 兜底。
        model = settings.script_parser_model or settings.ai_model or None
        return get_script_parser(
            "mimo",
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=model,
            timeout=settings.script_parser_timeout,
            api_key_header=settings.ai_api_key_header,
        )
    return RuleBasedScriptParser()
