# Mini-Go Server

1 次元 Mini-Go の大会用 TCP 対戦サーバーと参照ルールエンジンです。

Python 3.12 と uv を使います。

## セットアップ

```bash
uv sync --dev
```

## サーバー起動

```bash
uv run mini-go-server --board-size 15 --move-time 3.0 --pie-time 10.0
```

デフォルトでは `127.0.0.1:37373` で待ち受けます。
サーバーはデフォルトで接続、対局開始、初手、パイルール選択、各着手、結果を標準出力へログ出力します。実況ログを抑制したい場合は `--quiet` を付けます。

2 クライアントがエントリーした時点で、サーバー側の人間がどちらを `OPEN` にするか選びたい場合は `--manual-opener-selection` を付けます。

```bash
uv run mini-go-server -n 7 --move-time 1 --manual-opener-selection
```

このモードでは、2 クライアントが揃うたびにサーバー端末へ候補が表示され、`1` または `2` の入力で `OPEN` 側を決定します。

## 簡易動作確認

別々の端末で実行します。

```bash
uv run mini-go-server -n 7 --move-time 1
uv run mini-go-random-client --name a
uv run mini-go-random-client --name b
```

サーバーのタイムアウト付近の挙動を見たい場合は、サンプルクライアントを制限時間ぎりぎりまで待たせられます。

```bash
uv run mini-go-random-client --name a --wait-until-deadline
uv run mini-go-random-client --name b --wait-until-deadline --deadline-margin-ms 100
```

## プロトコル

[docs/protocol.md](docs/protocol.md) を参照してください。

大まかな流れは次の通りです。

1. サーバーが盤面長 `N` と制限時間を通知する。
2. クライアントがプログラム名を登録する。
3. 片方のクライアントが初手の黒石を置く。
4. もう片方のクライアントが `TAKE BLACK` または `TAKE WHITE` を選ぶ。
5. 以後はサーバーが全ての手を判定する。現時点では非合法手、タイムアウト、切断は即負けです。

## ソース構成

- `src/mini_go_server/`: 大会サーバー本体と Mini-Go ルール判定器
- `src/mini_go_sample_client/`: プロトコル確認用のサンプルクライアント
- `src/mini_go_common/`: サーバーとサンプルクライアントで共有するプロトコル処理
