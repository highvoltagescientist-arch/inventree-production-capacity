import React from "react";
import { MantineProvider } from "@mantine/core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CapacityDashboard, CapacityPanel, renderDashboardItem } from "../src/Capacity";

const result = {
  part: 1,
  name: "製品A",
  ipn: "A-001",
  status: "warning",
  current_capacity: 8,
  future_capacity: 12,
  minimum: 10,
  shortfall: 2,
  can_edit_minimum: true,
  monitored: true,
  material_limits: [],
  bom_hierarchy: [],
  purchase_shortages: [],
  manufacturing_suggestions: [],
  warnings: [],
  calculated_at: "2026-10-31T00:00:00Z",
};
function context(get = vi.fn().mockResolvedValue({ data: result })) {
  return {
    id: 1,
    navigate: vi.fn(),
    api: {
      get,
      patch: vi.fn().mockResolvedValue({ data: {} }),
      options: vi.fn().mockImplementation((url: string) => Promise.resolve({ data: {
        actions: { POST: url === "/api/build/"
          ? { reference: {}, part: {}, title: {}, quantity: {}, priority: {}, target_date: {}, tags: { type: "list" } }
          : { order: {}, part: {}, quantity: {}, purchase_price: {}, target_date: {}, notes: {} },
        },
      } })),
    },
  };
}
function show(component: React.ReactNode) {
  return render(<MantineProvider>{component}</MantineProvider>);
}

describe("capacity UI", () => {
  it("shows all BOM levels initially and can fold a subassembly", async () => {
    const ctx = context(vi.fn().mockResolvedValue({ data: {
      ...result,
      bom_hierarchy: [
        { part: 1, name: "製品A", ipn: "", path: "", depth: 0, kind: "assembly", available: "0", children: true, additional_capacity: 3 },
        { part: 2, name: "組立X", ipn: "", path: "0", depth: 1, kind: "assembly", available: "2", children: true, additional_capacity: 4 },
        { part: 3, name: "材料Y", ipn: "", path: "0/0", depth: 2, kind: "material", available: "10", children: false },
      ],
    }}));
    show(<CapacityPanel context={ctx} />);
    await screen.findByText("材料Y");
    expect(screen.getByText("組立X").closest("tr")?.textContent).toContain("4 個");
    fireEvent.click(screen.getByRole("button", { name: "組立Xを折りたたむ" }));
    expect(screen.queryByText("材料Y")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "組立Xを展開" }));
    expect(screen.getByText("材料Y")).toBeTruthy();
  });
  it("lists every material limit in ascending order even when overall capacity is zero", async () => {
    const ctx = context(
      vi.fn().mockResolvedValue({
        data: {
          ...result,
          current_capacity: 0,
          minimum: 0,
          material_limits: [
            { part: 2, name: "外箱", ipn: "BOX", capacity: 0, available: "0", allocated: "0", incoming: "0", scheduled: "0", capacity_capped: false },
            { part: 3, name: "皿ねじ M3x5", ipn: "SCREW", capacity: 6, available: "30", allocated: "0", incoming: "0", scheduled: "0", capacity_capped: false },
          ],
        },
      }),
    );
    show(<CapacityPanel context={ctx} />);
    await screen.findByText("BOX · 外箱");
    const rows = screen.getAllByRole("row");
    expect(rows[1].textContent).toContain("0 個");
    expect(rows[2].textContent).toContain("6 個");
    expect(screen.getByText(/上の材料別上限は最低製造余力/)).toBeTruthy();
  });
  it("colors capacities below the saved minimum red", async () => {
    const ctx = context(vi.fn().mockResolvedValue({ data: {
      ...result,
      material_limits: [
        { part: 2, name: "不足材料", ipn: "", capacity: 6, available: "6", allocated: "0", incoming: "0", scheduled: "0", capacity_capped: false },
        { part: 3, name: "十分な材料", ipn: "", capacity: 12, available: "12", allocated: "0", incoming: "0", scheduled: "0", capacity_capped: false },
      ],
    }}));
    show(<CapacityPanel context={ctx} />);
    const current = await screen.findByText("現在の追加製造可能数: 8");
    expect(current.getAttribute("style")).toContain("red");
    expect(screen.getByText("6 個").getAttribute("style")).toContain("red");
    expect(screen.getByText("12 個").getAttribute("style") ?? "").not.toContain("red");
  });
  it("separates immediate capacity and incoming reference and saves target through API", async () => {
    const ctx = context();
    show(<CapacityPanel context={ctx} />);
    await screen.findByText("現在の追加製造可能数: 8");
    expect(screen.getByText(/個（発注済み/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("最低製造余力"), {
      target: { value: "15" },
    });
    fireEvent.click(screen.getByText("設定を保存"));
    await waitFor(() =>
      expect(ctx.api.patch).toHaveBeenCalledWith(
        "/plugin/production-capacity/capacity/1/",
        { minimum: 15, monitor: true },
      ),
    );
  });
  it("saves the widget visibility switch independently of the minimum", async () => {
    const ctx = context();
    show(<CapacityPanel context={ctx} />);
    const toggle = await screen.findByRole("switch", { name: "ウィジェットに表示" });
    fireEvent.click(toggle);
    fireEvent.click(screen.getByText("設定を保存"));
    await waitFor(() => expect(ctx.api.patch).toHaveBeenCalledWith(
      "/plugin/production-capacity/capacity/1/",
      { minimum: 10, monitor: false },
    ));
  });
  it("displays backend calculation error rather than zero capacity", async () => {
    const ctx = context(
      vi
        .fn()
        .mockRejectedValue({
          response: { data: { calculation: "Circular BOM detected" } },
        }),
    );
    show(<CapacityPanel context={ctx} />);
    expect(await screen.findByText(/Circular BOM detected/)).toBeTruthy();
    expect(screen.queryByText(/現在の追加製造可能数/)).toBeNull();
  });
  it("disables target save for read-only user", async () => {
    const ctx = context(
      vi
        .fn()
        .mockResolvedValue({ data: { ...result, can_edit_minimum: false } }),
    );
    show(<CapacityPanel context={ctx} />);
    await screen.findByText("現在の追加製造可能数: 8");
    expect(
      (
        screen.getByRole("button", {
          name: "設定を保存",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
  it("loads all pages and puts warning products before healthy products", async () => {
    const get = vi
      .fn()
      .mockResolvedValueOnce({
        data: {
          count: 2,
          limit: 1,
          results: [
            {
              ...result,
              part: 2,
              name: "正常製品",
              status: "ok",
              shortfall: 0,
            },
          ],
        },
      })
      .mockResolvedValueOnce({
        data: { count: 2, limit: 1, results: [result] },
      });
    const ctx = context(get);
    show(<CapacityDashboard context={ctx} />);
    await screen.findByText("A-001 · 製品A");
    expect(screen.getByText("製造余力一覧（2件）")).toBeTruthy();
    expect(screen.getByText("余力不足・エラー: 1件")).toBeTruthy();
    expect(get).toHaveBeenCalledWith(
      "/plugin/production-capacity/capacity/?limit=25&offset=1",
    );
    const products = screen.getAllByRole("row");
    expect(products[1].textContent).toContain("製品A");
    fireEvent.click(screen.getByText("A-001 · 製品A"));
    expect(ctx.navigate).toHaveBeenCalledWith("/part/1/production-capacity");
  });
  it("opens the dedicated list from the compact widget", async () => {
    const ctx = context(vi.fn().mockResolvedValue({ data: { count: 1, limit: 25, results: [result] } }));
    show(renderDashboardItem(ctx));
    await screen.findByText("不足 1件");
    expect(screen.getByText("製造余力一覧").getAttribute("style")).toContain("blue");
    expect(screen.getByLabelText("監視対象 1件")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "製造余力一覧を開く" }));
    expect(ctx.navigate).toHaveBeenCalledWith("/plugin/production-capacity/capacity");
  });
  it("shows purchase shortages without a purchase action and keeps the build action", async () => {
    const requirement = { part: 2, name: "不足部品", ipn: "", quantity: "5", required: "10", stock: "5", allocated: "0", available: "5", incoming: "0", scheduled: "0" };
    const ctx = context(vi.fn().mockResolvedValue({ data: {
      ...result,
      purchase_shortages: [requirement],
      manufacturing_suggestions: [{ ...requirement, part: 3, name: "組立部品", materials_ready: true }],
    }}));
    show(<CapacityPanel context={ctx} />);
    await screen.findByText("不足部品");
    expect(screen.queryByRole("button", { name: "発注明細を追加" })).toBeNull();
    expect(screen.getByText(/購入部品・原材料の不足は一覧で確認/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "製造オーダー作成" }));
    expect(ctx.navigate).toHaveBeenCalledWith("/part/3/builds");
  });
  it("opens the native creation form for the suggested assembly", async () => {
    const requirement = { part: 2, name: "不足部品", ipn: "", quantity: "5", required: "10", stock: "5", allocated: "0", available: "5", incoming: "0", scheduled: "0" };
    const get = vi.fn().mockResolvedValue({ data: { ...result, purchase_shortages: [requirement], manufacturing_suggestions: [{ ...requirement, part: 3, name: "組立部品", quantity: "4", materials_ready: true }] } });
    const ctx = context(get);
    const create = vi.fn().mockReturnValue({ modal: null, open: vi.fn() });
    (ctx as any).forms = { create };
    show(<CapacityPanel context={ctx} />);
    await screen.findByText("不足部品");
    fireEvent.click(screen.getByRole("button", { name: "製造オーダー作成" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      url: "build/", initialData: { part: 3, quantity: 4 },
    })));
    expect(create).toHaveBeenCalledWith(expect.objectContaining({
      url: "build/", fields: expect.objectContaining({ priority: {}, target_date: {}, tags: { field_type: "tags" } }),
    }));
    expect(get).not.toHaveBeenCalledWith(expect.stringContaining("/api/company/part/"));
  });
  it("explains an HTML response when URL integration is disabled", async () => {
    const ctx = context(vi.fn().mockResolvedValue({ data: "<html>InvenTree</html>" }));
    show(<CapacityPanel context={ctx} />);
    expect(await screen.findByText(/URL統合を有効/)).toBeTruthy();
    expect(screen.queryByText(/現在の追加製造可能数/)).toBeNull();
  });
  it("shows a dashboard API error instead of crashing on an HTML response", async () => {
    const ctx = context(vi.fn().mockResolvedValue({ data: "<html>InvenTree</html>" }));
    show(<CapacityDashboard context={ctx} />);
    expect(await screen.findByText(/URL統合を有効/)).toBeTruthy();
  });
  it("explains how to opt into an empty dashboard", async () => {
    const ctx = context(
      vi.fn().mockResolvedValue({ data: { count: 0, limit: 25, results: [] } }),
    );
    show(<CapacityDashboard context={ctx} />);
    expect(await screen.findByText(/最低余力を保存すると/)).toBeTruthy();
  });
});
