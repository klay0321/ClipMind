// 脚本项目列表 + 新建（粘贴脚本 / 可选 .txt|.md 导入）。创建后跳转工作台。
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { useCreateScript, useScripts } from "@/lib/hooks";
import { MAX_SCRIPT_LENGTH } from "@/lib/script";
import { formatDateTime } from "@/lib/format";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

import { ParserStatusBadge } from "./ParserStatusBadge";

const MAX_IMPORT_BYTES = 1_000_000; // 1MB 文本导入上限（仅纯文本/Markdown）

export function ScriptListView() {
  const router = useRouter();
  const listQ = useScripts();
  const create = useCreateScript();
  const [name, setName] = useState("");
  const [raw, setRaw] = useState("");
  const [importErr, setImportErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const onFile = async (file: File | undefined) => {
    setImportErr(null);
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".txt") && !lower.endsWith(".md")) {
      setImportErr("仅支持 .txt / .md 文本文件（不支持 .docx）");
      return;
    }
    if (file.size > MAX_IMPORT_BYTES) {
      setImportErr("文件过大（上限 1MB）");
      return;
    }
    const text = (await file.text()).slice(0, MAX_SCRIPT_LENGTH);
    setRaw(text);
    if (!name.trim()) setName(file.name.replace(/\.(txt|md)$/i, ""));
  };

  const submit = () => {
    if (!name.trim() || !raw.trim() || create.isPending) return;
    create.mutate(
      { name: name.trim(), raw_script: raw, source_format: "paste" },
      { onSuccess: (proj) => router.push(`/script/${proj.id}`) },
    );
  };

  const createErr =
    create.error instanceof ApiError
      ? create.error.message
      : (create.error as Error | undefined)?.message ?? null;

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="script" />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <header className="mb-4">
          <h1 className="text-xl font-semibold text-gray-900">脚本匹配与剪辑清单</h1>
          <p className="text-sm text-gray-500">粘贴脚本分段，自动推荐镜头，并导出可用剪辑清单。</p>
        </header>

        <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4" aria-labelledby="new-script-h">
          <h2 id="new-script-h" className="mb-2 text-sm font-semibold text-gray-800">
            新建脚本项目
          </h2>
          <div className="space-y-3">
            <label className="block text-xs">
              <span className="text-gray-500">项目名称</span>
              <input
                data-testid="script-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={255}
                placeholder="如 吹风机产品介绍"
                className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              />
            </label>
            <label className="block text-xs">
              <div className="flex items-center justify-between">
                <span className="text-gray-500">脚本或分镜（粘贴文本）</span>
                <span className="text-[11px] text-gray-400">
                  {raw.length}/{MAX_SCRIPT_LENGTH}
                </span>
              </div>
              <textarea
                data-testid="script-raw"
                value={raw}
                maxLength={MAX_SCRIPT_LENGTH}
                onChange={(e) => setRaw(e.target.value)}
                rows={8}
                placeholder="粘贴完整脚本文案，按段落或镜头自然换行。支持中文 / 英文 / 中英混排。"
                className="mt-1 w-full resize-y rounded border border-gray-300 px-2 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.md,text/plain,text/markdown"
                data-testid="script-import"
                className="hidden"
                onChange={(e) => void onFile(e.target.files?.[0])}
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
              >
                导入 .txt / .md
              </button>
              {importErr ? <span className="text-[11px] text-red-600">{importErr}</span> : null}
              <button
                type="button"
                data-testid="script-create"
                onClick={submit}
                disabled={!name.trim() || !raw.trim() || create.isPending}
                className="ml-auto rounded-md bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
              >
                {create.isPending ? "创建中…" : "创建并进入工作台"}
              </button>
            </div>
            {createErr ? (
              <p className="text-[11px] text-red-600" role="alert">
                创建失败：{createErr}
              </p>
            ) : null}
          </div>
        </section>

        <section aria-labelledby="script-list-h">
          <h2 id="script-list-h" className="mb-2 text-sm font-semibold text-gray-800">
            已有脚本项目
          </h2>
          {listQ.isLoading ? (
            <Loading rows={3} />
          ) : listQ.isError ? (
            <ErrorState
              message={(listQ.error as Error)?.message ?? "加载失败"}
              onRetry={() => void listQ.refetch()}
            />
          ) : (listQ.data?.items.length ?? 0) === 0 ? (
            <Empty title="还没有脚本项目" description="在上方粘贴脚本并创建第一个项目。" />
          ) : (
            <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white" data-testid="script-list">
              {listQ.data!.items.map((p) => (
                <li key={p.id} className="flex items-center gap-3 px-3 py-2.5">
                  <Link
                    href={`/script/${p.id}`}
                    data-testid="script-list-item"
                    className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800 hover:text-brand"
                  >
                    {p.name}
                  </Link>
                  <ParserStatusBadge
                    status={p.parse_status}
                    provider={p.parser_provider}
                    warnings={null}
                  />
                  <span className="hidden text-[11px] text-gray-400 sm:inline">
                    {p.segment_count} 段 · {formatDateTime(p.updated_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  );
}
