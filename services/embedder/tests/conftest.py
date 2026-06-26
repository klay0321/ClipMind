"""让 embedder 包可被测试导入（torch/sentence-transformers 惰性导入，测试不需要）。"""

from __future__ import annotations

import os
import sys

# services/embedder 根加入 sys.path，使 `import embedder.app` 可用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
