# 2台構成セットアップガイド

このファイルは、`face_recognition` フォルダで使える **2台構成** の起動方法を日本語でまとめたものです。

このフォルダでは大きく 2 つの運用ができます。

- 1台構成
  - 既存の `reception_main.py` 系を使う構成です。
  - 従来どおりの動かし方を残したいときに使います。
- 2台構成
  - **Machine A = 顔認識 + フロントエンド**
  - **Machine B = 音声会話**
  - GPU / CPU の負荷を分けたいとき、音声処理を安定させたいときに使います。

このガイドは **2台構成専用** です。  
`reception_main.py` や 1台構成のファイルは壊さず、そのまま残す前提です。

---

## このフォルダで何ができるか

2台構成では、次の機能を組み合わせて動かします。

- 顔・人物検出
  - `recognition.runpod_recognition_browser`
  - カメラ画像を受け取り、人物・顔・既知人物一致を判定します。
- 受付フロントエンド
  - `application/reception_frontend.py`
  - ブラウザで開く画面を返します。
- 音声会話
  - `lab_voice_talk/recognition_gate_main.py`
  - WebSocket で音声を受け、話者認証、ASR、TTS、会話制御を行います。
- サンプル動画用モード
  - `lab_voice_talk/sample_withface_main.py`
  - 原稿固定で返答するモードです。
  - LLMの自由応答ではなく、台本どおりに返したいときに使います。

---

## 2台構成の全体像

役割分担は次のとおりです。

- Machine A
  - `8000`: Vision API
  - `8005`: Frontend
- Machine B
  - `8002`: Voice Gate

ブラウザから見る通信の流れはこうです。

1. ブラウザは Machine A の `8005` にアクセスして画面を開く
2. ブラウザは Machine A の `8000` にカメラフレームを送る
3. ブラウザは Machine B の `8002` に WebSocket で音声接続する
4. 顔認識結果に応じて、ブラウザが Voice Gate に制御メッセージを送る
5. Voice Gate が音声認識・話者認証・音声再生を行う

重要なのはここです。

- **顔認識の HTTP は Machine A**
- **音声の WebSocket は Machine B**

つまり、画面を開く URL と、音声がつながる URL は別です。

---

## 主なファイル

2台構成で直接使うファイルは次です。

- [run_two_machine_vision.sh](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/run_two_machine_vision.sh)
  - Machine A 用の起動スクリプトです。
- [run_two_machine_voice.sh](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/run_two_machine_voice.sh)
  - Machine B 用の起動スクリプトです。
- [application/reception_frontend.py](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/application/reception_frontend.py)
  - ブラウザ向けに `live.html` や `live.js` を配ります。
- [recognition/runpod_recognition_browser.py](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/recognition/runpod_recognition_browser.py)
  - 顔認識・人物追跡・`/api/live-frame` を担当します。
- [lab_voice_talk/recognition_gate_main.py](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/lab_voice_talk/recognition_gate_main.py)
  - Voice Gate の入口です。
  - 環境変数で本番モード / サンプルモードを切り替えます。
- [lab_voice_talk/sample_withface_main.py](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/lab_voice_talk/sample_withface_main.py)
  - サンプル動画用の固定シナリオ実装です。

---

## 起動前に決めること

起動前に、次の 2 つを決めてください。

1. Machine A の RunPod 公開 URL
2. Machine B の RunPod 公開 URL

たとえば次のようにします。

- Machine A
  - `https://aaaaaa-8000.proxy.runpod.net`
  - `https://aaaaaa-8005.proxy.runpod.net`
- Machine B
  - `https://bbbbbb-8002.proxy.runpod.net`
  - `wss://bbbbbb-8002.proxy.runpod.net/ws`

このときブラウザで開くのは Machine A です。

- `https://aaaaaa-8005.proxy.runpod.net/app`

---

## 先にやる環境構築
まず2台とも以下を実行してください。

```bash
git clone https://github.com/Okada-hiro/face_recognition.git
```
```bash
git clone https://github.com/autogyro/yolo-V8.git
git clone https://github.com/deepinsight/insightface.git
```
```bash
cd face_recognition
```

2台構成では、**起動コマンドの前に環境構築スクリプトを実行**してください。

### Machine A

Machine A では、まず次を実行します。


```bash
bash environment.sh
```

### Machine B

Machine B では、まず次を実行します。

```bash
bash environment_B.sh
```

この 2 つは、`bash run_two_machine_vision.sh` / `bash run_two_machine_voice.sh` の前に実行する前提です。

---

## Machine B を起動する

Machine B は音声会話専用です。  
まずこちらを起動します。

Machine B では、音声生成まわりの設定も明示してください。  
現状の推奨値は次です。

```bash
export QWEN3_MODEL_PATH=Qwen/Qwen3-TTS-12Hz-1.7B-Base
export PERM_TTS_TRIM_TAIL_SILENCE=1
export PERM_TTS_TAIL_SILENCE_DBFS=-42
export PERM_TTS_TAIL_SILENCE_MAX_TRIM_CHUNKS=240
export PERM_TTS_TAIL_SILENCE_KEEP_CHUNKS=0
export PERM_TTS_HEAD_SILENCE_MAX_DROP_CHUNKS=20
export PERM_TTS_HEAD_SILENCE_MAX_BUFFER_CHUNKS=2
export PERM_TTS_MAX_CHUNKS_PER_SENTENCE=24
export PERM_TTS_SAVE_DEBUG_AUDIO=1
export PERM_TTS_WORKER_COUNT=1
```

起動例をまとめると次です。

```bash
cd /workspace/face_recognition
source .venv/bin/activate
bash environment_B.sh
export VOICE_PORT=8002
export QWEN3_REF_AUDIO=/workspace/face_recognition/lab_voice_talk/ref_audio.WAV
export QWEN3_REF_TEXT="$(cat /workspace/face_recognition/lab_voice_talk/ref_text.txt)"
export QWEN3_MODEL_PATH=Qwen/Qwen3-TTS-12Hz-1.7B-Base
export PERM_TTS_TRIM_TAIL_SILENCE=1
export PERM_TTS_TAIL_SILENCE_DBFS=-42
export PERM_TTS_TAIL_SILENCE_MAX_TRIM_CHUNKS=240
export PERM_TTS_TAIL_SILENCE_KEEP_CHUNKS=0
export PERM_TTS_HEAD_SILENCE_MAX_DROP_CHUNKS=20
export PERM_TTS_HEAD_SILENCE_MAX_BUFFER_CHUNKS=2
export PERM_TTS_MAX_CHUNKS_PER_SENTENCE=24
export PERM_TTS_SAVE_DEBUG_AUDIO=1
export PERM_TTS_WORKER_COUNT=1
bash run_two_machine_voice.sh
```

正常起動すると、だいたい次のような表示になります。

```text
Starting two-machine voice gate ...
  port       : 8002
  mode       : prod
```

---

## Machine A を起動する

Machine A は顔認識とフロントエンド担当です。

```bash
cd /workspace/face_recognition
source .venv/bin/activate
bash environment.sh
export RECOGNITION_VOICE_TALK_WS_URL="wss://<machine-b>-8002.proxy.runpod.net/ws"
export RECEPTION_BROWSER_VOICE_WS_URL="wss://<machine-b>-8002.proxy.runpod.net/ws"
export RECEPTION_VISION_PUBLIC_BASE="https://<machine-a>-8000.proxy.runpod.net"
unset RECOGNITION_VOICE_TALK_NOTIFY_BASE
unset RECOGNITION_VOICE_TALK_HTTP_BASE
bash run_two_machine_vision.sh
```

正常起動すると、だいたい次のような表示になります。

```text
Two-machine vision/frontend stack is running.
  vision api          : http://127.0.0.1:8000
  frontend            : http://127.0.0.1:8005/app
  voice notify base   : <disabled>
  browser voice ws    : wss://<machine-b>-8002.proxy.runpod.net/ws
```

---

## ブラウザで開く URL

ブラウザで開くのは **Machine A の 8005** です。

```text
https://<machine-a>-8005.proxy.runpod.net/app
```

音声 WebSocket はこの画面の中から Machine B へ直接つながります。  
つまり、画面を開く URL は Machine A、音声は Machine B です。

---

## 本番モードとサンプルモード

Machine B の Voice Gate は、環境変数でモードを切り替えられます。

- `prod`
  - 本番用
  - 既定値
- `sample`
  - サンプル動画用
  - 固定原稿で返答します

### 本番モード

何も設定しなければ本番です。

```bash
unset RECOGNITION_VOICE_APP_MODE
bash run_two_machine_voice.sh
```

または明示的に次でも同じです。

```bash
export RECOGNITION_VOICE_APP_MODE=prod
bash run_two_machine_voice.sh
```

### サンプルモード

```bash
export RECOGNITION_VOICE_APP_MODE=sample
bash run_two_machine_voice.sh
```

起動ログに次が出れば、サンプルモードです。

```text
[GATE] startup mode=sample base=sample_withface_main ...
```

---

## サンプル動画用の原稿はどこにあるか

サンプル動画用の原稿は、現在は **外部ファイルではなくコード内に直接書いてあります**。

- [sample_withface_main.py](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/lab_voice_talk/sample_withface_main.py)

このファイルの `INLINE_SCRIPT_TURNS` を編集すると、サンプル動画の返答内容が変わります。

起動時に次のようなログが出ます。

```text
[SAMPLE_SCRIPT] loaded turns=... source=inline
```

これが出ていれば、外部 `.rtf` などは使っていません。

---

## 顔認識後の挨拶を変えたいとき

Voice Gate 側では、顔認識結果に応じて挨拶文を切り替えられます。

- 既知顔の挨拶
  - `RECOGNITION_GREETING_KNOWN_TEMPLATE`
- 未知顔の挨拶
  - `RECOGNITION_GREETING_UNKNOWN_TEXT`

たとえばサンプル動画向けに朝の挨拶にしたい場合は次のようにします。

```bash
export RECOGNITION_GREETING_KNOWN_TEMPLATE="おはようございます、{person_id}さん。"
export RECOGNITION_GREETING_UNKNOWN_TEXT="おはようございます。"
```

`{person_id}` の部分には認識した人物IDが入ります。

---

## よく使う環境変数

### Machine B 側

- `VOICE_PORT`
  - Voice Gate のポート
  - 通常は `8002`
- `QWEN3_MODEL_PATH`
  - 利用する Qwen3-TTS モデル
- `RECOGNITION_VOICE_APP_MODE`
  - `prod` または `sample`
- `QWEN3_REF_AUDIO`
  - TTS の参照音声
- `QWEN3_REF_TEXT`
  - 参照音声に対応するテキスト
- `PERM_TTS_TRIM_TAIL_SILENCE`
  - 文末無音のトリム有無
- `PERM_TTS_TAIL_SILENCE_DBFS`
  - 文末無音とみなすしきい値
- `PERM_TTS_TAIL_SILENCE_MAX_TRIM_CHUNKS`
  - 文末で最大何チャンク削るか
- `PERM_TTS_TAIL_SILENCE_KEEP_CHUNKS`
  - 文末無音をどれだけ残すか
- `PERM_TTS_HEAD_SILENCE_MAX_DROP_CHUNKS`
  - 先頭無音をどれだけ落とすか
- `PERM_TTS_HEAD_SILENCE_MAX_BUFFER_CHUNKS`
  - 先頭無音のバッファ量
- `PERM_TTS_MAX_CHUNKS_PER_SENTENCE`
  - 1文あたりの最大チャンク数
- `PERM_TTS_SAVE_DEBUG_AUDIO`
  - 生成音声のデバッグ保存有無
- `PERM_TTS_WORKER_COUNT`
  - TTS worker 数
  - 現在の推奨は `1`
- `RECOGNITION_GREETING_KNOWN_TEMPLATE`
  - 既知顔向け挨拶
- `RECOGNITION_GREETING_UNKNOWN_TEXT`
  - 未知顔向け挨拶

### Machine A 側

- `RECEPTION_BROWSER_VOICE_WS_URL`
  - ブラウザが接続する Machine B の WebSocket URL
- `RECOGNITION_VOICE_TALK_WS_URL`
  - Vision 側が使う voice WS URL
  - 通常は上と同じでよいです
- `RECEPTION_VISION_PUBLIC_BASE`
  - ブラウザから見える Machine A の Vision API の公開URL
- `RECOGNITION_VOICE_TALK_NOTIFY_BASE`
  - いまは通常未使用
- `RECOGNITION_VOICE_TALK_HTTP_BASE`
  - いまは通常未使用

---

## 典型的な起動手順

### 本番用

1. Machine B を起動する
2. Machine A を起動する
3. ブラウザで Machine A の `/app` を開く

### サンプル動画用

1. Machine B に `RECOGNITION_VOICE_APP_MODE=sample` を設定して起動する
2. 必要なら挨拶文も `RECOGNITION_GREETING_*` で調整する
3. Machine A を起動する
4. ブラウザで Machine A の `/app` を開く

---

## 動作確認の見方

### Machine B で見るログ

音声系がつながると次が出ます。

```text
[WS] Client Connected (recognition gate).
```

顔検知や顔認証の制御が届くと次が出ます。

```text
[WS_CONTROL] event=approach ...
[WS_CONTROL] event=recognized_face ...
[WS_CONTROL] event=unknown_face ...
```

### Machine A で見るログ

画面が開かれると次が出ます。

```text
[FRONTEND] render path=/ ...
```

カメラフレームが送られると次が出ます。

```text
POST /api/live-frame HTTP/1.1 200 OK
```

必要に応じて、`[LIVE_FRAME] ...` の診断ログを見ると、顔数・人物数・一致数・track event を追えます。

---

## つまずきやすいポイント

### 1. Machine A と Machine B の URL を混同する

次のように役割を分けて覚えると混乱しにくいです。

- 画面を開くのは Machine A
- 音声 WebSocket は Machine B

### 2. `RECEPTION_VISION_PUBLIC_BASE` を Machine B にしてしまう

これは Machine A の `8000` を指す必要があります。

正しい例:

```bash
export RECEPTION_VISION_PUBLIC_BASE="https://<machine-a>-8000.proxy.runpod.net"
```

### 3. `RECEPTION_BROWSER_VOICE_WS_URL` を Machine A にしてしまう

通常の 2台構成では、これは Machine B の `8002/ws` を指します。

正しい例:

```bash
export RECEPTION_BROWSER_VOICE_WS_URL="wss://<machine-b>-8002.proxy.runpod.net/ws"
```

### 4. サンプル原稿を `.rtf` で差し替えようとする

現在のサンプル動画モードは `.rtf` を読みません。  
[sample_withface_main.py](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/lab_voice_talk/sample_withface_main.py) の `INLINE_SCRIPT_TURNS` を直接編集してください。

---

## `.env` 例ファイル

補助的に次の例ファイルがあります。

- [two_machine_voice.env.example](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/two_machine_voice.env.example)
- [two_machine_vision.env.example](/Users/okadahiroaki/Downloads/AI/infodeliver/face_recognition/face_recognition/two_machine_vision.env.example)

ただし、実際の運用では RunPod の URL に合わせて書き換える必要があります。

---

## まとめ

このフォルダの 2台構成では、次の考え方だけ押さえれば運用しやすいです。

- Machine A は **顔認識 + 画面**
- Machine B は **音声会話**
- ブラウザは **Machine A の `/app`** を開く
- 音声は **Machine B の `/ws`** へつなぐ
- サンプル動画は **Machine B を `sample` モード** で起動する
- サンプル原稿は **`sample_withface_main.py` の中に直接書く**

迷ったときは、まず次の 3 つを確認してください。

1. Machine A の `RECEPTION_VISION_PUBLIC_BASE`
2. Machine A の `RECEPTION_BROWSER_VOICE_WS_URL`
3. Machine B の `RECOGNITION_VOICE_APP_MODE`
