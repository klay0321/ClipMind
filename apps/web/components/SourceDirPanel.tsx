"use client";

import { useState } from "react";

import { ScanStatusBadge } from "@/components/StatusBadge";
import type { SourceDirectory, SourceDirectoryCreate } from "@/lib/types";

export function SourceDirPanel({
  dirs,
  selectedDirId,
  onSelect,
  onScan,
  scanningDirId,
  onCreate,
  creating,
  createError,
}: {
  dirs: SourceDirectory[];
  selectedDirId: number | null;
  onSelect: (id: number) => void;
  onScan: (id: number) => void;
  scanningDirId: number | null;
  onCreate: (payload: SourceDirectoryCreate) => void;
  creating: boolean;
  createError: string | null;
}) {
  const [name, setName] = useState("");
  const [mountPath, setMountPath] = useState("/app/source");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !mountPath.trim()) return;
    onCreate({ name: name.trim(), mount_path: mountPath.trim() });
    setName("");
  };

  return (
    <section className="rounded-lg border border-gray-100 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-base font-semibold">素材目录</h2>

      <div className="mb-4 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-relaxed text-blue-800">
        「素材目录」填的是容器内只读挂载点{" "}
        <code className="rounded bg-white/70 px-1">/app/source</code>，本地开发时它对应项目里的{" "}
        <code className="rounded bg-white/70 px-1">sample_media</code> 文件夹。把视频放进该文件夹，这里填{" "}
        <code className="rounded bg-white/70 px-1">/app/source</code>（或子目录，如{" "}
        <code className="rounded bg-white/70 px-1">/app/source/powergo</code>）再点「扫描」即可。部署到 NAS 后{" "}
        <code className="rounded bg-white/70 px-1">/app/source</code> 会指向 NAS 素材目录，填法不变。ClipMind
        只读取、绝不修改源文件。
      </div>

      <form onSubmit={submit} className="mb-4 flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-xs text-gray-500">
          目录名称
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如 PowerGo 原始素材"
            aria-label="目录名称"
            className="mt-1 w-52 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-900 focus:border-brand focus:outline-none"
          />
        </label>
        <label className="flex flex-col text-xs text-gray-500">
          素材路径（容器内，通常直接用 /app/source）
          <input
            value={mountPath}
            onChange={(e) => setMountPath(e.target.value)}
            aria-label="素材路径"
            className="mt-1 w-64 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-900 focus:border-brand focus:outline-none"
          />
        </label>
        <button
          type="submit"
          disabled={creating}
          className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
        >
          {creating ? "添加中…" : "添加目录"}
        </button>
      </form>
      {createError ? <p className="mb-3 text-xs text-red-600">{createError}</p> : null}

      {dirs.length === 0 ? (
        <p className="text-sm text-gray-500">
          还没有素材目录。把视频放进本地 sample_media 文件夹，这里填 /app/source 并点「扫描」即可。
        </p>
      ) : (
        <ul className="divide-y divide-gray-50">
          {dirs.map((d) => {
            const selected = d.id === selectedDirId;
            const scanning = d.id === scanningDirId;
            return (
              <li key={d.id} className="flex items-center justify-between gap-3 py-2">
                <label className="flex flex-1 cursor-pointer items-center gap-3">
                  <input
                    type="radio"
                    name="selected-dir"
                    checked={selected}
                    onChange={() => onSelect(d.id)}
                    className="accent-brand"
                  />
                  <span>
                    <span className="font-medium text-gray-900">{d.name}</span>
                    <span className="ml-2 text-xs text-gray-400">{d.mount_path}</span>
                  </span>
                </label>
                <ScanStatusBadge status={d.scan_status} />
                <button
                  type="button"
                  onClick={() => onScan(d.id)}
                  disabled={scanning}
                  className="rounded-md bg-brand px-3 py-1 text-xs font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
                >
                  {scanning ? "扫描中…" : "扫描"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
