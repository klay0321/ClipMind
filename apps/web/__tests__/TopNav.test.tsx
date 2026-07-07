import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TopNav } from "@/components/TopNav";

describe("TopNav P2b 导航重组", () => {
  it("主导航为 6 个运营入口", () => {
    render(<TopNav active="assets" />);
    const nav = screen.getByRole("navigation", { name: "主导航" });
    const labels = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(labels).toEqual(["素材库", "搜索", "镜头库", "产品", "项目", "使用记录"]);
  });

  it("脚本剪辑 / 导出 / 收藏收进「更多」菜单", async () => {
    const user = userEvent.setup();
    render(<TopNav active="assets" />);
    await user.click(screen.getByTestId("nav-more"));
    expect(screen.getByTestId("nav-script")).toHaveTextContent("脚本剪辑");
    expect(screen.getByTestId("nav-exports")).toHaveTextContent("导出");
    expect(screen.getByTestId("nav-favorites")).toHaveTextContent("收藏");
  });

  it("子页 active 别名高亮到所属主入口（成片/证据→使用记录，目录→产品）", () => {
    const { rerender } = render(<TopNav active="final-videos" />);
    expect(screen.getByTestId("nav-usage-review")).toHaveAttribute("aria-current", "page");

    rerender(<TopNav active="usage-evidence" />);
    expect(screen.getByTestId("nav-usage-review")).toHaveAttribute("aria-current", "page");

    rerender(<TopNav active="products" />);
    expect(screen.getByTestId("nav-products-hub")).toHaveAttribute("aria-current", "page");
  });

  it("品牌区链接到仪表盘首页", () => {
    render(<TopNav />);
    expect(screen.getByTestId("nav-home")).toHaveAttribute("href", "/");
  });
});
