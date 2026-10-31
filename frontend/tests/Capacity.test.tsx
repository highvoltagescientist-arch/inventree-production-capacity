import React from "react";
import { MantineProvider } from "@mantine/core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CapacityDashboard, CapacityPanel } from "../src/Capacity";

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
  material_limits: [],
  purchase_shortages: [],
  manufacturing_suggestions: [],
  warnings: [],
  calculated_at: "2026-10-31T00:00:00Z",
};
function context(get = vi.fn().mockResolvedValue({ data: result })) {
  return {
    id: 1,
    navigate: vi.fn(),
    api: { get, patch: vi.fn().mockResolvedValue({ data: {} }) },
  };
}
function show(component: React.ReactNode) {
  return render(<MantineProvider>{component}</MantineProvider>);
}

describe("capacity UI", () => {
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
  it("separates immediate capacity and incoming reference and saves target through API", async () => {
    const ctx = context();
    show(<CapacityPanel context={ctx} />);
    await screen.findByText("現在の追加製造可能数: 8");
    expect(screen.getByText(/12 個（発注済み/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("最低製造余力"), {
      target: { value: "15" },
    });
    fireEvent.click(screen.getByText("保存・監視対象に追加"));
    await waitFor(() =>
      expect(ctx.api.patch).toHaveBeenCalledWith(
        "/plugin/production-capacity/capacity/1/",
        { minimum: 15 },
      ),
    );
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
          name: "保存・監視対象に追加",
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
    expect(get).toHaveBeenCalledWith(
      "/plugin/production-capacity/capacity/?limit=25&offset=1",
    );
    const products = screen.getAllByRole("row");
    expect(products[1].textContent).toContain("製品A");
    fireEvent.click(screen.getByText("A-001 · 製品A"));
    expect(ctx.navigate).toHaveBeenCalledWith("/part/1");
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
