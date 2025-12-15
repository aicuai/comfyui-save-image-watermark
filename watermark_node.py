"""
ComfyUI Save Image with Watermark
透かし機能付き画像保存ノード

Original: https://github.com/yhayano-ponotech/comfyui-save-image-local
Fork: AICU Japan Inc.

================================================================================
WATERMARK PROCESSING SPECIFICATION (透かし処理仕様)
================================================================================

【処理順序 / Processing Order】
1. 画像ロゴ透かし (Image Logo Watermark)
   - MASKを使用してアルファチャンネルを決定
   - MASK領域のみにopacityでブレンド
   - 透明部分は完全にスキップ（黒浮き・白浮きなし）

2. テキスト透かし (Text Watermark)
   - 画像ロゴの上に配置
   - 将来的にステガノグラフィ処理の影響を受けない位置に

3. 不可視透かし (Invisible Watermark / Steganography)
   - 最後に処理（テキスト透かしより後）
   - LSB (Least Significant Bit) 方式
   - RGBチャンネルのみ変更、アルファは保持

【画像ロゴブレンディング仕様 / Image Logo Blending Spec】
- 入力: IMAGE (RGB) + MASK (アルファチャンネル)
- MASK値が0の部分: 完全透明（ブレンドしない）
- MASK値が255の部分: opacity値でブレンド
- 計算式: result = base * (1 - mask * opacity) + logo * (mask * opacity)

【テキスト透かし仕様 / Text Watermark Spec】
- 色: HEX形式 (#RRGGBB)
- 透明度: opacity (0.0-1.0)
- フォント: システムフォント自動検出

【将来の拡張予定 / Future Extensions (TODO)】

[テキスト装飾 / Text Decoration]
- font_path: カスタムフォントパス指定
- font_family: フォントファミリー選択 (システムフォント一覧から)
- stroke_enabled: 縁取り有効化
- stroke_color: 縁取り色 (#RRGGBB)
- stroke_width: 縁取り太さ (px)
- shadow_enabled: ドロップシャドウ有効化
- shadow_color: 影の色
- shadow_offset_x: 影のXオフセット
- shadow_offset_y: 影のYオフセット
- shadow_blur: 影のぼかし半径
- text_rotation: テキスト回転角度 (度)
- background_enabled: テキスト背景ボックス
- background_color: 背景色
- background_padding: 背景パディング

[高度なステガノグラフィ / Advanced Steganography]
- steganography_method: 方式選択 (lsb, dct, dwt, spread_spectrum)
- steganography_strength: 埋め込み強度
- steganography_key: 暗号化キー（位置シャッフル用）
- steganography_error_correction: エラー訂正符号有効化

[画像ロゴ拡張 / Image Logo Extensions]
- logo_rotation: ロゴ回転角度
- logo_blend_mode: ブレンドモード (normal, multiply, screen, overlay)
- logo_padding: 端からのパディング調整

[C2PA対応 / C2PA Support]
- c2pa_enabled: C2PA署名有効化
- c2pa_certificate: 証明書パス
- c2pa_private_key: 秘密鍵パス

================================================================================
"""

import os
import json
import base64
import hashlib
from datetime import datetime
from io import BytesIO
from typing import Optional, Tuple, List, Dict, Any

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

# ComfyUI imports
import folder_paths
from server import PromptServer


class LocalSaveImageWithWatermark:
    """
    透かし（Watermark）付きで画像を保存するComfyUIノード

    Features:
    - 画像透かし（ロゴ、MASK対応、正確なアルファブレンディング）
    - テキスト透かし（色・位置・サイズ指定可能）
    - 不可視透かし（ステガノグラフィ、最後に処理）
    - メタデータ埋め込み（ワークフロー含む）
    - output フォルダ保存 + ブラウザダウンロード両対応
    """

    CATEGORY = "AICU/Save"
    FUNCTION = "save_with_watermark"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "filename", "content_hash")

    # 透かし位置オプション
    POSITION_OPTIONS = [
        "bottom_right",
        "bottom_left",
        "top_right",
        "top_left",
        "center",
        "tile"
    ]

    # 保存先オプション
    SAVE_OPTIONS = [
        "output_folder",
        "browser_download",
        "both"
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "aicuty"}),
                "file_format": (["PNG", "JPEG", "WEBP"],),
            },
            "optional": {
                # === 保存先設定 ===
                "save_to": (cls.SAVE_OPTIONS, {"default": "both"}),

                # === 画像透かし（ロゴ） ===
                # 処理順序: 1番目（最下層）
                "watermark_image": ("IMAGE",),
                "watermark_image_mask": ("MASK",),  # LoadImageのMASK出力を接続
                "watermark_image_position": (cls.POSITION_OPTIONS, {"default": "bottom_left"}),
                "watermark_image_scale": ("FLOAT", {"default": 0.15, "min": 0.01, "max": 1.0, "step": 0.01}),
                "watermark_image_opacity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),

                # === テキスト透かし ===
                # 処理順序: 2番目（画像ロゴの上）
                "watermark_text": ("STRING", {"default": "© AICU"}),
                "watermark_text_enabled": ("BOOLEAN", {"default": True}),
                "watermark_text_position": (cls.POSITION_OPTIONS, {"default": "bottom_right"}),
                "watermark_text_opacity": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05}),
                "watermark_text_size": ("INT", {"default": 24, "min": 8, "max": 128, "step": 1}),
                "watermark_text_color": ("STRING", {"default": "#FFFFFF"}),
                # TODO: font_path, stroke_color, stroke_width, shadow_* など

                # === 動的テキスト入力 ===
                # PrimitiveString などから接続して seed 等を表示
                "dynamic_text": ("STRING", {"forceInput": True}),

                # === 不可視透かし（ステガノグラフィ） ===
                # 処理順序: 3番目（最後）
                "invisible_watermark": ("STRING", {"default": ""}),
                "invisible_watermark_enabled": ("BOOLEAN", {"default": False}),
                # TODO: steganography_method, steganography_key など

                # === メタデータ ===
                "embed_workflow": ("BOOLEAN", {"default": True}),
                "embed_metadata": ("BOOLEAN", {"default": True}),
                "metadata_json": ("STRING", {"default": "{}"}),

                # === 品質設定 ===
                "jpeg_quality": ("INT", {"default": 95, "min": 1, "max": 100, "step": 1}),
                "webp_quality": ("INT", {"default": 90, "min": 1, "max": 100, "step": 1}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO"
            },
        }

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.compress_level = 4

    # =========================================================================
    # ユーティリティメソッド
    # =========================================================================

    def hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """16進数カラーコードをRGBに変換"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return (255, 255, 255)  # デフォルト白
        try:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except ValueError:
            return (255, 255, 255)

    def get_font(self, size: int, font_path: Optional[str] = None) -> ImageFont.FreeTypeFont:
        """
        フォントを取得（フォールバック付き）

        TODO: 将来的にfont_path引数でカスタムフォント対応
        TODO: フォントファミリー選択機能
        """
        # カスタムフォントが指定されている場合
        if font_path and os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except:
                pass

        # システムフォント検索
        font_paths = [
            # Linux
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            # macOS
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            # Windows
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/meiryo.ttc",
        ]

        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size)
                except:
                    continue

        return ImageFont.load_default()

    def calculate_position(
        self,
        position: str,
        img_width: int,
        img_height: int,
        obj_width: int,
        obj_height: int,
        padding: int = 20
    ) -> Tuple[int, int]:
        """オブジェクトの配置位置を計算"""
        positions = {
            "bottom_right": (img_width - obj_width - padding, img_height - obj_height - padding),
            "bottom_left": (padding, img_height - obj_height - padding),
            "top_right": (img_width - obj_width - padding, padding),
            "top_left": (padding, padding),
            "center": ((img_width - obj_width) // 2, (img_height - obj_height) // 2),
        }
        return positions.get(position, positions["bottom_right"])

    # =========================================================================
    # 画像ロゴ透かし処理
    # =========================================================================

    def add_image_watermark(
        self,
        base_image: Image.Image,
        logo_tensor: torch.Tensor,
        mask_tensor: Optional[torch.Tensor],
        position: str,
        scale: float,
        opacity: float
    ) -> Image.Image:
        """
        画像ロゴ透かしを追加

        【処理仕様】
        - MASKがある部分のみをopacityでブレンド
        - MASKがない部分（透明部分）は完全にスキップ
        - 黒浮き・白浮きなしの正確なアルファブレンディング

        Args:
            base_image: ベース画像
            logo_tensor: ロゴ画像テンソル (IMAGE)
            mask_tensor: マスクテンソル (MASK) - ロゴのアルファチャンネル
            position: 配置位置
            scale: スケール (0.01-1.0)
            opacity: 不透明度 (0.0-1.0)

        Returns:
            透かし合成後の画像
        """
        if logo_tensor is None:
            return base_image

        # テンソルをnumpy配列に変換
        logo_np = logo_tensor.cpu().numpy()
        if len(logo_np.shape) == 4:
            logo_np = logo_np[0]  # バッチの最初を使用
        logo_np = (logo_np * 255).clip(0, 255).astype(np.uint8)

        # RGB画像として作成
        if logo_np.shape[-1] >= 3:
            logo = Image.fromarray(logo_np[:, :, :3], mode='RGB')
        else:
            logo = Image.fromarray(logo_np).convert('RGB')

        # マスク（アルファチャンネル）の取得
        # ComfyUI LoadImageのMASK出力: 透明部分=1(白), 不透明部分=0(黒)
        # → 反転して intensity として使用: 不透明部分=255, 透明部分=0
        if mask_tensor is not None:
            # 外部MASKが提供された場合（反転して使用）
            mask_np = mask_tensor.cpu().numpy()
            if len(mask_np.shape) == 3:
                mask_np = mask_np[0]
            # 反転: 1→0, 0→255 (透明部分を0に、不透明部分を255に)
            mask_np = ((1.0 - mask_np) * 255).clip(0, 255).astype(np.uint8)
            alpha_mask = Image.fromarray(mask_np, mode='L')
        elif logo_np.shape[-1] == 4:
            # 元画像の4チャンネル目をアルファとして使用（そのまま）
            alpha_mask = Image.fromarray(logo_np[:, :, 3], mode='L')
        else:
            # マスクなし = 完全不透明
            alpha_mask = Image.new('L', logo.size, 255)

        # スケーリング
        img_width, img_height = base_image.size
        new_width = int(img_width * scale)
        new_height = int(logo.height * (new_width / logo.width))
        logo = logo.resize((new_width, new_height), Image.Resampling.LANCZOS)
        alpha_mask = alpha_mask.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # opacityをマスクに適用
        if opacity < 1.0:
            alpha_mask = alpha_mask.point(lambda p: int(p * opacity))

        # RGBAロゴを作成
        logo_rgba = logo.convert('RGBA')
        logo_rgba.putalpha(alpha_mask)

        # ベース画像をRGBAに変換
        if base_image.mode != 'RGBA':
            base_image = base_image.convert('RGBA')

        # 位置計算
        x, y = self.calculate_position(position, img_width, img_height, new_width, new_height)

        # 透明レイヤーにロゴを配置してアルファ合成
        overlay = Image.new('RGBA', base_image.size, (0, 0, 0, 0))
        overlay.paste(logo_rgba, (x, y), logo_rgba)
        result = Image.alpha_composite(base_image, overlay)

        return result

    # =========================================================================
    # テキスト透かし処理
    # =========================================================================

    def add_text_watermark(
        self,
        image: Image.Image,
        text: str,
        position: str,
        opacity: float,
        font_size: int,
        color: str,
        # TODO: 将来の拡張パラメータ
        # font_path: Optional[str] = None,
        # stroke_enabled: bool = False,
        # stroke_color: str = "#000000",
        # stroke_width: int = 2,
        # shadow_enabled: bool = False,
        # shadow_color: str = "#000000",
        # shadow_offset: Tuple[int, int] = (2, 2),
    ) -> Image.Image:
        """
        テキスト透かしを追加

        【処理仕様】
        - 画像ロゴの上に配置（処理順序2番目）
        - 透明レイヤーにテキストを描画してアルファ合成
        - ステガノグラフィ処理の前に実行

        TODO: 将来の拡張
        - カスタムフォント対応 (font_path)
        - 縁取り (stroke_enabled, stroke_color, stroke_width)
        - ドロップシャドウ (shadow_enabled, shadow_color, shadow_offset)
        - 背景ボックス
        - テキスト回転

        Args:
            image: ベース画像
            text: 透かしテキスト
            position: 配置位置
            opacity: 不透明度
            font_size: フォントサイズ
            color: テキスト色 (#RRGGBB)

        Returns:
            テキスト透かし合成後の画像
        """
        if not text:
            return image

        # RGBA変換
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        # 透かしレイヤー作成
        watermark_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)

        font = self.get_font(font_size)
        rgb_color = self.hex_to_rgb(color)
        alpha = int(255 * opacity)

        # テキストサイズ取得
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        img_width, img_height = image.size

        if position == "tile":
            # タイル状に配置
            spacing_x = text_width + 100
            spacing_y = text_height + 100
            for ty in range(0, img_height, spacing_y):
                for tx in range(0, img_width, spacing_x):
                    # TODO: 将来的に縁取り対応
                    # if stroke_enabled:
                    #     draw.text((tx, ty), text, font=font,
                    #               stroke_width=stroke_width,
                    #               stroke_fill=(*self.hex_to_rgb(stroke_color), alpha))
                    draw.text((tx, ty), text, font=font, fill=(*rgb_color, alpha))
        else:
            x, y = self.calculate_position(position, img_width, img_height, text_width, text_height)
            # TODO: ドロップシャドウ対応
            # if shadow_enabled:
            #     shadow_rgb = self.hex_to_rgb(shadow_color)
            #     draw.text((x + shadow_offset[0], y + shadow_offset[1]),
            #               text, font=font, fill=(*shadow_rgb, alpha // 2))
            draw.text((x, y), text, font=font, fill=(*rgb_color, alpha))

        # アルファ合成
        result = Image.alpha_composite(image, watermark_layer)

        return result

    # =========================================================================
    # 不可視透かし処理（ステガノグラフィ）
    # =========================================================================

    def embed_invisible_watermark(
        self,
        image: Image.Image,
        message: str,
        # TODO: 将来の拡張パラメータ
        # method: str = "lsb",  # lsb, dct, dwt, spread_spectrum
        # key: Optional[str] = None,  # 暗号化キー
        # strength: float = 1.0,  # 埋め込み強度
    ) -> Image.Image:
        """
        不可視透かし（ステガノグラフィ）を埋め込む

        【処理仕様】
        - 処理順序: 最後（テキスト透かしの後）
        - RGBチャンネルのLSBにメッセージを埋め込み
        - アルファチャンネルは変更しない（透明度保持）

        TODO: 将来の拡張
        - DCT (Discrete Cosine Transform) 方式
        - DWT (Discrete Wavelet Transform) 方式
        - Spread Spectrum 方式
        - 暗号化キーによる位置シャッフル
        - エラー訂正符号

        Args:
            image: ベース画像
            message: 埋め込むメッセージ

        Returns:
            ステガノグラフィ処理後の画像
        """
        if not message:
            return image

        # メッセージをバイナリに変換
        binary_message = ''.join(format(ord(c), '08b') for c in message)
        binary_message += '00000000' * 4  # 終端マーカー

        # アルファチャンネルを保存
        original_alpha = None
        if image.mode == 'RGBA':
            original_alpha = image.split()[3]
            rgb_image = image.convert('RGB')
        elif image.mode == 'RGB':
            rgb_image = image
        else:
            rgb_image = image.convert('RGB')

        # LSB埋め込み
        pixels = np.array(rgb_image)
        flat = pixels.flatten()

        for i, bit in enumerate(binary_message):
            if i >= len(flat):
                break
            flat[i] = (flat[i] & 0xFE) | int(bit)

        pixels = flat.reshape(pixels.shape)
        result = Image.fromarray(pixels.astype(np.uint8), mode='RGB')

        # アルファチャンネルを復元
        if original_alpha is not None:
            result = result.convert('RGBA')
            r, g, b, _ = result.split()
            result = Image.merge('RGBA', (r, g, b, original_alpha))

        return result

    # =========================================================================
    # ハッシュ・メタデータ処理
    # =========================================================================

    def calculate_content_hash(self, image: Image.Image) -> str:
        """画像のSHA-256ハッシュを計算（来歴用）"""
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return hashlib.sha256(buffer.getvalue()).hexdigest()

    def create_aicu_metadata(
        self,
        original_hash: str,
        watermarked_hash: str,
        additional_metadata: dict
    ) -> dict:
        """AICU独自メタデータを作成"""
        metadata = {
            "generator": "AICU ComfyUI Watermark",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "content_hash": {
                "original": original_hash,
                "watermarked": watermarked_hash,
                "algorithm": "SHA-256"
            },
            "watermark": {
                "applied": True,
                "types": ["image_logo", "text", "invisible"]
            }
        }

        if additional_metadata:
            metadata.update(additional_metadata)

        return metadata

    # =========================================================================
    # メイン処理
    # =========================================================================

    def save_with_watermark(
        self,
        images: torch.Tensor,
        filename_prefix: str,
        file_format: str,
        save_to: str = "both",
        # 画像ロゴ透かし
        watermark_image: Optional[torch.Tensor] = None,
        watermark_image_mask: Optional[torch.Tensor] = None,
        watermark_image_position: str = "bottom_left",
        watermark_image_scale: float = 0.15,
        watermark_image_opacity: float = 1.0,
        # テキスト透かし
        watermark_text: str = "© AICU",
        watermark_text_enabled: bool = True,
        watermark_text_position: str = "bottom_right",
        watermark_text_opacity: float = 0.9,
        watermark_text_size: int = 24,
        watermark_text_color: str = "#FFFFFF",
        # 動的テキスト
        dynamic_text: str = "",
        # 不可視透かし
        invisible_watermark: str = "",
        invisible_watermark_enabled: bool = False,
        # メタデータ
        embed_workflow: bool = True,
        embed_metadata: bool = True,
        metadata_json: str = "{}",
        # 品質
        jpeg_quality: int = 95,
        webp_quality: int = 90,
        # hidden
        prompt=None,
        extra_pnginfo=None
    ) -> Tuple[str, str]:
        """
        透かし付きで画像を保存

        【処理順序】
        1. 画像ロゴ透かし（MASK領域のみブレンド）
        2. テキスト透かし（ロゴの上に配置）
        3. 不可視透かし（最後に処理）
        4. ファイル保存
        """

        # 保存パス取得
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix,
            self.output_dir,
            images[0].shape[1],
            images[0].shape[0]
        )

        results = []
        browser_images = []
        output_images = []  # IMAGE出力用
        batch_size = images.shape[0]

        # 動的テキストを結合（そのまま連結、間に何も入れない）
        final_text = watermark_text
        if dynamic_text:
            final_text = f"{watermark_text}{dynamic_text}"

        for batch_number in range(batch_size):
            # テンソルをPIL画像に変換
            img_np = images[batch_number].cpu().numpy()
            img_np = (img_np * 255).clip(0, 255).astype(np.uint8)

            if img_np.shape[-1] == 4:
                image = Image.fromarray(img_np, mode='RGBA')
            else:
                image = Image.fromarray(img_np, mode='RGB')

            # オリジナルハッシュ
            original_hash = self.calculate_content_hash(image)

            # ===============================
            # 1. 画像ロゴ透かし（最下層）
            # ===============================
            if watermark_image is not None:
                image = self.add_image_watermark(
                    image,
                    watermark_image,
                    watermark_image_mask,
                    watermark_image_position,
                    watermark_image_scale,
                    watermark_image_opacity
                )

            # ===============================
            # 2. テキスト透かし（ロゴの上）
            # ===============================
            if watermark_text_enabled and final_text:
                image = self.add_text_watermark(
                    image,
                    final_text,
                    watermark_text_position,
                    watermark_text_opacity,
                    watermark_text_size,
                    watermark_text_color
                )

            # ===============================
            # 3. 不可視透かし（最後）
            # ===============================
            if invisible_watermark_enabled and invisible_watermark:
                image = self.embed_invisible_watermark(image, invisible_watermark)

            # フォーマット変換
            if file_format != "PNG":
                if image.mode == 'RGBA':
                    background = Image.new('RGB', image.size, (255, 255, 255))
                    background.paste(image, mask=image.split()[3])
                    image = background
                elif image.mode != 'RGB':
                    image = image.convert('RGB')

            # 透かし後ハッシュ
            watermarked_hash = self.calculate_content_hash(image)

            # ファイル名生成
            filename_with_batch = filename.replace("%batch_num%", str(batch_number))
            ext = 'jpg' if file_format == 'JPEG' else file_format.lower()
            file = f"{filename_with_batch}_{counter:05}_.{ext}"

            # メタデータ
            pnginfo = None
            if file_format == "PNG":
                pnginfo = PngInfo()

                if embed_workflow:
                    if prompt is not None:
                        pnginfo.add_text("prompt", json.dumps(prompt))
                    if extra_pnginfo is not None:
                        for key in extra_pnginfo:
                            pnginfo.add_text(key, json.dumps(extra_pnginfo[key]))

                if embed_metadata:
                    try:
                        additional = json.loads(metadata_json) if metadata_json else {}
                    except:
                        additional = {}
                    aicu_metadata = self.create_aicu_metadata(original_hash, watermarked_hash, additional)
                    pnginfo.add_text("aicu_metadata", json.dumps(aicu_metadata))
                    pnginfo.add_text("content_hash", watermarked_hash)

            # 保存
            if save_to in ["output_folder", "both"]:
                file_path = os.path.join(full_output_folder, file)
                if file_format == "PNG":
                    image.save(file_path, pnginfo=pnginfo, compress_level=self.compress_level)
                elif file_format == "JPEG":
                    image.save(file_path, quality=jpeg_quality)
                elif file_format == "WEBP":
                    image.save(file_path, quality=webp_quality)

                results.append({
                    "filename": file,
                    "subfolder": subfolder,
                    "type": self.type
                })

            # ブラウザダウンロード
            if save_to in ["browser_download", "both"]:
                buffer = BytesIO()
                if file_format == "PNG":
                    image.save(buffer, format='PNG', pnginfo=pnginfo)
                elif file_format == "JPEG":
                    image.save(buffer, format='JPEG', quality=jpeg_quality)
                elif file_format == "WEBP":
                    image.save(buffer, format='WEBP', quality=webp_quality)

                buffer.seek(0)
                base64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
                browser_images.append({
                    "filename": file,
                    "data": base64_data,
                    "format": ext
                })

            # IMAGE出力用にテンソル変換
            # RGBに変換（ComfyUI IMAGE形式）
            if image.mode == 'RGBA':
                # RGBAの場合はRGBに変換（アルファは破棄）
                output_image = image.convert('RGB')
            else:
                output_image = image
            output_np = np.array(output_image).astype(np.float32) / 255.0
            output_images.append(output_np)

            counter += 1

        # ブラウザダウンロードトリガー
        if browser_images:
            PromptServer.instance.send_sync("local_save_data", {"images": browser_images})

        # IMAGE出力用テンソル作成
        output_tensor = torch.from_numpy(np.stack(output_images))

        return {
            "ui": {
                "images": results if results else [{"filename": browser_images[0]["filename"], "subfolder": "", "type": "output"}]
            },
            "result": (
                output_tensor,
                results[0]["filename"] if results else browser_images[0]["filename"],
                watermarked_hash
            )
        }


class ExtractInvisibleWatermark:
    """
    不可視透かし（ステガノグラフィ）を抽出するノード

    【処理仕様】
    - LSB方式で埋め込まれたメッセージを抽出
    - 終端マーカー（null文字×4）まで読み取り
    """

    CATEGORY = "AICU/Watermark"
    FUNCTION = "extract"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("hidden_message",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "max_length": ("INT", {"default": 1000, "min": 1, "max": 10000}),
            }
        }

    def extract(self, image: torch.Tensor, max_length: int = 1000) -> Tuple[str]:
        """LSBステガノグラフィからメッセージを抽出"""

        img_np = image[0].cpu().numpy()
        img_np = (img_np * 255).clip(0, 255).astype(np.uint8)
        pil_image = Image.fromarray(img_np)

        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')

        pixels = np.array(pil_image).flatten()

        # LSB抽出
        binary_message = ''
        for pixel in pixels[:max_length * 8 + 32]:
            binary_message += str(pixel & 1)

        # バイナリ→テキスト変換
        message = ''
        for i in range(0, len(binary_message), 8):
            byte = binary_message[i:i+8]
            if len(byte) < 8:
                break
            char_code = int(byte, 2)
            if char_code == 0:  # 終端マーカー
                break
            message += chr(char_code)

        return (message,)


# ノード登録
NODE_CLASS_MAPPINGS = {
    "LocalSaveImageWithWatermark": LocalSaveImageWithWatermark,
    "ExtractInvisibleWatermark": ExtractInvisibleWatermark,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LocalSaveImageWithWatermark": "Save Image (Watermark) 💧",
    "ExtractInvisibleWatermark": "Extract Hidden Watermark 🔍",
}
