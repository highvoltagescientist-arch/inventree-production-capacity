# 調査・検証記録

調査日：2026-10-31（日本時間）。公式GitHubから最新HEADを取得して確認しました。本体の作業ツリーは編集せず、公式HEADのアーカイブを別ディレクトリに展開して統合テストを実行しています。

## 参照した公式資料

- [InvenTree最新ソース](https://github.com/inventree/InvenTree/tree/d96174cddbc2566fea53b3fe39b5d4aa5d30fbf1)
- [公式プラグイン開発ドキュメント](https://docs.inventree.org/en/latest/plugins/develop/)
- [公式UI拡張ドキュメント](https://docs.inventree.org/en/stable/plugins/mixins/ui/)
- [Plugin Creator](https://github.com/inventree/plugin-creator/tree/4bd8022a13d039e073a86c16e2cd769ddab8c989)
- [公式UIサンプル](https://github.com/inventree/InvenTree/blob/d96174cddbc2566fea53b3fe39b5d4aa5d30fbf1/src/backend/InvenTree/plugin/samples/integration/user_interface_sample.py)

Plugin CreatorのCookiecutterテンプレートを実際に生成し、UrlsMixin / UserInterfaceMixin、Pythonエントリポイント、React classic JSXと外部ライブラリの設定を基に構成しました。サンプル機能や独自モデルを除き、計算とUIを分離しています。

## データモデルの根拠

対象コミットの次の実装を確認しました。

| 実装 | 使用・判断 |
| --- | --- |
| `part/models.py: Part.get_bom_items` | 継承BOMを含めて取得 |
| `part/models.py: BomItem.get_required_quantity` | piece_count、attrition、setup_quantity、rounding_multiple。実モデルの関数と計算結果を比較 |
| `stock/models.py: StockItem.IN_STOCK_FILTER` | 消費済み・組込済み・顧客割当・製造途中・使用不可状態の在庫を除外 |
| `StockItem.bulk_allocation_count` | 製造・未出荷の販売・未完了の移動の引当を集計 |
| `build/models.py: BuildLine.unallocated_quantity` | 必要量－消費済み－引当済みを製造予定として確保 |
| `build/status_codes.py: BuildStatusGroups.ACTIVE_CODES` | Pending / Production / On Hold の製造需要を対象 |
| `part/models.py: Part.on_order` | 未入荷量とSupplierPart.base_quantityによる梱包単位換算を参考に実装 |
| `order/status_codes.py: PurchaseOrderStatus` | 標準on_orderは下書き・保留も含むため、本プラグインではPLACEDだけに限定 |
| `InvenTree/models.py: MetadataMixin` | 名前空間単位のメタデータを使用。更新は行ロック付きで他キーを維持 |
| `users/permissions.py: check_user_permission` | モデルクラスを渡して標準の権限継承を使用 |
| `plugin/base/ui/mixins.py` | get_ui_panels / get_ui_dashboard_items |
| `plugin/base/integration/UrlsMixin.py` | setup_urls でREST APIを登録 |
| `src/frontend/src/components/plugins/PluginContext.tsx` | context.api、context.id、context.navigateを使用 |

## 検証環境と範囲

- InvenTree **1.6.3**（公式Dockerイメージ）および **1.7.0 dev**、コミット `d96174cddbc2566fea53b3fe39b5d4aa5d30fbf1`
- 1.7.0 dev：Docker上のPython 3.12 / Django 5.2.17、PostgreSQL 15、Redis 7
- 1.7.0 dev：プラグインを `pip install -e` で導入し、専用DB `test_production_capacity` で統合テスト
- 1.6.3：公式イメージ `inventree/inventree:1.6.3` に0.1.1をpip導入し、一時SQLiteテストDBで17件の統合テスト。プラグイン登録・UI機能・静的ファイル収集も確認
- ホストのPython 3.14で純粋な計算エンジンのテスト
- Node.js 26.13 / React 19.2.7 / Mantine 9.7.1 / Vite 7.3.7でUIテスト・TypeScript検査・本番ビルド

計算エンジン、実モデル連携、メタデータ保存、権限、CSRF、HTTPルート、エントリポイントからの自動検出、InvenTree標準処理による静的ファイル収集を検証します。UIはjsdomによる描画・操作テストです。実際の標準Web UIへのブラウザ接続は利用できず、目視・操作によるE2E確認は未実施です。

GitHub Actionsの設定例 `docs/ci-workflow.example.yml` はエンジン・UI・パッケージの検証用です。導入時のGit認証に `workflow` 権限がなく、自動実行は有効化していません。実モデル統合テストのCI実行も未設定で、READMEのコマンドから実行します。

## 実行結果

| 検証 | 結果 |
| --- | --- |
| 純粋な計算エンジン | 33件成功 |
| InvenTree 1.6.3 実モデル・プラグイン・API | 17件成功（SQLite、一時Dockerコンテナ） |
| InvenTree 1.7.0 dev 実モデル・プラグイン・API | 17件成功（PostgreSQL） |
| React UI描画・操作 | 5件成功 |
| TypeScript検査・Vite本番ビルド | 成功 |
| Ruff検査・整形チェック | 成功 |
| Wheel・ソース配布物ビルド | 成功 |

パッケージには計算エンジン、プラグインエントリポイント、ビルド済み `static/Capacity.js` を同梱します。実モデルテストのCSRF拒否試験では意図的なHTTP 403がログに出ます。

## 計算上の意図的な境界

引当済み在庫と未引当の製造必要量を別々に控除し、消費済み数量は再度控除しません。製造予定はInvenTreeに保存済みのBuildLineを参照し、製造オーダーを変更しません。BOM変更に伴うInvenTree側のBuildLine更新が未完了の場合、その反映を待つ必要があります。

代替部品・バリアントの自動選択を行わず、在庫は正確な品目ID単位で保持します。これにより親品目の在庫にバリアントを合算しながら、別経路でも同じ在庫を利用する二重計上を防ぎます。購入可能なアセンブリも、BOMがある場合は追加購入を仮定せず製造展開します。BOMのない末端品は外部調達対象として扱います。

実際の割付で要求される切断寸法・在庫単位の適合、期限など、標準の集計在庫フィルターを超える制約は考慮しません。画面表示時の参考試算であり、実製造時はInvenTree標準の割当・検証を実行してください。
