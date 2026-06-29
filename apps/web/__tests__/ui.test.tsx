import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/Button";
import { MediaThumb } from "@/components/ui/MediaThumb";
import { Menu } from "@/components/ui/Menu";
import { Pagination } from "@/components/Pagination";

describe("Button", () => {
  it("loading 时 aria-busy 且禁用，防止重复点击", () => {
    render(
      <Button loading onClick={() => {}}>
        提交
      </Button>,
    );
    const btn = screen.getByRole("button", { name: /提交/ });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
  });
});

describe("MediaThumb 媒体兜底", () => {
  it("无 src 显示无缩略图占位", () => {
    render(<MediaThumb src={null} alt="封面" />);
    expect(screen.getByTestId("media-fallback")).toHaveTextContent("无缩略图");
  });

  it("加载失败回退到错误占位，不显示破图", () => {
    render(<MediaThumb src="http://x/broken.jpg" alt="封面" />);
    const img = screen.getByAltText("封面");
    fireEvent.error(img);
    expect(screen.getByTestId("media-fallback")).toHaveTextContent("缩略图加载失败");
  });
});

describe("Menu 溢出菜单", () => {
  it("点击展开、选择触发回调、Esc 关闭", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <Menu
        items={[{ key: "a", label: "重新扫描", onSelect }]}
        triggerAriaLabel="更多操作"
      />,
    );
    await user.click(screen.getByRole("button", { name: "更多操作" }));
    await user.click(screen.getByRole("menuitem", { name: "重新扫描" }));
    expect(onSelect).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "更多操作" }));
    expect(screen.getByRole("menuitem", { name: "重新扫描" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menuitem", { name: "重新扫描" })).not.toBeInTheDocument();
  });
});

describe("Pagination 页码", () => {
  it("渲染页码并可跳转，超过 7 页显示省略号", async () => {
    const onPageChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Pagination page={5} pageSize={20} total={200} onPageChange={onPageChange} noun="素材" />,
    );
    expect(screen.getByText(/共 200 个素材/)).toBeInTheDocument();
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "6" }));
    expect(onPageChange).toHaveBeenCalledWith(6);
    // 当前页高亮
    expect(screen.getByRole("button", { name: "5" })).toHaveAttribute("aria-current", "page");
  });
});
