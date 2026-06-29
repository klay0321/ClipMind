import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FavoritesView } from "@/components/favorites/FavoritesView";
import { FavoriteButton } from "@/components/favorites/FavoriteButton";
import * as hooks from "@/lib/hooks";

import { makeFavorite, mutation, query } from "./fixtures";

vi.mock("@/lib/hooks", () => ({
  useFavorites: vi.fn(),
  useDeleteFavorite: vi.fn(),
  useCreateFavorite: vi.fn(),
}));

function renderC(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function favList(items = [makeFavorite()], total = items.length) {
  return query({ data: { items, total, page: 1, page_size: 24 } });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hooks.useFavorites).mockReturnValue(favList());
  vi.mocked(hooks.useDeleteFavorite).mockReturnValue(mutation());
  vi.mocked(hooks.useCreateFavorite).mockReturnValue(mutation());
});

describe("FavoritesView", () => {
  it("渲染收藏项 + 四种类型筛选按钮", () => {
    renderC(<FavoritesView />);
    expect(screen.getByTestId("favorites")).toBeInTheDocument();
    expect(screen.getByTestId("favorite-item-1")).toBeInTheDocument();
    for (const t of ["shot", "search_result", "script_match_result", "asset"]) {
      expect(screen.getByTestId(`favorite-filter-${t}`)).toBeInTheDocument();
    }
  });

  it("切换类型筛选 → aria-pressed 更新", async () => {
    const user = userEvent.setup();
    renderC(<FavoritesView />);
    const assetBtn = screen.getByTestId("favorite-filter-asset");
    await user.click(assetBtn);
    expect(assetBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("移除收藏调用 deleteFavorite mutate", async () => {
    const del = mutation();
    vi.mocked(hooks.useDeleteFavorite).mockReturnValue(del);
    const user = userEvent.setup();
    renderC(<FavoritesView />);
    await user.click(screen.getByTestId("remove-favorite-1"));
    expect(del.mutate).toHaveBeenCalledWith(1);
  });

  it("素材类型收藏 → 打开素材关联镜头库链接", () => {
    vi.mocked(hooks.useFavorites).mockReturnValue(
      favList([
        makeFavorite({
          id: 2,
          target_type: "asset",
          shot_id: null,
          shot: null,
          asset_id: 10,
          asset: { id: 10, filename: "demo.mp4", duration: 12, width: 1080, height: 1920 },
        }),
      ]),
    );
    renderC(<FavoritesView />);
    const link = screen.getByText("打开");
    expect(link).toHaveAttribute("href", "/shots?asset_id=10");
  });

  it("空态显示空提示", () => {
    vi.mocked(hooks.useFavorites).mockReturnValue(favList([], 0));
    renderC(<FavoritesView />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
  });
});

describe("FavoriteButton", () => {
  it("点击 → 用目标类型与 shotId 调创建收藏", async () => {
    const create = mutation();
    vi.mocked(hooks.useCreateFavorite).mockReturnValue(create);
    const user = userEvent.setup();
    renderC(<FavoriteButton targetType="shot" shotId={55} />);
    await user.click(screen.getByTestId("favorite-btn"));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ target_type: "shot", shot_id: 55 }),
      expect.anything(),
    );
  });

  it("素材收藏携带 asset_id", async () => {
    const create = mutation();
    vi.mocked(hooks.useCreateFavorite).mockReturnValue(create);
    const user = userEvent.setup();
    renderC(<FavoriteButton targetType="asset" assetId={10} />);
    await user.click(screen.getByTestId("favorite-btn"));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ target_type: "asset", asset_id: 10 }),
      expect.anything(),
    );
  });
});
