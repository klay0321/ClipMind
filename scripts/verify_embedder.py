#!/usr/bin/env python3
"""本地真实 embedder 最低验收（PR-04 §13）。

经 OpenAICompatibleEmbeddingProvider 调用真实 embedder 服务，验证真实嵌入链路可用：
- 中文/英文/中英混合：近义文档相似度高于无关文档；
- 维度严格为配置值（默认 384）；
- 批量顺序稳定；相同输入重复请求向量稳定；
- query/passage 前缀生效（provider 负责）。

这不是 Gate B 的检索质量验收，只证明真实 Embedding 链路可用。需先启动 embedder：
    docker compose --profile embedding up -d embedder
    EMBEDDING_BASE_URL=http://localhost:8100 EMBEDDING_MODEL=intfloat/multilingual-e5-small \\
        EMBEDDING_DIMENSION=384 python scripts/verify_embedder.py
"""

from __future__ import annotations

import os
import sys

from clipmind_shared.ai import get_embedding_provider


def _cos(a: list[float], b: list[float]) -> float:
    # provider 已 L2 归一，点积即 cosine
    return sum(x * y for x, y in zip(a, b, strict=True))


def main() -> int:
    base_url = os.environ.get("EMBEDDING_BASE_URL", "http://localhost:8100")
    model = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    dim = int(os.environ.get("EMBEDDING_DIMENSION", "384"))
    provider = get_embedding_provider(
        "openai_compatible",
        base_url=base_url,
        api_key=os.environ.get("EMBEDDING_API_KEY") or None,
        model=model,
        dimension=dim,
        model_revision=os.environ.get("EMBEDDING_MODEL_REVISION", ""),
    )

    cases = [
        ("中文", "桌面上给手机充电的充电器", "充电器放在桌面上为手机充电", "一只猫在草地上奔跑"),
        ("英文", "a charger powering a phone on a desk", "desktop charger charging a smartphone", "a cat running on grass"),
        ("混合", "PowerGo 充电器 desk charging", "PowerGo charger on a desk charging a phone", "森林里的瀑布风景"),
    ]
    failures: list[str] = []
    for label, query, near, far in cases:
        q = provider.embed_query(query)
        d_near, d_far = provider.embed_documents([near, far])
        if len(q) != dim or len(d_near) != dim:
            failures.append(f"{label}: 维度不符 {len(q)}/{len(d_near)} != {dim}")
            continue
        s_near, s_far = _cos(q, d_near), _cos(q, d_far)
        ok = s_near > s_far
        print(f"[{label}] near={s_near:.4f} far={s_far:.4f} -> {'OK' if ok else 'FAIL'}")
        if not ok:
            failures.append(f"{label}: 近义({s_near:.4f}) 未高于无关({s_far:.4f})")

    # 批序稳定 + 可复现（真实模型批量与单条存在极小浮点差，用 cosine 容差而非精确相等）
    texts = ["第一段文本", "second text", "第三段 mixed text"]
    b1 = provider.embed_documents(texts)
    b2 = provider.embed_documents(texts)
    for i in range(len(texts)):
        if _cos(b1[i], b2[i]) < 0.9999:
            failures.append("重复请求向量不稳定")
            break
    # 顺序保持：批量第 i 条与其单条嵌入高度一致（cosine~1），且高于与其它位置的相似度
    for i in range(len(texts)):
        single = provider.embed_documents([texts[i]])[0]
        s_self = _cos(single, b1[i])
        s_others = [_cos(single, b1[j]) for j in range(len(texts)) if j != i]
        if s_self < 0.999:
            failures.append(f"批量第 {i} 条与单条不一致 (cos={s_self:.4f})")
        if s_others and s_self <= max(s_others):
            failures.append(f"批量顺序错位（位置 {i}）")

    if failures:
        print("\n验收失败：", *failures, sep="\n  - ", file=sys.stderr)
        return 1
    print("\n真实 embedder 最低验收通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
