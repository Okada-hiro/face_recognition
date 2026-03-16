# /workspace/new_speaker_filter.py (判定安定化版: 閾値緩和 & 正規化)
import torch
import torchaudio
try:
    # speechbrain >= 1.x
    from speechbrain.inference.classifiers import EncoderClassifier
except ImportError:
    # speechbrain 0.5.x
    from speechbrain.pretrained import EncoderClassifier
import os
import logging
import torch.nn.functional as F

logger = logging.getLogger(__name__)

# --- 音声読み込み & 前処理関数 ---
def load_and_normalize_audio(path: str, target_sample_rate=16000):
    if not os.path.exists(path):
        raise FileNotFoundError(f"音声ファイルが見つかりません: {path}")

    signal, fs = torchaudio.load(path)
    
    # 1. ステレオ→モノラル変換
    if signal.shape[0] > 1:
        signal = signal.mean(dim=0, keepdim=True)
    
    # 2. リサンプリング (16kHzへ)
    if fs != target_sample_rate:
        resampler = torchaudio.transforms.Resample(orig_freq=fs, new_freq=target_sample_rate)
        signal = resampler(signal)

    # 3. ★音量正規化 (Peak Normalization)★
    # これにより、声の大きさによる判定ミスを減らします
    max_val = torch.abs(signal).max()
    if max_val > 0:
        signal = signal / max_val
        
    return signal

# --- 声紋フィルタークラス ---
class SpeakerGuard:
    def __init__(self):
        print("⏳ [SpeakerGuard] モデルをロード中... (SpeechBrain)")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # モデルロード
        self.classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
            run_opts={"device": self.device}
        )
        
        self.known_speakers = [] 
        self.auto_register_min_seconds = float(os.getenv("SPEAKER_AUTO_REGISTER_MIN_SECONDS", "1.5"))
        
        # ★閾値を変更★
        # 0.35(厳格) -> 0.25(実用的)
        # 数値を下げると本人拒否が減りますが、他人誤認のリスクは少し増えます。
        # バランスを見て 0.20 〜 0.30 の間で調整してください。
        self.threshold = 0.25 
        
        print(f"✅ [SpeakerGuard] 準備完了 (Device: {self.device}, Threshold: {self.threshold})")

    def extract_embedding(self, audio_tensor):
        """音声波形から特徴ベクトル(Embedding)を抽出"""
        # Tensorの形状チェックとデバイス移動
        audio_tensor = audio_tensor.to(self.device)
        
        if audio_tensor.ndim == 1:
            audio_tensor = audio_tensor.unsqueeze(0)
            
        # 音量正規化 (念のためここでもチェック)
        max_val = torch.abs(audio_tensor).max()
        if max_val > 0:
            audio_tensor = audio_tensor / max_val

        # 長さ情報のダミー作成
        wav_lens = torch.ones(audio_tensor.shape[0]).to(self.device)

        with torch.no_grad():
            embedding = self.classifier.encode_batch(audio_tensor, wav_lens)
        
        # 正規化されたベクトルを返す (コサイン類似度計算のため重要)
        return F.normalize(embedding, p=2, dim=-1)

    def identify_speaker(self, audio_tensor) -> tuple[bool, str]:
        """
        Tensorを受け取り、(登録済みか, 話者ID) を返す
        """
        try:
            current_embedding = self.extract_embedding(audio_tensor)
            sample_count = int(audio_tensor.shape[-1]) if audio_tensor.ndim > 1 else int(audio_tensor.shape[0])
            duration_sec = sample_count / 16000.0
            
            # まだ誰も登録されていない場合 -> 最初の1人を自動登録 (オーナー)
            if not self.known_speakers:
                if duration_sec < self.auto_register_min_seconds:
                    logger.info(
                        f"🚫 [SpeakerGuard] 初回自動登録を見送り: 音声が短すぎます ({duration_sec:.2f}s < {self.auto_register_min_seconds:.2f}s)"
                    )
                    return False, "Unknown"
                print("🔒 [SpeakerGuard] 最初の話者を 'User 0' (オーナー) として登録")
                self.known_speakers.append({'id': 'User 0', 'emb': current_embedding})
                return True, "User 0"

            max_score = -1.0
            best_match_id = "Unknown"
            is_match = False

            # 全登録者と比較し、ベストスコアを探す (Winner takes all)
            for speaker in self.known_speakers:
                score = torch.nn.functional.cosine_similarity(
                    speaker['emb'], current_embedding, dim=-1
                )
                score_val = score.item()
                
                # ログを出して調整しやすくする
                # logger.info(f"Checking {speaker['id']}: Score={score_val:.4f}")

                if score_val > max_score:
                    max_score = score_val
                    best_match_id = speaker['id']

            # 最大スコアが閾値を超えているか判定
            if max_score > self.threshold:
                is_match = True
                logger.info(f"✅ [SpeakerGuard] 認証成功: {best_match_id} (スコア: {max_score:.3f} > {self.threshold})")
                return True, best_match_id
            else:
                logger.info(f"🚫 [SpeakerGuard] 未知の話者 (最大スコア: {max_score:.3f} < {self.threshold}) -> 候補: {best_match_id}")
                return False, "Unknown"
                
        except Exception as e:
            print(f"[SpeakerGuard Error] 識別失敗: {e}")
            import traceback
            traceback.print_exc()
            return False, "Error"

    def register_new_speaker(self, audio_path: str) -> str:
        """
        ファイルパスから新規登録し、割り当てたIDを返す
        """
        try:
            # 読み込み時に正規化を実行
            audio_tensor = load_and_normalize_audio(audio_path)
            
            # 極端に短い音声の登録を防ぐ (0.5秒未満はエラー扱いなど)
            if audio_tensor.shape[-1] < 8000: # 16000Hz * 0.5s
                print("[SpeakerGuard] エラー: 登録音声が短すぎます")
                return None

            new_emb = self.extract_embedding(audio_tensor)
            
            # ID生成
            new_id = f"User {len(self.known_speakers)}"
            
            self.known_speakers.append({'id': new_id, 'emb': new_emb})
            print(f"📝 [SpeakerGuard] 新規登録完了: {new_id}")
            return new_id
        except Exception as e:
            print(f"[SpeakerGuard Error] 登録失敗: {e}")
            return None

    def verify_tensor(self, audio_tensor):
        """互換性維持用"""
        is_ok, _ = self.identify_speaker(audio_tensor)
        return is_ok
