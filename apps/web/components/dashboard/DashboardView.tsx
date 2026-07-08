"use client";

import Link from "next/link";

import { TopNav } from "@/components/TopNav";
import { cn } from "@/lib/cn";
import {
  usePipelineHealth,
  usePmSummary,
  usePmUnassigned,
  useProcessingOverview,
  useUsageReviewSummary,
} from "@/lib/hooks";

// 运营仪表盘：只聚合既有 API 的真实数字（处理概览 / 产品覆盖 / 使用记录待办），
// 各区块独立加载与降级，不因单个接口失败而整页空白；不展示未实现能力。
export function DashboardView() {
  return (
    <div className="min-h-screen bg-gray-50">
      <TopNav active="dashboard" />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <h1 className="text-xl font-semibold text-gray-800">运营总览</h1>
        <p className="mb-5 mt-0.5 text-sm text-gray-500">
          素材处理进度、产品归类覆盖与待人工处理事项一屏总览，点击卡片直达对应工作台。
        </p>
        <div className="space-y-5">
          <PipelineSection />
          <PipelineHealthSection />
          <div className="grid gap-5 lg:grid-cols-2">
            <ProductCoverageSection />
            <UsageTodoSection />
          </div>
          <QuickLinksSection />
        </div>
      </main>
    </div>
  );
}

function SectionCard({
  title,
  action,
  children,
  testId,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <section
      className="rounded-lg border border-gray-200 bg-white p-4"
      data-testid={testId}
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-gray-700">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  href,
  tone = "gray",
  testId,
}: {
  label: string;
  value: number | string;
  href?: string;
  tone?: "gray" | "brand" | "emerald" | "amber";
  testId?: string;
}) {
  const tones: Record<string, string> = {
    gray: "border-gray-200 bg-white text-gray-800",
    brand: "border-brand/30 bg-brand/5 text-brand",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
  };
  const body = (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5",
        tones[tone],
        href ? "transition hover:shadow-sm" : undefined,
      )}
      data-testid={testId}
    >
      <div className="text-2xl font-semibold">{value}</div>
      <div className="mt-0.5 text-xs opacity-75">{label}</div>
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

function LoadingRow() {
  return <div className="h-16 animate-pulse rounded-lg bg-gray-100" />;
}

// OBS：管线健康——各环节滞后/失败计数（0=健康隐藏，非零才占视线）+ 队列积压
const HEALTH_LABELS: Record<string, string> = {
  assets_no_shots: "视频无镜头",
  shots_ai_missing: "镜头缺 AI",
  ai_failed: "AI 失败",
  img_ai_missing: "图片缺 AI 理解",
  runs_stuck_running: "运行卡住 >2h",
  shot_docs_missing: "镜头缺检索文档",
  shot_docs_degraded: "向量降级",
  asset_docs_missing: "素材缺检索文档",
  visual_emb_failed: "视觉向量失败",
};

const HEALTH_SEVERE = new Set(["ai_failed", "runs_stuck_running", "visual_emb_failed"]);

function PipelineHealthSection() {
  const health = usePipelineHealth();
  const d = health.data;
  if (health.isError) {
    return (
      <SectionCard title="管线健康" testId="dash-health">
        <p className="text-xs text-gray-400">健康数据暂不可用</p>
      </SectionCard>
    );
  }
  if (!d) {
    return (
      <SectionCard title="管线健康" testId="dash-health">
        <LoadingRow />
      </SectionCard>
    );
  }
  const issues = Object.entries(d.counters).filter(([, v]) => v > 0);
  const queued = Object.entries(d.queues).filter(([, v]) => (v ?? 0) > 0);
  const allGreen = issues.length === 0;
  return (
    <SectionCard
      title="管线健康"
      testId="dash-health"
      action={
        <span
          className={cn(
            "rounded px-2 py-0.5 text-xs",
            allGreen ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700",
          )}
          data-testid="dash-health-badge"
        >
          {allGreen ? "全部环节正常" : `${issues.length} 项待处理`}
        </span>
      }
    >
      {allGreen ? (
        <p className="text-xs text-gray-400" data-testid="dash-health-ok">
          扫描 → 拆镜头 → AI → 检索文档 → 向量 全链无滞后、无失败。
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4" data-testid="dash-health-issues">
          {issues.map(([k, v]) => (
            <Stat
              key={k}
              label={HEALTH_LABELS[k] ?? k}
              value={v}
              tone={HEALTH_SEVERE.has(k) ? "amber" : "gray"}
              testId={`health-${k}`}
            />
          ))}
        </div>
      )}
      {queued.length > 0 ? (
        <p className="mt-2 text-xs text-gray-500" data-testid="dash-health-queues">
          队列积压：{queued.map(([q, v]) => `${q} ${v}`).join("、")}
        </p>
      ) : null}
    </SectionCard>
  );
}

function PipelineSection() {
  const overview = useProcessingOverview();
  const d = overview.data;
  if (overview.isError) {
    return (
      <SectionCard title="素材处理进度" testId="dash-pipeline">
        <p className="text-xs text-gray-400">处理概览暂不可用</p>
      </SectionCard>
    );
  }
  if (!d) {
    return (
      <SectionCard title="素材处理进度" testId="dash-pipeline">
        <LoadingRow />
      </SectionCard>
    );
  }
  const active =
    d.scan.queued + d.scan.running + d.shots.queued + d.shots.running +
    d.ai.queued + d.ai.running;
  return (
    <SectionCard
      title="素材处理进度"
      testId="dash-pipeline"
      action={
        <span
          className={cn(
            "rounded px-2 py-0.5 text-xs",
            active > 0 ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-500",
          )}
          data-testid="dash-active-jobs"
        >
          {active > 0 ? `${active} 个任务处理中` : "管线空闲"}
        </span>
      }
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="视频素材" value={d.totals.videos_total} href="/assets" testId="dash-videos-total" />
        <Stat label="已拆镜头" value={d.totals.videos_with_shots} href="/assets" />
        <Stat label="可用镜头" value={d.totals.shots_ready} href="/shots" />
        <Stat label="AI 已理解镜头" value={d.totals.shots_ai_labeled} href="/shots" tone="emerald" />
        <Stat label="图片素材" value={d.totals.images_total} href="/assets" />
        <Stat label="可搜索素材文档" value={d.totals.searchable_docs} href="/search" tone="brand" />
      </div>
      <p className="mt-3 text-xs text-gray-400">
        自动扫描每 {d.config.scan_interval_minutes} 分钟一次；
        扫描后自动拆镜头{d.config.auto_analyze_on_scan ? "已开启" : "已关闭"}、
        拆完自动 AI 理解{d.config.auto_ai_after_shots ? "已开启" : "已关闭"}。
        {d.config.ai_daily_budget > 0
          ? ` 今日 AI 花费 $${d.config.ai_spent_today.toFixed(4)} / 预算 $${d.config.ai_daily_budget}。`
          : ""}
      </p>
    </SectionCard>
  );
}

function ProductCoverageSection() {
  const summary = usePmSummary();
  // 只取 total 计数（page_size 最小页即可），用于「待归类」提示
  const unImg = usePmUnassigned("image", 1);
  const unVid = usePmUnassigned("video", 1);
  if (summary.isError) {
    return (
      <SectionCard title="产品素材覆盖" testId="dash-products">
        <p className="text-xs text-gray-400">产品覆盖统计暂不可用</p>
      </SectionCard>
    );
  }
  const families = summary.data;
  if (!families) {
    return (
      <SectionCard title="产品素材覆盖" testId="dash-products">
        <LoadingRow />
      </SectionCard>
    );
  }
  const withMedia = families.filter(
    (f) => f.image_count + f.video_count + f.shot_link_count > 0,
  ).length;
  const images = families.reduce((s, f) => s + f.image_count, 0);
  const videos = families.reduce((s, f) => s + f.video_count, 0);
  const unassigned = (unImg.data?.total ?? 0) + (unVid.data?.total ?? 0);
  return (
    <SectionCard
      title="产品素材覆盖"
      testId="dash-products"
      action={
        <Link href="/product-media" className="text-xs text-brand hover:underline">
          去产品工作台 →
        </Link>
      }
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="产品数" value={families.length} href="/products" testId="dash-family-count" />
        <Stat label="有素材的产品" value={withMedia} href="/product-media" />
        <Stat label="已归类图片" value={images} href="/product-media" />
        <Stat label="已归类视频" value={videos} href="/product-media" />
      </div>
      {unImg.data || unVid.data ? (
        <p className="mt-3 text-xs" data-testid="dash-unassigned">
          {unassigned > 0 ? (
            <Link href="/product-media" className="text-amber-700 hover:underline">
              还有 {unassigned} 条素材未归类到产品 →
            </Link>
          ) : (
            <span className="text-gray-400">素材已全部归类到产品</span>
          )}
        </p>
      ) : null}
    </SectionCard>
  );
}

function UsageTodoSection() {
  const summary = useUsageReviewSummary();
  if (summary.isError) {
    return (
      <SectionCard title="使用记录待办" testId="dash-usage">
        <p className="text-xs text-gray-400">使用记录统计暂不可用</p>
      </SectionCard>
    );
  }
  const s = summary.data;
  if (!s) {
    return (
      <SectionCard title="使用记录待办" testId="dash-usage">
        <LoadingRow />
      </SectionCard>
    );
  }
  return (
    <SectionCard
      title="使用记录待办"
      testId="dash-usage"
      action={
        <Link href="/usage-review" className="text-xs text-brand hover:underline">
          去使用记录中心 →
        </Link>
      }
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="待人工处理"
          value={s.needs_review_total}
          href="/usage-review"
          tone={s.needs_review_total > 0 ? "amber" : "gray"}
          testId="dash-needs-review"
        />
        <Stat label="正式确认使用" value={s.formal.confirmed} href="/usage-review" tone="emerald" />
        <Stat
          label="正式候选"
          value={s.formal.proposed + s.formal.suspected}
          href="/usage-review"
        />
        <Stat label="历史证据待审核" value={s.legacy.pending} href="/usage-review" />
      </div>
    </SectionCard>
  );
}

const QUICK_LINKS = [
  { href: "/assets", label: "素材库", desc: "浏览与管理已索引素材" },
  { href: "/search", label: "搜索", desc: "按描述找镜头 / 视频 / 图片" },
  { href: "/shots", label: "镜头库", desc: "镜头浏览与 AI 结果审核" },
  { href: "/product-media", label: "产品", desc: "产品素材与目录维护" },
  { href: "/projects", label: "项目", desc: "项目与镜头集合" },
  { href: "/usage-review", label: "使用记录", desc: "使用审核与成片登记" },
];

function QuickLinksSection() {
  return (
    <SectionCard title="快捷入口" testId="dash-quick-links">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {QUICK_LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="rounded-lg border border-gray-200 px-3 py-2.5 transition hover:border-brand/50 hover:shadow-sm"
          >
            <div className="text-sm font-medium text-gray-800">{l.label}</div>
            <div className="mt-0.5 text-xs text-gray-400">{l.desc}</div>
          </Link>
        ))}
      </div>
    </SectionCard>
  );
}
