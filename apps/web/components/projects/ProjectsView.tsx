"use client";

import Link from "next/link";
import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { ProjectStatusBadge, InlineError } from "@/components/projects/widgets";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import {
  useArchiveProject,
  useCreateProject,
  useProjects,
  useUnarchiveProject,
} from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import type { Project, ProjectStatus } from "@/lib/types";
import { ApiError } from "@/lib/api";

type Filter = "all" | "active" | "archived";

const PAGE_SIZE = 12;

export function ProjectsView() {
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const statusParam = filter === "all" ? undefined : (filter as ProjectStatus);
  const query = useProjects(page, PAGE_SIZE, statusParam);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const create = useCreateProject();

  const submitCreate = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate(
      { name: trimmed, description: description.trim() || undefined },
      {
        onSuccess: () => {
          setName("");
          setDescription("");
          setShowCreate(false);
          setPage(1);
        },
      },
    );
  };

  const data = query.data;

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="projects" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-800">项目</h1>
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            data-testid="toggle-create-project"
            className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-dark"
          >
            {showCreate ? "收起" : "+ 新建项目"}
          </button>
        </div>

        {showCreate ? (
          <form
            onSubmit={submitCreate}
            data-testid="create-project-form"
            className="mb-4 space-y-2 rounded-lg border border-gray-200 bg-white p-4"
          >
            <div>
              <label htmlFor="project-name" className="block text-xs font-medium text-gray-600">
                项目名称
              </label>
              <input
                id="project-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
                placeholder="如：夏季广告 / TikTok 6 月素材"
                className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="project-desc" className="block text-xs font-medium text-gray-600">
                描述（可选）
              </label>
              <textarea
                id="project-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={2000}
                rows={2}
                className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
              />
            </div>
            <InlineError error={create.error} />
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={!name.trim() || create.isPending}
                data-testid="submit-create-project"
                className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
              >
                {create.isPending ? "创建中…" : "创建"}
              </button>
            </div>
          </form>
        ) : null}

        <div className="mb-3 flex items-center gap-2 text-sm">
          {(["all", "active", "archived"] as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => {
                setFilter(f);
                setPage(1);
              }}
              data-testid={`filter-${f}`}
              aria-pressed={filter === f}
              className={`rounded-full border px-3 py-1 ${
                filter === f
                  ? "border-brand bg-brand/10 text-brand"
                  : "border-gray-300 text-gray-600 hover:bg-gray-100"
              }`}
            >
              {f === "all" ? "全部" : f === "active" ? "进行中" : "已归档"}
            </button>
          ))}
        </div>

        {query.isLoading ? (
          <Loading rows={4} />
        ) : query.isError ? (
          <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
        ) : !data || data.items.length === 0 ? (
          <Empty
            title="还没有项目"
            description="创建项目，把真实素材、镜头、产品、脚本与镜头集合组织到一起。"
          />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.items.map((p) => (
                <ProjectCard key={p.id} project={p} />
              ))}
            </div>
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={data.total}
              onPageChange={setPage}
              noun="项目"
            />
          </>
        )}
      </main>
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const archive = useArchiveProject(project.id);
  const unarchive = useUnarchiveProject(project.id);
  const archived = project.status === "archived";
  const busy = archive.isPending || unarchive.isPending;
  const err = (archive.error ?? unarchive.error) as ApiError | null;

  return (
    <div
      data-testid="project-card"
      className="flex flex-col rounded-lg border border-gray-200 bg-white p-4 transition hover:border-gray-300"
    >
      <div className="flex items-start justify-between gap-2">
        <Link
          href={`/projects/${project.id}`}
          className="min-w-0 flex-1 text-sm font-medium text-gray-800 hover:text-brand"
          data-testid={`open-project-${project.id}`}
        >
          <span className="block truncate">{project.name}</span>
        </Link>
        <ProjectStatusBadge status={project.status} />
      </div>
      {project.description ? (
        <p className="mt-1 line-clamp-2 text-xs text-gray-500">{project.description}</p>
      ) : (
        <p className="mt-1 text-xs text-gray-300">无描述</p>
      )}
      <div className="mt-3 flex items-center justify-between border-t border-gray-100 pt-2 text-[11px] text-gray-400">
        <span>更新于 {formatDateTime(project.updated_at)}</span>
        <button
          type="button"
          onClick={() =>
            archived
              ? unarchive.mutate(project.lock_version)
              : archive.mutate(project.lock_version)
          }
          disabled={busy}
          data-testid={archived ? `unarchive-${project.id}` : `archive-${project.id}`}
          className="rounded border border-gray-300 px-2 py-0.5 text-gray-600 disabled:opacity-50 hover:bg-gray-50"
        >
          {busy ? "…" : archived ? "恢复" : "归档"}
        </button>
      </div>
      {err ? (
        <div role="alert" className="mt-1 text-[11px] text-red-600">
          {err.status === 409 ? "已被更新，请刷新后重试" : err.message}
        </div>
      ) : null}
    </div>
  );
}
