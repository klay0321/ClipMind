"use client";

import Link from "next/link";
import { useState } from "react";

import { DynamicCollectionsSection } from "@/components/projects/DynamicCollections";
import { MemberPicker, type PickerPage } from "@/components/projects/MemberPicker";
import {
  BatchResultNotice,
  ConfirmDialog,
  InlineError,
} from "@/components/projects/widgets";
import { PreviewModal } from "@/components/PreviewModal";
import { ShotCard } from "@/components/ShotCard";
import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { api, assetPosterUrl, shotThumbnailUrl } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";
import {
  useAddProjectAssets,
  useAddProjectProducts,
  useAddProjectShots,
  useAttachProjectScript,
  useCreateCollection,
  useDeleteCollection,
  useDetachProjectScript,
  useProjectAssets,
  useProjectCollections,
  useProjectProducts,
  useProjectScripts,
  useProjectShots,
  useProjectStats,
  useProducts,
  useRemoveProjectAsset,
  useRemoveProjectProduct,
  useRemoveProjectShot,
  useReorderProjectAssets,
} from "@/lib/hooks";
import type {
  BatchMembershipResult,
  Collection,
  Project,
  ProjectShotSource,
  ReviewStatus,
} from "@/lib/types";

const ARCHIVED_HINT = "项目已归档（只读），恢复后可编辑。";

// ============================ 素材 Tab ============================

export function ProjectAssetsTab({ project }: { project: Project }) {
  const archived = project.status === "archived";
  const [page, setPage] = useState(1);
  const pageSize = 24;
  const query = useProjectAssets(project.id, page, pageSize);
  const add = useAddProjectAssets(project.id);
  const remove = useRemoveProjectAsset(project.id);
  const reorder = useReorderProjectAssets(project.id);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [batch, setBatch] = useState<BatchMembershipResult | null>(null);
  const data = query.data;
  const canReorder = !archived && data != null && data.total <= pageSize && data.items.length > 1;

  const fetchAssets = (p: number, q: string): Promise<PickerPage> =>
    api.listAssets({ page: p, page_size: 24, q: q || undefined }).then((r) => ({
      total: r.total,
      items: r.items.map((a) => ({
        id: a.id,
        label: a.filename,
        sub: `${a.shot_count} 镜头`,
        thumbUrl: a.has_poster ? assetPosterUrl(a.id) : undefined,
      })),
    }));

  const move = (index: number, dir: -1 | 1) => {
    if (!data) return;
    const ids = data.items.map((it) => it.asset.id);
    const j = index + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[index], ids[j]] = [ids[j], ids[index]];
    reorder.mutate({ ids, lockVersion: project.lock_version });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-500">项目素材（其镜头计入可见镜头，不复制数据）</span>
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          disabled={archived}
          title={archived ? ARCHIVED_HINT : undefined}
          data-testid="add-assets"
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark"
        >
          + 添加素材
        </button>
      </div>
      <BatchResultNotice result={batch} nounMap={{ completed: "素材" }} />
      <InlineError error={add.error ?? remove.error ?? reorder.error} />
      {query.isLoading ? (
        <Loading rows={3} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !data || data.items.length === 0 ? (
        <Empty title="项目暂无素材" description="点击「添加素材」从素材库批量加入。" />
      ) : (
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
          {data.items.map((it, i) => (
            <li key={it.asset.id} className="flex items-center gap-3 px-3 py-2" data-testid={`project-asset-${it.asset.id}`}>
              {it.asset.has_poster ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={assetPosterUrl(it.asset.id)} alt="" className="h-10 w-16 rounded object-cover" loading="lazy" />
              ) : (
                <div className="flex h-10 w-16 items-center justify-center rounded bg-gray-100 text-[10px] text-gray-400">无封面</div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-gray-800" title={it.asset.filename}>
                  {it.asset.filename}
                </div>
                <div className="text-xs text-gray-400">
                  {it.asset.shot_count} 镜头 · {formatDuration(it.asset.duration)}
                </div>
              </div>
              {canReorder ? (
                <div className="flex flex-col">
                  <button type="button" aria-label="上移" onClick={() => move(i, -1)} disabled={i === 0 || reorder.isPending} className="px-1 text-gray-400 disabled:opacity-30 hover:text-gray-700">▲</button>
                  <button type="button" aria-label="下移" onClick={() => move(i, 1)} disabled={i === data.items.length - 1 || reorder.isPending} className="px-1 text-gray-400 disabled:opacity-30 hover:text-gray-700">▼</button>
                </div>
              ) : null}
              <Link href={`/shots?asset_id=${it.asset.id}`} className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50">
                打开
              </Link>
              {!archived ? (
                <button type="button" onClick={() => remove.mutate(it.asset.id)} data-testid={`remove-asset-${it.asset.id}`} className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50">
                  移除
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {data && data.total > pageSize ? (
        <PagerBar page={page} total={data.total} pageSize={pageSize} onChange={setPage} noun="素材" />
      ) : null}
      <MemberPicker
        open={pickerOpen}
        title="添加素材到项目"
        queryKey="assets"
        fetchPage={fetchAssets}
        pending={add.isPending}
        onClose={() => setPickerOpen(false)}
        onAdd={(ids) =>
          add.mutate(ids, {
            onSuccess: (r) => {
              setBatch(r);
              setPickerOpen(false);
            },
          })
        }
      />
    </div>
  );
}

// ============================ 镜头 Tab ============================

const REVIEW_OPTIONS: { value: "" | ReviewStatus; label: string }[] = [
  { value: "", label: "全部审核状态" },
  { value: "confirmed", label: "已确认" },
  { value: "modified", label: "已修改" },
  { value: "pending_review", label: "待审核" },
  { value: "unreviewed", label: "未审核" },
];

export function ProjectShotsTab({ project }: { project: Project }) {
  const archived = project.status === "archived";
  const [source, setSource] = useState<ProjectShotSource>("all");
  const [productId, setProductId] = useState<number | "">("");
  const [reviewStatus, setReviewStatus] = useState<"" | ReviewStatus>("");
  const [risk, setRisk] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 24;
  const products = useProducts();
  const query = useProjectShots(project.id, {
    source,
    product_id: productId === "" ? undefined : productId,
    review_status: reviewStatus === "" ? undefined : reviewStatus,
    risk: risk.trim() || undefined,
    page,
    page_size: pageSize,
  });
  const add = useAddProjectShots(project.id);
  const remove = useRemoveProjectShot(project.id);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [batch, setBatch] = useState<BatchMembershipResult | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const data = query.data;

  const reset = () => setPage(1);
  const fetchShots = (p: number): Promise<PickerPage> =>
    api.listShots({ page: p, page_size: 24 }).then((r) => ({
      total: r.total,
      items: r.items.map((s) => ({
        id: s.id,
        label: `#${s.sequence_no} ${s.asset_filename ?? ""}`,
        sub: `${s.duration.toFixed(1)}s`,
        thumbUrl: s.has_thumbnail ? shotThumbnailUrl(s.id) : undefined,
      })),
    }));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="shot-source">来源</label>
        <select id="shot-source" value={source} onChange={(e) => { setSource(e.target.value as ProjectShotSource); reset(); }} data-testid="shot-source" className="rounded border border-gray-300 px-2 py-1 text-sm">
          <option value="all">全部来源</option>
          <option value="asset">素材派生</option>
          <option value="explicit">显式加入</option>
          <option value="collection">集合内</option>
        </select>
        <label className="sr-only" htmlFor="shot-product">产品</label>
        <select id="shot-product" value={productId} onChange={(e) => { setProductId(e.target.value === "" ? "" : Number(e.target.value)); reset(); }} data-testid="shot-product" className="rounded border border-gray-300 px-2 py-1 text-sm">
          <option value="">全部产品</option>
          {(products.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <label className="sr-only" htmlFor="shot-review">审核状态</label>
        <select id="shot-review" value={reviewStatus} onChange={(e) => { setReviewStatus(e.target.value as "" | ReviewStatus); reset(); }} data-testid="shot-review" className="rounded border border-gray-300 px-2 py-1 text-sm">
          {REVIEW_OPTIONS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
        </select>
        <input value={risk} onChange={(e) => { setRisk(e.target.value); reset(); }} placeholder="风险标签…" aria-label="风险筛选" data-testid="shot-risk" className="w-28 rounded border border-gray-300 px-2 py-1 text-sm" />
        <button type="button" onClick={() => setPickerOpen(true)} disabled={archived} title={archived ? ARCHIVED_HINT : undefined} data-testid="add-shots" className="ml-auto rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark">
          + 添加显式镜头
        </button>
      </div>
      <BatchResultNotice result={batch} nounMap={{ completed: "镜头" }} />
      <InlineError error={add.error ?? remove.error} />
      {query.isLoading ? (
        <Loading rows={3} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !data || data.items.length === 0 ? (
        <Empty title="无可见镜头" description="加入素材（带来其镜头）、显式加入镜头，或在集合中加入镜头。" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {data.items.map((s) => (
              <div key={s.id} className="space-y-1">
                <ShotCard shot={s} selected={false} onSelect={(id) => setPreviewId(id)} />
                {!archived && source === "explicit" ? (
                  <button type="button" onClick={() => remove.mutate(s.id)} data-testid={`remove-shot-${s.id}`} className="w-full rounded border border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50">
                    移除显式
                  </button>
                ) : null}
              </div>
            ))}
          </div>
          {data.total > pageSize ? (
            <PagerBar page={page} total={data.total} pageSize={pageSize} onChange={setPage} noun="镜头" />
          ) : null}
        </>
      )}
      <PreviewModal shotId={previewId} onClose={() => setPreviewId(null)} />
      <MemberPicker
        open={pickerOpen}
        title="显式添加镜头到项目"
        queryKey="shots"
        searchable={false}
        fetchPage={fetchShots}
        pending={add.isPending}
        onClose={() => setPickerOpen(false)}
        onAdd={(ids) => add.mutate(ids, { onSuccess: (r) => { setBatch(r); setPickerOpen(false); } })}
      />
    </div>
  );
}

// ============================ Collections Tab ============================

export function ProjectCollectionsTab({ project }: { project: Project }) {
  const archived = project.status === "archived";
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const query = useProjectCollections(project.id, page, pageSize);
  const create = useCreateCollection(project.id);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const data = query.data;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate({ name: trimmed, description: description.trim() || undefined }, {
      onSuccess: () => { setName(""); setDescription(""); setShowCreate(false); },
    });
  };

  return (
    <div className="space-y-6">
      <section className="space-y-3" data-testid="static-collections">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">静态集合</h3>
          <span className="text-xs text-gray-500">人工挑选并固定保存镜头成员（删除集合只删关联，不删镜头）</span>
        </div>
        <button type="button" onClick={() => setShowCreate((v) => !v)} disabled={archived} title={archived ? ARCHIVED_HINT : undefined} data-testid="toggle-create-collection" className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark">
          + 新建集合
        </button>
      </div>
      {showCreate && !archived ? (
        <form onSubmit={submit} data-testid="create-collection-form" className="space-y-2 rounded-lg border border-gray-200 bg-white p-3">
          <label className="sr-only" htmlFor="coll-name">集合名称</label>
          <input id="coll-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} placeholder="如：Hook 集合 / 产品特写" className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
          <label className="sr-only" htmlFor="coll-desc">描述</label>
          <input id="coll-desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} placeholder="描述（可选）" className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
          <InlineError error={create.error} />
          <div className="flex justify-end">
            <button type="submit" disabled={!name.trim() || create.isPending} data-testid="submit-create-collection" className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark">
              {create.isPending ? "创建中…" : "创建"}
            </button>
          </div>
        </form>
      ) : null}
      {query.isLoading ? (
        <Loading rows={3} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !data || data.items.length === 0 ? (
        <Empty title="暂无集合" description="新建集合，把镜头组合为 Hook / 特写 / 补拍清单等。" />
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((c) => (
            <CollectionRow key={c.id} collection={c} projectId={project.id} archived={archived} />
          ))}
        </ul>
      )}
      {data && data.total > pageSize ? (
        <PagerBar page={page} total={data.total} pageSize={pageSize} onChange={setPage} noun="集合" />
      ) : null}
      </section>

      <div className="border-t border-gray-100 pt-4">
        <DynamicCollectionsSection projectId={project.id} archived={archived} />
      </div>
    </div>
  );
}

function CollectionRow({ collection, projectId, archived }: { collection: Collection; projectId: number; archived: boolean }) {
  const del = useDeleteCollection(collection.id, projectId);
  const [confirm, setConfirm] = useState(false);
  return (
    <li className="flex flex-col rounded-lg border border-gray-200 bg-white p-3" data-testid={`collection-${collection.id}`}>
      <div className="flex items-start justify-between gap-2">
        <Link href={`/collections/${collection.id}`} className="min-w-0 flex-1 text-sm font-medium text-gray-800 hover:text-brand" data-testid={`open-collection-${collection.id}`}>
          <span className="block truncate">{collection.name}</span>
        </Link>
        <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">{collection.shot_count} 镜头</span>
      </div>
      {collection.description ? (<p className="mt-1 line-clamp-2 text-xs text-gray-500">{collection.description}</p>) : null}
      <div className="mt-2 flex items-center justify-between border-t border-gray-100 pt-2 text-[11px] text-gray-400">
        <span>更新于 {formatDateTime(collection.updated_at)}</span>
        {!archived ? (
          <button type="button" onClick={() => setConfirm(true)} data-testid={`delete-collection-${collection.id}`} className="rounded border border-gray-300 px-2 py-0.5 text-gray-600 hover:bg-gray-50">删除</button>
        ) : null}
      </div>
      <InlineError error={del.error} />
      <ConfirmDialog
        open={confirm}
        title="删除集合"
        message="只删除集合和关联，不删除镜头。确定删除该集合？"
        confirmLabel="删除集合"
        pending={del.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => del.mutate(undefined, { onSuccess: () => setConfirm(false) })}
      />
    </li>
  );
}

// ============================ 产品 Tab ============================

export function ProjectProductsTab({ project }: { project: Project }) {
  const archived = project.status === "archived";
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const query = useProjectProducts(project.id, page, pageSize);
  const add = useAddProjectProducts(project.id);
  const remove = useRemoveProjectProduct(project.id);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [batch, setBatch] = useState<BatchMembershipResult | null>(null);
  const data = query.data;

  const fetchProducts = (_p: number, q: string): Promise<PickerPage> =>
    api.listProducts(q || undefined).then((items) => ({
      total: items.length,
      items: items.map((p) => ({ id: p.id, label: p.name, sub: p.brand ?? undefined })),
    }));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-500">项目关注/允许的产品（仅引用，不改产品库与确认绑定）</span>
        <button type="button" onClick={() => setPickerOpen(true)} disabled={archived} title={archived ? ARCHIVED_HINT : undefined} data-testid="add-products" className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark">+ 添加产品</button>
      </div>
      <BatchResultNotice result={batch} nounMap={{ completed: "产品" }} />
      <InlineError error={add.error ?? remove.error} />
      {query.isLoading ? (
        <Loading rows={2} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !data || data.items.length === 0 ? (
        <Empty title="暂无产品引用" description="添加产品，便于在项目内按产品筛选镜头。" />
      ) : (
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
          {data.items.map((p) => (
            <li key={p.id} className="flex items-center gap-3 px-3 py-2" data-testid={`project-product-${p.id}`}>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-gray-800">{p.name}</div>
                {p.brand ? (<div className="text-xs text-gray-400">{p.brand}</div>) : null}
              </div>
              {!archived ? (
                <button type="button" onClick={() => remove.mutate(p.id)} data-testid={`remove-product-${p.id}`} className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50">移除</button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <MemberPicker open={pickerOpen} title="添加产品引用" queryKey="products" fetchPage={fetchProducts} pending={add.isPending} onClose={() => setPickerOpen(false)} onAdd={(ids) => add.mutate(ids, { onSuccess: (r) => { setBatch(r); setPickerOpen(false); } })} />
    </div>
  );
}

// ============================ 脚本 Tab ============================

export function ProjectScriptsTab({ project }: { project: Project }) {
  const archived = project.status === "archived";
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const query = useProjectScripts(project.id, page, pageSize);
  const stats = useProjectStats(project.id, true);
  const attach = useAttachProjectScript(project.id);
  const detach = useDetachProjectScript(project.id);
  const [pickerOpen, setPickerOpen] = useState(false);
  const data = query.data;

  const fetchScripts = (p: number): Promise<PickerPage> =>
    api.listScripts(p, 20).then((r) => ({
      total: r.total,
      items: r.items.map((sp) => ({ id: sp.id, label: sp.name, sub: `${sp.segment_count} 段 · ${sp.status}` })),
    }));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500">
          已关联脚本
          {stats.data ? (
            <span className="ml-2 text-xs text-gray-400" data-testid="scripts-lockgap-summary">
              锁定段 {stats.data.locked_segment_count} · 缺口段 {stats.data.gap_segment_count}
            </span>
          ) : null}
        </div>
        <button type="button" onClick={() => setPickerOpen(true)} disabled={archived} title={archived ? ARCHIVED_HINT : undefined} data-testid="attach-script" className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-dark">+ 关联脚本</button>
      </div>
      <InlineError error={attach.error ?? detach.error} />
      {query.isLoading ? (
        <Loading rows={2} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !data || data.items.length === 0 ? (
        <Empty title="暂无关联脚本" description="关联已有脚本项目；attach/detach 不修改脚本内容、候选或锁定。" />
      ) : (
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
          {data.items.map((sp) => (
            <li key={sp.id} className="flex items-center gap-3 px-3 py-2" data-testid={`project-script-${sp.id}`}>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-gray-800">{sp.name}</div>
                <div className="text-xs text-gray-400">{sp.segment_count} 段 · {sp.status}</div>
              </div>
              <Link href={`/script/${sp.id}`} className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50">打开</Link>
              {!archived ? (
                <button type="button" onClick={() => detach.mutate(sp.id)} data-testid={`detach-script-${sp.id}`} className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50">解除关联</button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {data && data.total > pageSize ? (
        <PagerBar page={page} total={data.total} pageSize={pageSize} onChange={setPage} noun="脚本" />
      ) : null}
      <MemberPicker open={pickerOpen} title="关联脚本到项目" queryKey="scripts" searchable={false} fetchPage={fetchScripts} pending={attach.isPending} onClose={() => setPickerOpen(false)} onAdd={(ids) => { ids.forEach((sid) => attach.mutate(sid)); setPickerOpen(false); }} />
    </div>
  );
}

// ============================ 简易分页条 ============================

function PagerBar({ page, total, pageSize, onChange, noun }: { page: number; total: number; pageSize: number; onChange: (p: number) => void; noun: string }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between px-1 py-1 text-sm text-gray-500">
      <span>共 {total} 个{noun} · 第 {page}/{totalPages} 页</span>
      <div className="flex gap-2">
        <button type="button" onClick={() => onChange(page - 1)} disabled={page <= 1} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">上一页</button>
        <button type="button" onClick={() => onChange(page + 1)} disabled={page >= totalPages} className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">下一页</button>
      </div>
    </div>
  );
}
