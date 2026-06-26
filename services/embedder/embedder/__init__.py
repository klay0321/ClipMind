"""ClipMind 本地 Embedding 微服务（PR-04）。

OpenAI 兼容 ``/embeddings``，封装 sentence-transformers 多语模型（默认
intfloat/multilingual-e5-small，384 维）。torch 仅存在于本镜像，api/worker 通过
OpenAICompatibleEmbeddingProvider 以 HTTP 调用，不引入 torch。

约定：本服务**不加 E5 前缀**（query:/passage: 由调用端 provider 负责），也**不归一化**
（由 provider L2 归一），只负责把输入文本编码为向量。不记录业务文本与任何密钥。
"""
