# Mini-Go TCP プロトコル v1

このプロトコルは TCP 上の UTF-8 行指向プロトコルです。

1 行が 1 コマンドです。改行は LF です。トークンは ASCII 空白で区切ります。空白を含む値はシェル風にクォートできます。`key=value` 形式のトークンはフィールドとして扱います。コマンド名と列挙値は大文字小文字を区別しませんが、この文書では大文字で書きます。

サーバーはルール、制限時間、色、勝敗判定について常に権威を持ちます。

## 盤面とルール

盤面は `1 x N` の 1 次元盤面です。インデックスは左から `0..N-1` です。

プロトコル上の盤面文字列は次の文字で表します。

- `.`: 空点
- `X`: 黒石
- `O`: 白石

黒が先手です。着手は、着手先が空点であり、かつ「捕獲手である」または「自殺手ではない」場合に合法です。

捕獲手を着手したプレイヤーは即勝ちです。非捕獲の合法手のあと、次の手番プレイヤーに合法手がなければ、直前に着手したプレイヤーが勝ちです。

## パイルール

各対局はパイルール付きで始まります。

1. サーバーが片方のクライアントを `OPEN`、もう片方を `CHOOSE` に割り当てる。
2. `OPEN` が初手として黒石を 1 つ置く。
3. `CHOOSE` が `TAKE BLACK` または `TAKE WHITE` を返す。
4. `CHOOSE` が黒を選んだ場合、`CHOOSE` が黒、`OPEN` が白を担当する。
5. `CHOOSE` が白を選んだ場合、`OPEN` が黒、`CHOOSE` が白を担当する。
6. 初手後の盤面から対局を続ける。初手で対局が終わっていなければ白番から再開する。

## 接続開始

接続後、サーバーは次を送ります。

```text
HELLO MINIGO version=1 board_size=15 move_time_ms=3000 pie_time_ms=10000
```

クライアントは `handshake_time` 以内に次を返す必要があります。

```text
REGISTER name="Program Name" protocol=1
```

登録が受理されると、サーバーは次を送ります。

```text
READY
```

2 クライアントが揃うと、サーバーは各クライアントに対局情報を送ります。

```text
MATCH id=1779190000000 you=OPEN opponent="Other Bot" board_size=15
ROLE OPEN
```

または:

```text
MATCH id=1779190000000 you=CHOOSE opponent="Other Bot" board_size=15
ROLE CHOOSE
```

## 着手要求

クライアントの手番では、サーバーが次を送ります。

```text
REQUEST MOVE phase=PLAY color=WHITE board=..X............ legal=0,1,3,4,5 timeout_ms=3000
```

クライアントは次のように返します。

```text
MOVE 4
```

範囲外、占有点、自殺手、不正な形式、時間切れ、無応答はサーバーが反則負けとして処理します。

## パイルール選択要求

`CHOOSE` 側は次を受け取ります。

```text
REQUEST PIE choices=BLACK,WHITE timeout_ms=10000
```

クライアントは次のどちらかを返します。

```text
TAKE BLACK
```

```text
TAKE WHITE
```

## 任意の探索情報

クライアントは考慮中に、最終的な `MOVE` の前に 0 個以上の `INFO` 行を送れます。

```text
INFO score=120 comment="中央を分断できそう"
```

`score` はクライアント視点の任意の評価値です。`comment` は観戦表示やログ用の任意コメントです。どちらも勝敗判定には影響しません。

## 状態通知

合法手が受理されたあと、サーバーは両クライアントに状態を通知します。

```text
STATE phase=PLAY board=..XO........... turn=BLACK last_move=3 status=ongoing
```

`turn` は次に着手する色です。

## 結果通知

通常の勝敗:

```text
RESULT winner=BLACK winner_name=bot-a loser=WHITE loser_name=bot-b reason=capture board=..XOOX.........
```

反則や異常終了:

```text
RESULT winner_name=bot-a loser_name=bot-b reason=illegal_move:suicide
```

主な `reason` は次の通りです。

- `capture`
- `no_legal_move`
- `timeout:<phase>`
- `disconnect:<phase>`
- `illegal_opening:<detail>`
- `illegal_move:<detail>`
- `protocol:<phase>:<detail>`

## 互換性方針

この文書はプロトコルバージョン `1` を定義します。後方互換性のない変更は、`HELLO` と `REGISTER` のプロトコルバージョンを更新して扱います。
