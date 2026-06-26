import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DegradedNotice } from "@/components/search/DegradedNotice";
import { MatchExplanation } from "@/components/search/MatchExplanation";
import { MatchScore } from "@/components/search/MatchScore";
import { ScoreBreakdown } from "@/components/search/ScoreBreakdown";
import { RecommendationBadge, ReviewStatusBadge } from "@/components/search/SearchBadges";

import { makeItem } from "./fixtures";

describe("DegradedNotice", () => {
  it("全正常时不渲染（正常模式不长期显示 degraded）", () => {
    const { container } = render(<DegradedNotice parserStatus="ok" embeddingStatus="ok" />);
    expect(container.firstChild).toBeNull();
  });
  it("parser/embedding/index 降级分别渲染对应提示", () => {
    render(
      <DegradedNotice
        parserStatus="degraded"
        embeddingStatus="unavailable"
        indexBuilding
        degradationReasons={["parser_degraded"]}
      />,
    );
    expect(screen.getByTestId("degraded-parser")).toBeInTheDocument();
    expect(screen.getByTestId("degraded-embedding")).toBeInTheDocument();
    expect(screen.getByTestId("degraded-index")).toBeInTheDocument();
    // 中性提示，不是错误态
    expect(screen.getByTestId("degraded-notice")).toHaveAttribute("role", "status");
  });
});

describe("ScoreBreakdown", () => {
  it("缺失通道显示未参与（绝不当 0），有值显示百分比", () => {
    render(<ScoreBreakdown item={makeItem({ semantic_score: null, lexical_score: 0.5 })} />);
    const box = screen.getByTestId("score-breakdown");
    expect(box).toHaveTextContent("未参与");
    expect(box).toHaveTextContent("50%");
  });
});

describe("MatchExplanation", () => {
  it("渲染匹配理由 / 不匹配项 / 风险提示三组", () => {
    render(
      <MatchExplanation
        matchedReasons={["产品匹配：X10"]}
        unmatched={["场景仅相似"]}
        riskWarnings={["competitor"]}
      />,
    );
    expect(screen.getByTestId("matched-reasons")).toHaveTextContent("产品匹配：X10");
    expect(screen.getByTestId("unmatched-requirements")).toHaveTextContent("场景仅相似");
    expect(screen.getByTestId("risk-warnings")).toHaveTextContent("competitor");
  });
  it("三组皆空时不渲染", () => {
    const { container } = render(
      <MatchExplanation matchedReasons={[]} unmatched={[]} riskWarnings={[]} />,
    );
    expect(container.firstChild).toBeNull();
  });
});

describe("徽章与匹配分", () => {
  it("MatchScore 标注综合匹配度且取整", () => {
    render(<MatchScore matchPercent={64.3} />);
    const el = screen.getByTestId("match-score");
    expect(el).toHaveTextContent("综合匹配度");
    expect(el).toHaveTextContent("64%");
  });
  it("推荐等级与审核状态徽章带文字（颜色非唯一信息）", () => {
    render(
      <div>
        <RecommendationBadge level="high" />
        <ReviewStatusBadge status="confirmed" />
      </div>,
    );
    expect(screen.getByText("强烈推荐")).toBeInTheDocument();
    expect(screen.getByText("审核：已确认")).toBeInTheDocument();
  });
});
