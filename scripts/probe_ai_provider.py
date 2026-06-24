#!/usr/bin/env python3
"""MiMo / OpenAI 兼容 AI Provider 能力探测（PR-03A）。

只读环境变量 / .env 取配置（密钥仅本地，绝不写代码/库/前端/提交）；输出**脱敏**能力报告，
据此回填 ProviderCapabilities 并决定调用与降级。**任一探测失败，相关能力默认置为不支持。**

用法：
    # 先在本机 .env 配置 AI_BASE_URL / AI_API_KEY / AI_MODEL（绝不提交）
    python scripts/probe_ai_provider.py            # 人类可读报告
    python scripts/probe_ai_provider.py --json     # JSON 报告
    python scripts/probe_ai_provider.py --out docs/ai-probe-report.local.md

覆盖 AI_PROVIDER_PLAN 第 2 节 17 项；部分项（URL 图 / 并发上限 / 限流策略 / 上下文窗口 /
数据是否被保留）需结合厂商文档人工确认，脚本标记为 manual。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time

try:
    import httpx
except ImportError:  # pragma: no cover
    print("需要 httpx（pip install httpx）", file=sys.stderr)
    sys.exit(2)

# 1x1 透明 PNG（避免依赖 PIL；用于图片输入探测）
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_DATA_URL = "data:image/png;base64," + base64.b64encode(_PNG_1x1).decode("ascii")


def _redact(secret: str) -> str:
    if not secret:
        return "<empty>"
    return ("****" + secret[-4:]) if len(secret) > 4 else "****"


def _load_env() -> dict:
    # 简单加载 .env（不覆盖已存在的环境变量）
    if os.path.isfile(".env"):
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return {
        "provider": os.environ.get("AI_PROVIDER", ""),
        "base_url": os.environ.get("AI_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("AI_API_KEY", ""),
        "model": os.environ.get("AI_MODEL", ""),
        "embed_model": os.environ.get("EMBEDDING_MODEL", ""),
        "timeout": float(os.environ.get("AI_TIMEOUT", "60") or 60),
        "max_images": int(os.environ.get("AI_MAX_IMAGES", "4") or 4),
    }


class Probe:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.results: list[dict] = []
        self.client = httpx.Client(
            timeout=cfg["timeout"],
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
        )

    def _record(self, name: str, status: str, detail: str = "") -> None:
        self.results.append({"probe": name, "status": status, "detail": detail})

    def _chat(self, messages: list, **extra) -> httpx.Response:
        body = {"model": self.cfg["model"], "temperature": 0, "messages": messages, **extra}
        return self.client.post(f"{self.cfg['base_url']}/chat/completions", json=body)

    def run(self) -> list[dict]:
        self._connectivity_auth_compat()
        self._text()
        self._json()
        self._json_schema()
        self._images()
        self._embedding()
        self._latency()
        for name in ("url_image", "context_window", "concurrency", "rate_limit", "data_retention"):
            self._record(name, "manual", "需结合厂商文档/观测人工确认")
        return self.results

    def _connectivity_auth_compat(self) -> None:
        try:
            r = self.client.get(f"{self.cfg['base_url']}/models")
        except httpx.HTTPError as e:
            self._record("connectivity", "fail", f"连接失败: {type(e).__name__}")
            self._record("auth", "skip", "连通性失败")
            self._record("openai_compat", "skip", "连通性失败")
            return
        if r.status_code in (401, 403):
            self._record("connectivity", "ok", f"HTTP {r.status_code}")
            self._record("auth", "fail", "鉴权失败（检查 AI_API_KEY）")
            self._record("openai_compat", "skip", "鉴权失败")
            return
        self._record("connectivity", "ok", f"HTTP {r.status_code}")
        self._record("auth", "ok" if r.status_code < 400 else "warn", f"HTTP {r.status_code}")
        try:
            data = r.json()
            ok = isinstance(data, dict) and "data" in data
        except ValueError:
            ok = False
        self._record("openai_compat", "ok" if ok else "warn", "/models 返回 OpenAI 风格" if ok else "非标准响应")

    def _text(self) -> None:
        try:
            r = self._chat([{"role": "user", "content": "回复一个字：好"}])
            ok = r.status_code < 400 and r.json()["choices"][0]["message"]["content"]
            self._record("text", "ok" if ok else "fail", f"HTTP {r.status_code}")
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            self._record("text", "fail", type(e).__name__)

    def _json(self) -> None:
        try:
            r = self._chat([{"role": "user", "content": '只输出 JSON: {"ok": true}'}])
            content = r.json()["choices"][0]["message"]["content"]
            json.loads(content.strip().strip("`").removeprefix("json").strip())
            self._record("strict_json", "ok", "可解析为 JSON")
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            self._record("strict_json", "fail", type(e).__name__)

    def _json_schema(self) -> None:
        try:
            r = self._chat(
                [{"role": "user", "content": '输出 {"a":1}'}],
                response_format={"type": "json_object"},
            )
            ok = r.status_code < 400
            self._record("json_schema", "ok" if ok else "warn", f"response_format HTTP {r.status_code}")
        except httpx.HTTPError as e:
            self._record("json_schema", "warn", f"不支持 response_format? {type(e).__name__}")

    def _image_msg(self, n: int) -> list:
        content = [{"type": "text", "text": "描述这些图片"}]
        for _ in range(n):
            content.append({"type": "image_url", "image_url": {"url": _DATA_URL}})
        return [{"role": "user", "content": content}]

    def _images(self) -> None:
        for name, n in (("single_image", 1), ("multi_image", 2)):
            try:
                r = self._chat(self._image_msg(n))
                ok = r.status_code < 400
                self._record(name, "ok" if ok else "fail", f"HTTP {r.status_code}")
                if name == "single_image":
                    self._record("base64_image", "ok" if ok else "fail", "内联 Base64 图")
            except httpx.HTTPError as e:
                self._record(name, "fail", type(e).__name__)

    def _embedding(self) -> None:
        model = self.cfg["embed_model"] or self.cfg["model"]
        try:
            r = self.client.post(
                f"{self.cfg['base_url']}/embeddings",
                json={"model": model, "input": "hello"},
            )
            ok = r.status_code < 400 and r.json().get("data")
            self._record("embedding", "ok" if ok else "fail", f"HTTP {r.status_code}")
        except (httpx.HTTPError, ValueError) as e:
            self._record("embedding", "fail", type(e).__name__)

    def _latency(self) -> None:
        try:
            t0 = time.perf_counter()
            self._chat([{"role": "user", "content": "hi"}])
            self._record("timeout", "ok", f"单次往返 {int((time.perf_counter()-t0)*1000)}ms")
        except httpx.HTTPError as e:
            self._record("timeout", "fail", type(e).__name__)


def _render_md(cfg: dict, results: list[dict]) -> str:
    lines = [
        "# AI Provider 能力探测报告（脱敏）",
        "",
        f"- provider: `{cfg['provider'] or '<unset>'}`",
        f"- base_url: `{cfg['base_url'] or '<unset>'}`",
        f"- model: `{cfg['model'] or '<unset>'}`",
        f"- api_key: `{_redact(cfg['api_key'])}`",
        "",
        "| 探测项 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for r in results:
        lines.append(f"| {r['probe']} | {r['status']} | {r['detail']} |")
    lines.append("")
    lines.append("> 任一关键探测失败，相关能力默认置为不支持并走降级，绝不伪造。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="AI Provider 能力探测（脱敏）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    ap.add_argument("--out", help="写入报告文件路径（Markdown）")
    args = ap.parse_args()

    cfg = _load_env()
    if not cfg["base_url"] or not cfg["api_key"]:
        print("未配置 AI_BASE_URL / AI_API_KEY（仅本地 .env 提供，绝不提交）。", file=sys.stderr)
        return 1

    results = Probe(cfg).run()

    if args.json:
        print(json.dumps({"config": {**cfg, "api_key": _redact(cfg["api_key"])}, "results": results},
                         ensure_ascii=False, indent=2))
    else:
        print(_render_md(cfg, results))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(_render_md(cfg, results))
        print(f"\n报告已写入 {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
