# AGENTS.md - AI Agent Instructions

このファイルはAIエージェント（Claude Code、GitHub Copilot等）向けの開発ガイドです。

## プロジェクト概要

**comfyui-save-image-watermark** は ComfyUI のカスタムノードで、透かし機能付きの画像保存を提供します。

### 主要ファイル

```
comfyui-save-image-watermark/
├── __init__.py           # ノード登録（NODE_CLASS_MAPPINGS）
├── watermark_node.py     # メインロジック（★重要）
├── local_save_node.py    # シンプル保存ノード（非推奨、後方互換用）
├── js/
│   └── local_save.js     # ブラウザダウンロード用JS
├── examples/
│   └── *.json            # サンプルワークフロー
├── README.md
└── AGENTS.md             # このファイル
```

## アーキテクチャ

### クラス構成

```
LocalSaveImageWithWatermark
├── add_image_watermark()    # 画像ロゴ合成（MASK対応）
├── add_text_watermark()     # テキスト透かし
├── embed_invisible_watermark()  # LSBステガノグラフィ
├── calculate_content_hash() # SHA-256ハッシュ
├── create_aicu_metadata()   # メタデータ生成
└── save_with_watermark()    # メイン処理

ExtractInvisibleWatermark
└── extract()               # LSB抽出
```

### 処理順序（重要）

```python
# 1. 画像ロゴ透かし（最下層）
if watermark_image is not None:
    image = self.add_image_watermark(...)

# 2. テキスト透かし（ロゴの上）
if watermark_text_enabled:
    image = self.add_text_watermark(...)

# 3. 不可視透かし（最後）- ステガノグラフィ
if invisible_watermark_enabled:
    image = self.embed_invisible_watermark(...)
```

## 開発ガイドライン

### ComfyUIノードの基本構造

```python
class MyNode:
    CATEGORY = "AICU/Save"          # ノードブラウザのカテゴリ
    FUNCTION = "main_function"       # 実行される関数名
    OUTPUT_NODE = True               # 出力ノード（実行トリガー）
    RETURN_TYPES = ("STRING",)       # 出力の型
    RETURN_NAMES = ("output_name",)  # 出力の名前

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "optional": {
                "mask": ("MASK",),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO"
            }
        }
```

### 型の対応

| ComfyUI型 | Python型 | 説明 |
|----------|---------|------|
| IMAGE | torch.Tensor | shape: (batch, height, width, channels) |
| MASK | torch.Tensor | shape: (batch, height, width) |
| STRING | str | 文字列 |
| INT | int | 整数 |
| FLOAT | float | 浮動小数点 |
| BOOLEAN | bool | 真偽値 |

### 画像テンソルの変換

```python
# ComfyUI IMAGE → PIL
img_np = tensor[0].cpu().numpy()
img_np = (img_np * 255).clip(0, 255).astype(np.uint8)
if img_np.shape[-1] == 4:
    pil_image = Image.fromarray(img_np, mode='RGBA')
else:
    pil_image = Image.fromarray(img_np, mode='RGB')

# PIL → ComfyUI IMAGE
np_image = np.array(pil_image).astype(np.float32) / 255.0
tensor = torch.from_numpy(np_image).unsqueeze(0)
```

### MASK処理

```python
# ComfyUI MASK → PIL (L mode)
# 【重要】ComfyUI LoadImageのMASK出力は反転している
# MASK=1 (白) = 透明部分、MASK=0 (黒) = 不透明部分
# → 一般的な用途では反転が必要
mask_np = mask_tensor[0].cpu().numpy()
# 反転して intensity として使用: 不透明部分=255, 透明部分=0
mask_np = ((1.0 - mask_np) * 255).clip(0, 255).astype(np.uint8)
alpha_mask = Image.fromarray(mask_np, mode='L')
```

### LSBステガノグラフィ（不可視透かし）

現在の実装はシンプルLSB方式を採用。

```python
# 埋め込み
def embed_invisible_watermark(image: Image, message: str) -> Image:
    """
    【アルゴリズム】
    1. message を UTF-8 でバイト列に変換
    2. 終端マーカー b'\x00\x00\x00\x00' を追加
    3. 各バイトを8ビットに分解
    4. 画像の各ピクセルの R,G,B の LSB を順番に書き換え
    5. アルファチャンネルは変更しない（透明度保持）

    【制限事項】
    - JPEG/WebP保存で破壊される（非可逆圧縮）
    - リサイズ、クロップ、回転で破壊される
    - PNG形式でのみ保持される
    - 暗号化なし、固定パターン
    """
    pixels = np.array(image)
    data = message.encode('utf-8') + b'\x00\x00\x00\x00'
    bits = ''.join(format(byte, '08b') for byte in data)

    bit_idx = 0
    for y in range(pixels.shape[0]):
        for x in range(pixels.shape[1]):
            for c in range(3):  # R, G, B のみ
                if bit_idx < len(bits):
                    pixels[y, x, c] = (pixels[y, x, c] & 0xFE) | int(bits[bit_idx])
                    bit_idx += 1
    return Image.fromarray(pixels)

# 抽出
def extract_invisible_watermark(image: Image) -> str:
    """
    【アルゴリズム】
    1. 各ピクセルの R,G,B から LSB を取得
    2. 8ビットずつ集めてバイトに復元
    3. 終端マーカー検出で終了
    4. UTF-8 デコード
    """
    pixels = np.array(image)
    bits = []
    for y in range(pixels.shape[0]):
        for x in range(pixels.shape[1]):
            for c in range(3):
                bits.append(pixels[y, x, c] & 1)

    # 8ビットずつバイトに変換
    message_bytes = bytearray()
    for i in range(0, len(bits) - 7, 8):
        byte = sum(bits[i+j] << (7-j) for j in range(8))
        message_bytes.append(byte)
        # 終端マーカー検出
        if len(message_bytes) >= 4 and message_bytes[-4:] == b'\x00\x00\x00\x00':
            break

    return message_bytes[:-4].decode('utf-8', errors='ignore')
```

**⚠️ 制限事項まとめ:**
| 操作 | 結果 |
|-----|------|
| PNG保存 | ✅ 保持 |
| JPEG/WebP | ❌ 破壊 |
| リサイズ/クロップ/回転 | ❌ 破壊 |
| 色調補正 | ❌ 破壊 |

## 将来の拡張（TODO）

### テキスト装飾
watermark_node.py の `add_text_watermark()` を拡張:

```python
# 追加予定のパラメータ
font_path: Optional[str] = None,
stroke_enabled: bool = False,
stroke_color: str = "#000000",
stroke_width: int = 2,
shadow_enabled: bool = False,
shadow_color: str = "#000000",
shadow_offset: Tuple[int, int] = (2, 2),
```

PIL/Pillowの `ImageDraw.text()` で実装可能:
```python
draw.text((x, y), text, font=font, fill=color,
          stroke_width=stroke_width, stroke_fill=stroke_color)
```

### 高度なステガノグラフィ
`embed_invisible_watermark()` を拡張:

- **DCT方式**: JPEG圧縮耐性あり、`scipy.fftpack.dct` 使用
- **DWT方式**: ロバスト、`pywt` ライブラリ使用
- **暗号化**: `hashlib` でキーからシード生成、埋め込み位置シャッフル

### C2PA対応
`c2pa-python` ライブラリを使用:
```python
from c2pa import Builder, SigningAlg
builder = Builder()
builder.add_resource("image.png", image_bytes)
builder.sign(cert, private_key, SigningAlg.PS256)
```

## テスト方法

### ComfyUI起動
```bash
# macOS (ComfyUI.app)
open -a "ComfyUI"

# 手動起動
cd /path/to/ComfyUI
python main.py
```

### ノードの確認
1. ComfyUI起動後、ノードブラウザで「AICU」検索
2. `Save Image (Watermark) 💧` が表示されれば成功
3. `examples/` のワークフローをロードしてテスト

### 不可視透かしテスト
1. `invisible_watermark = "test message"` で保存
2. 保存画像を `LoadImage` で読み込み
3. `Extract Hidden Watermark 🔍` で抽出
4. `hidden_message` が "test message" なら成功

## コーディング規約

- Python 3.10+ 互換
- 型ヒント使用推奨
- docstring は日本語OK
- ソースコード内の仕様コメントは `【】` で囲む
- TODO は `# TODO:` 形式で記載

## 関連リソース

- [ComfyUI Custom Node Guide](https://docs.comfy.org/essentials/custom_node_overview)
- [PIL/Pillow Documentation](https://pillow.readthedocs.io/)
- [C2PA Specification](https://c2pa.org/specifications/)
