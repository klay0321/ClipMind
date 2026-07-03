import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  UsageAdvancedFilters,
  UsageModePills,
} from "@/components/search/UsageControls";
import { UsageBadge, UsageExplanation } from "@/components/search/UsageBadge";
import {
  EMPTY_SEARCH_FORM,
  buildSearchRequest,
  hasSearchSignal,
  requestToForm,
} from "@/lib/search";
import type { SearchResultItem, SearchUsageInfo } from "@/lib/types";

function makeUsage(o: Partial<SearchUsageInfo> = {}): SearchUsageInfo {
  return {
    shot_confirmed_usage_count: 0,
    shot_distinct_final_video_count: 0,
    asset_confirmed_usage_count: 0,
    asset_distinct_final_video_count: 0,
    asset_used_shot_count: 0,
    asset_total_current_shot_count: 0,
    last_confirmed_used_at: null,
    days_since_last_confirmed_use: null,
    accepted_legacy_evidence_count: 0,
    pending_formal_count: 0,
    usage_state: "never_confirmed_used",
    ...o,
  };
}

describe("buildSearchRequest 使用感知（default parity）", () => {
  it("default 模式不带任何 usage 字段（请求与旧实现完全一致）", () => {
    const req = buildSearchRequest({ ...EMPTY_SEARCH_FORM, query: "测试" }, 1, 24);
    expect(req).not.toHaveProperty("usage_mode");
    expect(req).not.toHaveProperty("usage_scope");
    expect(req).not.toHaveProperty("usage_preset");
    expect(req).not.toHaveProperty("include_usage_explanation");
  });

  it("非 default 模式携带 usage 字段；阈值可独立触发", () => {
    const req = buildSearchRequest(
      { ...EMPTY_SEARCH_FORM, query: "q", usageMode: "prefer_unused", usagePreset: "strong_unused" },
      1,
      24,
    );
    expect(req.usage_mode).toBe("prefer_unused");
    expect(req.usage_preset).toBe("strong_unused");
    const req2 = buildSearchRequest(
      { ...EMPTY_SEARCH_FORM, query: "q", maxConfirmedUsage: "2" },
      1,
      24,
    );
    expect(req2.usage_mode).toBe("default");
    expect(req2.max_confirmed_usage_count).toBe(2);
  });

  it("usage 条件本身是合法搜索信号（无查询词也可浏览）", () => {
    expect(hasSearchSignal(EMPTY_SEARCH_FORM)).toBe(false);
    expect(hasSearchSignal({ ...EMPTY_SEARCH_FORM, usageMode: "only_never_confirmed" })).toBe(true);
    expect(hasSearchSignal({ ...EMPTY_SEARCH_FORM, maxConfirmedUsage: "2" })).toBe(true);
    expect(hasSearchSignal({ ...EMPTY_SEARCH_FORM, excludeRecentDays: "30" })).toBe(true);
  });

  it("Saved Search 往返恢复（老数据缺字段回退 default）", () => {
    const form = {
      ...EMPTY_SEARCH_FORM,
      query: "口红",
      usageMode: "only_never_confirmed" as const,
      excludeRecentDays: "30",
      usagePreset: "relevance_first" as const,
      includeLegacyUnknown: false,
    };
    const restored = requestToForm(buildSearchRequest(form, 1, 24));
    expect(restored.usageMode).toBe("only_never_confirmed");
    expect(restored.excludeRecentDays).toBe("30");
    expect(restored.usagePreset).toBe("relevance_first");
    expect(restored.includeLegacyUnknown).toBe(false);
    // 老 Saved Search（无 usage 字段）→ default
    const legacy = requestToForm({ query: "旧保存", page: 1, page_size: 24 });
    expect(legacy.usageMode).toBe("default");
    expect(legacy.usagePreset).toBe("balanced");
  });
});

describe("UsageModePills", () => {
  it("渲染五档快捷模式并回调选择", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<UsageModePills value="default" onSelect={onSelect} />);
    for (const key of [
      "default", "prefer_unused", "only_never_confirmed",
      "exclude_high_frequency", "least_recently_used",
    ]) {
      expect(screen.getByTestId(`usage-mode-${key}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("usage-mode-default")).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByTestId("usage-mode-prefer_unused"));
    expect(onSelect).toHaveBeenCalledWith("prefer_unused");
  });
});

describe("UsageAdvancedFilters", () => {
  it("阈值/范围/预设/开关全部可交互", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<UsageAdvancedFilters form={EMPTY_SEARCH_FORM} onChange={onChange} />);
    await user.type(screen.getByTestId("usage-max-count"), "3");
    expect(onChange).toHaveBeenCalledWith({ maxConfirmedUsage: "3" });
    await user.selectOptions(screen.getByTestId("usage-scope"), "shot");
    expect(onChange).toHaveBeenCalledWith({ usageScope: "shot" });
    await user.selectOptions(screen.getByTestId("usage-preset"), "strong_unused");
    expect(onChange).toHaveBeenCalledWith({ usagePreset: "strong_unused" });
    await user.click(screen.getByTestId("usage-include-legacy"));
    expect(onChange).toHaveBeenCalledWith({ includeLegacyUnknown: false });
  });
});

describe("UsageBadge 冻结文案", () => {
  it("confirmed 显示正式次数并链接使用记录中心", () => {
    render(
      <UsageBadge usage={makeUsage({ shot_confirmed_usage_count: 3, usage_state: "confirmed_used" })} />,
    );
    const badge = screen.getByTestId("usage-badge-confirmed");
    expect(badge).toHaveTextContent("正式使用 3 次");
    expect(badge).toHaveAttribute("href", "/usage-review");
  });

  it("未使用显示未正式使用", () => {
    render(<UsageBadge usage={makeUsage()} />);
    expect(screen.getByTestId("usage-badge-never")).toHaveTextContent("未正式使用");
  });

  it("legacy 显示历史上可能使用过——绝不带数字次数", () => {
    render(
      <UsageBadge
        usage={makeUsage({ accepted_legacy_evidence_count: 5, usage_state: "legacy_used_unknown" })}
      />,
    );
    const badge = screen.getByTestId("usage-badge-legacy");
    expect(badge).toHaveTextContent("历史上可能使用过（次数未知）");
    expect(badge.textContent).not.toMatch(/\d/);
    expect(badge).toHaveAttribute("href", "/usage-evidence");
  });

  it("proposed 显示待确认——绝不显示成已使用", () => {
    render(<UsageBadge usage={makeUsage({ pending_formal_count: 2 })} />);
    expect(screen.getByTestId("usage-badge-pending")).toHaveTextContent("存在待确认使用记录");
    expect(screen.queryByText(/正式使用 \d+ 次/)).toBeNull();
    expect(screen.getByTestId("usage-badge-never")).toBeInTheDocument();
  });
});

describe("UsageExplanation 排序解释", () => {
  it("展示 base + 各调整项 + 最终分（绝不只给一个推荐分）", () => {
    const item = {
      base_score: 0.82,
      usage_adjustment: -0.06,
      final_score: 0.76,
      usage_reasons: [
        { code: "shot_used_multiple_times", adjustment: -0.04, message: "该镜头已被 2 条成片确认使用" },
        { code: "shot_recently_used", adjustment: -0.02, message: "该镜头最近 5 天内被使用过" },
      ],
    } as unknown as SearchResultItem;
    render(<UsageExplanation item={item} />);
    const box = screen.getByTestId("usage-explanation");
    expect(box).toHaveTextContent("语义相关度");
    expect(box).toHaveTextContent("0.8200");
    expect(screen.getByTestId("reason-shot_used_multiple_times")).toHaveTextContent("-0.0400");
    expect(box).toHaveTextContent("最终分数");
    expect(box).toHaveTextContent("0.7600");
  });
});
