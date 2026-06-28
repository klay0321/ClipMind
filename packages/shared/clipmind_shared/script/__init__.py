"""PR-05 脚本拆段（结构化 Schema + 解析器）。

公开：``ParsedScript`` / ``ParsedScriptSegment``（严格校验的数据模型）、``ScriptParser`` 协议、
``RuleBasedScriptParser`` / ``FakeScriptParser`` 与工厂 ``get_script_parser``、``split_segments``。
MiMo 实现惰性导入（见 ``parser_mimo``）。
"""

from clipmind_shared.script.parser import (
    FakeScriptParser,
    RuleBasedScriptParser,
    ScriptParser,
    get_script_parser,
    split_segments,
)
from clipmind_shared.script.schema import (
    MAX_SCRIPT_LENGTH,
    MAX_SEGMENTS,
    ParsedScript,
    ParsedScriptSegment,
)

__all__ = [
    "ParsedScript",
    "ParsedScriptSegment",
    "ScriptParser",
    "RuleBasedScriptParser",
    "FakeScriptParser",
    "get_script_parser",
    "split_segments",
    "MAX_SEGMENTS",
    "MAX_SCRIPT_LENGTH",
]
