import React, { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  NumberInput,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";

interface Context {
  id?: number;
  api: {
    get: (url: string) => Promise<{ data: any }>;
    patch: (url: string, data: object) => Promise<{ data: any }>;
  };
  navigate: (path: string) => void;
}
interface Requirement {
  part: number;
  name: string;
  ipn: string;
  quantity: string;
  stock: string;
  allocated: string;
  available: string;
  incoming: string;
  scheduled: string;
  required: string;
  materials_ready?: boolean;
}
interface MaterialLimit {
  part: number;
  name: string;
  ipn: string;
  capacity: number;
  capacity_capped: boolean;
  available: string;
  allocated: string;
  incoming: string;
  scheduled: string;
}
interface Capacity {
  part: number;
  name: string;
  ipn: string;
  status: "ok" | "warning" | "error";
  current_capacity: number;
  future_capacity: number;
  minimum: number;
  shortfall: number;
  capacity_capped: boolean;
  future_capacity_capped: boolean;
  material_limits: MaterialLimit[];
  purchase_shortages: Requirement[];
  manufacturing_suggestions: Requirement[];
  warnings: string[];
  calculated_at: string;
  can_edit_minimum: boolean;
  error?: string;
}
const base = "/plugin/production-capacity/capacity/";
const invalidApiResponse =
  "製造余力APIから正しい応答を取得できません。管理者設定の「URL統合を有効」とプラグインの有効状態を確認してください。";
function requireCapacity(data: any): Capacity {
  if (
    !data ||
    typeof data.current_capacity !== "number" ||
    !Array.isArray(data.material_limits) ||
    !Array.isArray(data.purchase_shortages) ||
    !Array.isArray(data.manufacturing_suggestions) ||
    !Array.isArray(data.warnings)
  ) {
    throw new Error(invalidApiResponse);
  }
  return data as Capacity;
}
const independence =
  "製品ごとに独立した試算です。複数製品を同時にこの数量まで製造できる保証はありません。";

function errorText(error: any): string {
  const body = error?.response?.data;
  return body
    ? typeof body === "string"
      ? body
      : JSON.stringify(body)
    : String(error?.message || error);
}
function Status({ value }: { value: string }) {
  return (
    <Badge color={value === "ok" ? "green" : "red"}>
      {value === "ok" ? "正常" : value === "error" ? "計算エラー" : "余力不足"}
    </Badge>
  );
}
function PartLink({
  row,
  context,
}: {
  row: { part: number; name: string; ipn: string };
  context: Context;
}) {
  return (
    <Button
      variant="subtle"
      size="compact-sm"
      onClick={() => context.navigate(`/part/${row.part}`)}
    >
      {row.ipn ? `${row.ipn} · ` : ""}
      {row.name}
    </Button>
  );
}
function Requirements({
  title,
  rows,
  context,
  proposals = false,
}: {
  title: string;
  rows: Requirement[];
  context: Context;
  proposals?: boolean;
}) {
  return (
    <Stack gap="xs">
      <Title order={5}>{title}</Title>
      {rows.length ? (
        <Table.ScrollContainer minWidth={650}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>部品</Table.Th>
                <Table.Th>{proposals ? "追加製造" : "不足"}</Table.Th>
                <Table.Th>必要総数</Table.Th>
                <Table.Th>現在庫</Table.Th>
                <Table.Th>引当済み</Table.Th>
                <Table.Th>使用可能</Table.Th>
                <Table.Th>入荷予定</Table.Th>
                <Table.Th>製造予定で確保</Table.Th>
                {proposals && <Table.Th>材料</Table.Th>}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.part}>
                  <Table.Td>
                    <PartLink row={row} context={context} />
                  </Table.Td>
                  <Table.Td>{row.quantity}</Table.Td>
                  <Table.Td>{row.required}</Table.Td>
                  <Table.Td>{row.stock}</Table.Td>
                  <Table.Td>{row.allocated}</Table.Td>
                  <Table.Td>{row.available}</Table.Td>
                  <Table.Td>{row.incoming}</Table.Td>
                  <Table.Td>{row.scheduled}</Table.Td>
                  {proposals && (
                    <Table.Td>
                      {row.materials_ready
                        ? "材料充足・製造提案"
                        : "下位材料の調達が必要"}
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      ) : (
        <Text size="sm">該当なし</Text>
      )}
    </Stack>
  );
}

export function CapacityPanel({ context }: { context: Context }) {
  const [data, setData] = useState<Capacity | null>(null);
  const [minimum, setMinimum] = useState<string | number>(0);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    setData(null);
    context.api
      .get(`${base}${context.id}/`)
      .then(({ data }) => {
        if (active) {
          const result = requireCapacity(data);
          setData(result);
          setMinimum(result.minimum);
        }
      })
      .catch((error) => {
        if (active) setError(errorText(error));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [context.id, refresh, context.api]);
  async function save() {
    if (typeof minimum !== "number" || !Number.isInteger(minimum)) return;
    setSaving(true);
    setError("");
    try {
      await context.api.patch(`${base}${context.id}/`, { minimum });
      setRefresh((v) => v + 1);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setSaving(false);
    }
  }
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={4}>製造余力</Title>
        <Button
          onClick={() => setRefresh((v) => v + 1)}
          loading={busy}
          disabled={saving}
        >
          再計算
        </Button>
      </Group>
      {error && (
        <Alert color="red" title="計算・保存できませんでした">
          {error}
        </Alert>
      )}
      {busy && <Text>計算中…</Text>}
      {data && (
        <>
          <Group>
            <Status value={data.status} />
            <Text>
              現在の追加製造可能数: {data.current_capacity}
              {data.capacity_capped ? "以上" : ""}
            </Text>
            <Text>最低余力: {data.minimum}</Text>
            <Text>不足: {data.shortfall}</Text>
          </Group>
          <Alert title="入荷後の参考数量">
            {data.future_capacity}
            {data.future_capacity_capped ? "以上" : ""}{" "}
            個（発注済みの未入荷分を含む試算。現在は使用できません。入荷時期・製造所要時間は考慮しません。）
          </Alert>
          <Stack gap="xs">
            <Title order={5}>材料別の製造可能数（上限の低い順）</Title>
            <Text size="sm">
              各材料だけを制約とした追加製造数です。多階層BOM、共通材料の合算、サブアセンブリ在庫、段取り数量と端数処理を含めて計算します。
              他の材料も必要なため、実際の現在余力は一覧の最小値です。入荷予定はこの上限に含めません。
            </Text>
            <Table.ScrollContainer minWidth={650}>
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>材料</Table.Th>
                    <Table.Th>この材料による上限</Table.Th>
                    <Table.Th>使用可能在庫</Table.Th>
                    <Table.Th>引当済み</Table.Th>
                    <Table.Th>製造予定で確保</Table.Th>
                    <Table.Th>入荷予定（参考）</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {data.material_limits.map((row) => (
                    <Table.Tr key={row.part}>
                      <Table.Td>
                        <PartLink row={row} context={context} />
                      </Table.Td>
                      <Table.Td>
                        {row.capacity}{row.capacity_capped ? "以上" : ""} 個
                      </Table.Td>
                      <Table.Td>{row.available}</Table.Td>
                      <Table.Td>{row.allocated}</Table.Td>
                      <Table.Td>{row.scheduled}</Table.Td>
                      <Table.Td>{row.incoming}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Stack>
          <Group align="end">
            <NumberInput
              label="最低製造余力"
              value={minimum}
              onChange={setMinimum}
              min={0}
              max={1000000000}
              allowDecimal={false}
              allowNegative={false}
              disabled={!data.can_edit_minimum || saving}
            />
            <Button
              onClick={save}
              loading={saving}
              disabled={
                !data.can_edit_minimum ||
                typeof minimum !== "number" ||
                !Number.isInteger(minimum)
              }
            >
              保存・監視対象に追加
            </Button>
          </Group>
          <Text size="sm">
            最低製造余力は警告判定の閾値です。以下の調達不足と製造提案は、この目標数量を達成するための分析です。
            上の材料別上限は最低製造余力の設定値に依存しません。
          </Text>
          <Requirements
            title="最低余力達成に不足する購入部品・原材料"
            rows={data.purchase_shortages}
            context={context}
          />
          <Requirements
            title="最低余力達成に必要なサブアセンブリ製造（下位から順番）"
            rows={data.manufacturing_suggestions}
            context={context}
            proposals
          />
          {data.warnings.map((warning) => (
            <Alert color="yellow" key={warning}>
              {warning}
            </Alert>
          ))}
          <Text size="xs">
            計算時刻: {new Date(data.calculated_at).toLocaleString()}
          </Text>
        </>
      )}
      <Text size="sm">
        完成品の既存在庫を除く、新たに製造できる数量を表示します。{independence}{" "}
        この試算は在庫を予約しません。
      </Text>
    </Stack>
  );
}

export function CapacityDashboard({ context }: { context: Context }) {
  const [rows, setRows] = useState<Capacity[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    async function load() {
      const all: Capacity[] = [];
      let offset = 0;
      while (active) {
        const { data } = await context.api.get(
          `${base}?limit=25&offset=${offset}`,
        );
        if (
          !data ||
          !Array.isArray(data.results) ||
          !Number.isInteger(data.count) ||
          !Number.isInteger(data.limit) ||
          data.limit < 1
        ) {
          throw new Error(invalidApiResponse);
        }
        all.push(...data.results);
        offset += data.limit;
        if (offset >= data.count) break;
      }
      all.sort(
        (a, b) =>
          Number(a.status === "ok") - Number(b.status === "ok") ||
          (b.shortfall || 0) - (a.shortfall || 0) ||
          a.part - b.part,
      );
      if (active) setRows(all);
    }
    load()
      .catch((error) => {
        if (active) setError(errorText(error));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [context.api, refresh]);
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text fw={600}>製造余力一覧</Text>
        <Button
          size="xs"
          loading={busy}
          onClick={() => setRefresh((v) => v + 1)}
        >
          更新
        </Button>
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {!busy && !rows.length && !error && (
        <Text>
          製品の「製造余力」パネルで最低余力を保存すると、ここに表示されます。
        </Text>
      )}
      <Table.ScrollContainer minWidth={500}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>製品・品番</Table.Th>
              <Table.Th>現在余力</Table.Th>
              <Table.Th>最低</Table.Th>
              <Table.Th>不足</Table.Th>
              <Table.Th>状態</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.part}>
                <Table.Td>
                  <PartLink row={row} context={context} />
                  {row.error && (
                    <Text c="red" size="xs">
                      {row.error}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  {row.current_capacity ?? "—"}
                  {row.capacity_capped ? "以上" : ""}
                </Table.Td>
                <Table.Td>{row.minimum ?? "—"}</Table.Td>
                <Table.Td>{row.shortfall ?? "—"}</Table.Td>
                <Table.Td>
                  <Status value={row.status} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="xs">{independence}</Text>
    </Stack>
  );
}
export function renderPanel(context: Context) {
  return <CapacityPanel context={context} />;
}
export function renderDashboardItem(context: Context) {
  return <CapacityDashboard context={context} />;
}
