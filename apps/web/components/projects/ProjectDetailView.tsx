"use client";

import Link from "next/link";
import { useState } from "react";

import {
  ProjectAssetsTab,
  ProjectCollectionsTab,
  ProjectProductsTab,
  ProjectScriptsTab,
  ProjectShotsTab,
} from "@/components/projects/tabs";
import { ProjectStatsGrid } from "@/components/projects/ProjectStatsGrid";
import { ArchivedBanner, InlineError, ProjectStatusBadge } from "@/components/projects/widgets";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { TopNav } from "@/components/TopNav";
import { formatDateTime } from "@/lib/format";
import {
  useArchiveProject,
  useProject,
  useProjectStats,
  useUnarchiveProject,
  useUpdateProject,
} from "@/lib/hooks";
import type { Project } from "@/lib/types";

type Tab = "overview" | "assets" | "shots" | "collections" | "products" | "scripts";
const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "总览" },
  { key: "assets", label: "素材" },
  { key: "shots", label: "镜头" },
  { key: "collections", label: "Collections" },
  { key: "products", label: "产品" },
  { key: "scripts", label: "脚本" },
];

export function ProjectDetailView({ projectId }: { projectId: number }) {
  const projectQuery = useProject(projectId);
  const [tab, setTab] = useState<Tab>("overview");
  const project = projectQuery.data;

  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="projects" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Link href="/projects" className="text-sm text-gray-500 hover:text-brand">
          ← 返回项目列表
        </Link>
        {projectQuery.isLoading ? (
          <Loading rows={3} />
        ) : projectQuery.isError ? (
          <ErrorState
            message={(projectQuery.error as Error).message}
            onRetry={() => projectQuery.refetch()}
          />
        ) : !project ? null : (
          <>
            <ProjectHeader project={project} />
            {project.status === "archived" ? (
              <ArchivedBannerControl project={project} />
            ) : null}

            <nav className="mt-4 flex gap-1 border-b border-gray-200" role="tablist">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.key}
                  data-testid={`tab-${t.key}`}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                    tab === t.key
                      ? "border-brand font-medium text-brand"
                      : "border-transparent text-gray-500 hover:text-gray-800"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>

            <div className="py-4" data-testid={`tabpanel-${tab}`}>
              {tab === "overview" ? <OverviewTab project={project} /> : null}
              {tab === "assets" ? <ProjectAssetsTab project={project} /> : null}
              {tab === "shots" ? <ProjectShotsTab project={project} /> : null}
              {tab === "collections" ? <ProjectCollectionsTab project={project} /> : null}
              {tab === "products" ? <ProjectProductsTab project={project} /> : null}
              {tab === "scripts" ? <ProjectScriptsTab project={project} /> : null}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function ProjectHeader({ project }: { project: Project }) {
  const archived = project.status === "archived";
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const update = useUpdateProject(project.id);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    update.mutate(
      { lock_version: project.lock_version, name: trimmed, description: description.trim() },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <div className="mt-2">
      {editing && !archived ? (
        <form onSubmit={submit} data-testid="edit-project-form" className="space-y-2 rounded-lg border border-gray-200 bg-white p-4">
          <div>
            <label htmlFor="edit-name" className="block text-xs font-medium text-gray-600">
              项目名称
            </label>
            <input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="edit-desc" className="block text-xs font-medium text-gray-600">
              描述
            </label>
            <textarea
              id="edit-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              rows={2}
              className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none"
            />
          </div>
          <InlineError error={update.error} />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setName(project.name);
                setDescription(project.description ?? "");
              }}
              className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={!name.trim() || update.isPending}
              data-testid="submit-edit-project"
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
            >
              {update.isPending ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-xl font-semibold text-gray-800" data-testid="project-name">
                {project.name}
              </h1>
              <ProjectStatusBadge status={project.status} />
            </div>
            {project.description ? (
              <p className="mt-1 text-sm text-gray-500">{project.description}</p>
            ) : null}
            <p className="mt-1 text-xs text-gray-400">
              创建于 {formatDateTime(project.created_at)} · 更新于 {formatDateTime(project.updated_at)}
            </p>
          </div>
          {!archived ? (
            <button
              type="button"
              onClick={() => setEditing(true)}
              data-testid="edit-project"
              className="shrink-0 rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              编辑
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

function ArchivedBannerControl({ project }: { project: Project }) {
  const unarchive = useUnarchiveProject(project.id);
  return (
    <div className="mt-3">
      <ArchivedBanner
        onUnarchive={() => unarchive.mutate(project.lock_version)}
        pending={unarchive.isPending}
      />
      <InlineError error={unarchive.error} />
    </div>
  );
}

function OverviewTab({ project }: { project: Project }) {
  const stats = useProjectStats(project.id, true);
  const archive = useArchiveProject(project.id);
  const unarchive = useUnarchiveProject(project.id);
  const archived = project.status === "archived";
  return (
    <div className="space-y-4">
      {stats.isLoading ? (
        <Loading rows={3} />
      ) : stats.isError ? (
        <ErrorState message={(stats.error as Error).message} onRetry={() => stats.refetch()} />
      ) : stats.data ? (
        <ProjectStatsGrid stats={stats.data} />
      ) : null}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="text-sm font-medium text-gray-700">项目状态</div>
        <p className="mt-1 text-xs text-gray-500">
          {archived
            ? "项目已归档（只读）。恢复后可继续编辑成员与集合。"
            : "项目进行中。可添加素材/镜头/产品/脚本，并组织镜头集合。"}
        </p>
        <button
          type="button"
          onClick={() =>
            archived ? unarchive.mutate(project.lock_version) : archive.mutate(project.lock_version)
          }
          disabled={archive.isPending || unarchive.isPending}
          data-testid={archived ? "overview-unarchive" : "overview-archive"}
          className="mt-2 rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:opacity-50 hover:bg-gray-50"
        >
          {archived ? "恢复项目" : "归档项目"}
        </button>
        <InlineError error={archive.error ?? unarchive.error} />
      </div>
    </div>
  );
}
