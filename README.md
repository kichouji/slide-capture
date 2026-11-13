# slide-capture

画面上の指定した矩形範囲を監視し、描画内容が一定以上変化したとき(スライド切り替え時)に自動でスクリーンショットを保存する、Windows タスクトレイ常駐アプリ。要件は [requirements.md](requirements.md) を参照。

## セットアップ(初回のみ)

Python はインストール済みとします。次の手順は、最初に一度だけ行います。

### 1. uv をインストールする

このアプリは、必要なライブラリの準備に [uv](https://docs.astral.sh/uv/) を使います。PowerShell を開いて次を実行します。

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

インストール後、**PowerShell をいったん閉じて開き直し**、次のコマンドでバージョンが表示されれば完了です。

```powershell
uv --version
```

> 社内ネットワークなどで上記のコマンドが使えない場合は、`pip install uv` でもインストールできます。

### 2. アプリのフォルダを置く

このフォルダ(`slide_capture`)を、好きな場所(例: `C:\Users\<ユーザー名>\Apps\slide_capture`)に置きます。
置いた後にフォルダを移動すると、手順 4 のショートカットが使えなくなるため、場所を決めてから進めてください。

### 3. ライブラリをインストールする

アプリのフォルダで PowerShell を開き(エクスプローラでフォルダを開き、アドレスバーに `powershell` と入力して Enter)、次を実行します。

```powershell
uv sync
```

フォルダ内に `.venv` が作られれば完了です。

- このアプリは Python 3.13 以上で動きます。インストール済みの Python がそれより古い場合は、uv が自動で Python 3.13 をダウンロードして使います(パソコンに入っている Python は変更されません)。
- この手順を飛ばしても、`SlideCapture.cmd` を初めてダブルクリックしたときに自動で実行されます。

### 4. 起動用ショートカットを作る(推奨)

手順 3 と同じ PowerShell で、次をまとめて貼り付けて実行します。フォルダ内に `スライド自動キャプチャ.lnk` が作られます。

```powershell
$root = (Get-Location).Path; $ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$root\スライド自動キャプチャ.lnk")
$lnk.TargetPath = "$root\.venv\Scripts\pythonw.exe"; $lnk.Arguments = "-m slide_capture"
$lnk.WorkingDirectory = $root; $lnk.IconLocation = "$root\assets\app.ico,0"; $lnk.Save()
```

作ったショートカットは、デスクトップやスタートメニューにコピーして使えます。

### 5. 初回起動と撮影範囲の指定

1. ショートカットをダブルクリックして起動します。タスクトレイ(画面右下)に灰色のアイコンが表示されます。アイコンが見えない場合は、タスクバーの「^」(隠れているインジケーター)の中を確認してください
2. アイコンを右クリックし、「撮影範囲を指定...」を選び、講義のスライドが表示される範囲をドラッグで囲みます
3. 必要に応じて「保存先を変更...」で画像の保存先を選びます(既定は `ピクチャ\SlideCapture`)

撮影範囲と保存先は記憶されるため、次回からは起動して「開始」を選ぶだけで使えます。

## 起動のしかた

| 方法 | 説明 |
|---|---|
| `スライド自動キャプチャ.lnk` をダブルクリック | 黒いウィンドウを出さずに起動します(おすすめ) |
| `SlideCapture.cmd` をダブルクリック | 黒いウィンドウが一瞬表示されてから起動します。`.venv` がなければ先に `uv sync` を実行します |

- すでに起動している場合、2つ目は起動しません
- Windows の起動時に自動で起動したい場合は、トレイメニューの「Windows 起動時に自動起動」にチェックを入れます
- ショートカットはこのパソコンのフォルダの場所を記録しているため、Git には含めていません。フォルダを移動した場合は、手順 4 をやり直してください

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

## 開発環境

[uv](https://docs.astral.sh/uv/) を使用します(Python 3.13)。開発者向けのコマンドは次のとおりです。

```bash
uv sync                      # 依存関係のインストール
uv run slide-capture         # アプリの起動
uv run pytest                # テスト
uv run ruff check .          # Lint
uv run ruff format .         # フォーマット
```

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

## ライセンス

[MIT License](LICENSE)
