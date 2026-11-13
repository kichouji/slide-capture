# slide-capture

画面上の指定した矩形範囲を監視し、描画内容が一定以上変化したとき(スライド切り替え時)に自動でスクリーンショットを保存する、Windows タスクトレイ常駐アプリ。要件は [requirements.md](requirements.md) を参照。

## 開発環境

[uv](https://docs.astral.sh/uv/) を使用します(Python 3.13)。

```bash
uv sync                      # 依存関係のインストール
uv run slide-capture         # アプリの起動
uv run pytest                # テスト
uv run ruff check .          # Lint
uv run ruff format .         # フォーマット
```

コンソールなしで起動する場合は `uv run slide-capture-gui`(または `.venv\Scripts\pythonw.exe -m slide_capture`)。

## 使い方

1. 起動するとタスクトレイにアイコン(灰色=停止中)が表示される
2. メニューの「撮影範囲を指定...」で、監視する範囲をドラッグで指定する(Esc で取り消し)
3. 「開始」で監視を開始(赤=監視中、黄=一時停止、保存した瞬間は緑に光る)
4. 「停止」で終了。セッションフォルダに画像・`log.csv`・PDF が残る

| 既定のホットキー | 操作 |
|---|---|
| Ctrl+Alt+S | 開始 / 停止 |
| Ctrl+Alt+P | 一時停止 / 再開 |
| Ctrl+Alt+C | 今すぐ撮影 |
| Ctrl+Alt+R | 撮影範囲の指定 |

### ファイルの場所

| 内容 | 場所 |
|---|---|
| 設定ファイル | `%APPDATA%\slide-capture\config.toml`(メニュー「設定ファイルを開く」でメモ帳が開く。保存すると自動反映) |
| ログ | `%APPDATA%\slide-capture\app.log` |
| 画像の保存先(既定) | `%USERPROFILE%\Pictures\SlideCapture\YYYYMMDD_HHMMSS\` |

保存ファイル名は `連番_経過時間.png`(例: `0003_00-12-34.png`)。

## 構成

| モジュール | 役割 |
|---|---|
| `detector.py` | 変化検知(縮小グレースケール画像の画素差分、落ち着き待ち、重複判定) |
| `monitor.py` | 監視ループ、状態(停止/監視中/一時停止)、最大時間・無変化の自動停止 |
| `session.py` | セッションフォルダ、PNG 保存、CSV ログ、PDF 出力 |
| `config.py` | TOML 設定の読み書き(コメント保持)と変更監視 |
| `app.py` | タスクトレイ・メニュー・通知と各機能の結び付け |
| `overlay.py` | 範囲指定のオーバーレイ、確認用の枠線、フォルダ選択 |
| `hotkeys.py` / `autostart.py` / `icons.py` / `winutil.py` | ホットキー、自動起動、トレイアイコン、Windows 固有処理 |

## 主な依存ライブラリ

| ライブラリ | 用途 |
|---|---|
| mss | 画面範囲の高速キャプチャ |
| Pillow / numpy | 画像の保存(PNG)と変化量の計算 |
| pystray | タスクトレイ常駐・メニュー・通知 |
| tkinter (標準) | ドラッグによる撮影範囲の指定、枠線表示 |
| pynput | グローバルホットキー |
| tomlkit | 設定ファイル(TOML、コメントを保持したまま読み書き) |
| watchdog | 設定ファイル変更の検知(再起動なしで反映) |
| img2pdf | 保存画像の PDF 化 |
