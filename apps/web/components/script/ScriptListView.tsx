// 脚本项目列表页：标题 + 新建脚本（Modal）+ 搜索/状态筛选 + 结构化表格。
// 不再把巨大创建表单固定在列表顶部；创建后跳转工作台。
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { useCreateScript, useScripts } from "@/lib/hooks";
import { MAX_SCRIPT_LENGTH } from "@/lib/script";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/overlay";
import { TopNav } from "@/components/TopNav";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import type { ScriptStatus } from "@/lib/types";

import { ParserStatusBadge } from "./ParserStatusBadge";

const MAX_IMPORT_BYTES = 1_000_000; // 1MB 文本导入上限（仅纯文本/Markdown）

const STATUS_FILTERS: { value: "" | ScriptStatus; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "draft", label: "草稿" },
  { value: "parsed", label: "已拆段" },
  { value: "matched", label: "已匹配" },
  { value: "failed", label: "失败" },
];

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  parsing: "拆段中",
  parsed: "已拆段",
  matched: "已匹配",
  failed: "失败",
};

export function ScriptListView() {
  const router = useRouter();
  const listQ = useScripts();
  const create = useCreateScript();
  const [name, setName] = useState("");
  const [raw, setRaw] = useState("");
  const [importErr, setImportErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | ScriptStatus>("");
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

  const items = useMemo(() => {
    const all = listQ.data?.items ?? [];
    const term = q.trim().toLowerCase();
    return all.filter(
      (p) =>
        (!term || p.name.toLowerCase().includes(term)) &&
        (!statusFilter || p.status === statusFilter),
    );
  }, [listQ.data, q, statusFilter]);

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="script" />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">脚本匹配与剪辑清单</h1>
            <p className="text-sm text-gray-500">粘贴脚本分段，自动推荐镜头，并导出可用剪辑清单。</p>
          </div>
          <Button variant="primary" data-testid="script-new-btn" onClick={() => setOpen(true)}>
            ＋ 新建脚本
          </Button>
        </header>

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索脚本名称"
            aria-label="搜索脚本名称"
            className="w-56 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-brand focus:outline-none"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "" | ScriptStatus)}
            aria-label="状态筛选"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-brand focus:outline-none"
          >
            {STATUS_FILTERS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {listQ.isLoading ? (
          <Loading rows={3} />
        ) : listQ.isError ? (
          <ErrorState
            message={(listQ.error as Error)?.message ?? "加载失败"}
            onRetry={() => void listQ.refetch()}
          />
        ) : items.length === 0 ? (
          <Empty
            title={(listQ.data?.items.length ?? 0) === 0 ? "还没有脚本项目" : "没有符合条件的脚本"}
            description="点「新建脚本」粘贴文案，自动拆段并匹配镜头。"
            action={
              <Button variant="secondary" onClick={() => setOpen(true)}>
                新建脚本
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white" data-testid="script-list">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-gray-100 text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-3 py-2.5 font-medium">脚本名称</th>
                  <th className="px-3 py-2.5 font-medium">状态</th>
                  <th className="px-3 py-2.5 font-medium">段落数</th>
                  <th className="px-3 py-2.5 font-medium">更新时间</th>
                  <th className="px-3 py-2.5 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {items.map((p) => (
                  <tr key={p.id} className="hover:bg-gray-50/60">
                    <td className="max-w-[18rem] px-3 py-2.5">
                      <Link
                        href={`/script/${p.id}`}
                        data-testid="script-list-item"
                        className="block truncate font-medium text-gray-800 hover:text-brand"
                        title={p.name}
                      >
                        {p.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                          {STATUS_LABEL[p.status] ?? p.status}
                        </span>
                        <ParserStatusBadge
                          status={p.parse_status}
                          provider={p.parser_provider}
                          warnings={null}
                        />
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-gray-700">{p.segment_count} 段</td>
                    <td className="px-3 py-2.5 text-gray-500">{formatDateTime(p.updated_at)}</td>
                    <td className="px-3 py-2.5 text-right">
                      <Link
                        href={`/script/${p.id}`}
                        className="inline-flex items-center rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                      >
                        打开工作台 →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="新建脚本项目"
        widthClass="max-w-2xl"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)} disabled={create.isPending}>
              取消
            </Button>
            <Button
              variant="primary"
              data-testid="script-create"
              onClick={submit}
              disabled={!name.trim() || !raw.trim() || create.isPending}
              loading={create.isPending}
            >
              {create.isPending ? "创建中…" : "创建并进入工作台"}
            </Button>
          </>
        }
      >
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
          </div>
          {createErr ? (
            <p className="text-[11px] text-red-600" role="alert">
              创建失败：{createErr}
            </p>
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
