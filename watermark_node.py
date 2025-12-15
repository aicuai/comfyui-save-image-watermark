"""
ComfyUI Save Image Local with Watermark
透かし機能付き画像保存ノード

Original: https://github.com/yhayano-ponotech/comfyui-save-image-local
Fork: AICU Japan Inc.
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


class LocalSaveImageWithWatermark:
    """
    透かし（Watermark）付きで画像を保存するComfyUIノード
    
    Features:
    - テキスト透かし（カスタマイズ可能）
    - 画像透かし（ロゴ等）
    - 不可視透かし（ステガノグラフィ）
    - メタデータ埋め込み
    - ハッシュ値生成（来歴用）
    """
    
    CATEGORY = "AICU/Save"
    FUNCTION = "save_with_watermark"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "STRING")  # filename, hash
    RETURN_NAMES = ("filename", "content_hash")
    
    # 透かし位置オプション
    POSITION_OPTIONS = [
        "bottom_right",
        "bottom_left", 
        "top_right",
        "top_left",
        "center",
        "tile"  # タイル状に繰り返し
    ]
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "prefix": ("STRING", {"default": "aicuty"}),
                "file_format": (["PNG", "JPEG", "WEBP"],),
            },
            "optional": {
                # テキスト透かし
                "watermark_text": ("STRING", {"default": "© AICU"}),
                "watermark_enabled": ("BOOLEAN", {"default": True}),
                "watermark_position": (cls.POSITION_OPTIONS, {"default": "bottom_left"}),
                "watermark_opacity": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05}),
                "watermark_font_size": ("INT", {"default": 24, "min": 8, "max": 128, "step": 1}),
                "watermark_color": ("STRING", {"default": "#FFFFFF"}),
                
                # 画像透かし（ロゴ）
                "watermark_image": ("IMAGE", {"default": None}),
                "watermark_image_scale": ("FLOAT", {"default": 0.15, "min": 0.01, "max": 0.5, "step": 0.01}),
                
                # 不可視透かし（ステガノグラフィ）
                "invisible_watermark": ("STRING", {"default": ""}),
                "invisible_watermark_enabled": ("BOOLEAN", {"default": False}),
                
                # メタデータ
                "embed_metadata": ("BOOLEAN", {"default": True}),
                "metadata_json": ("STRING", {"default": "{}"}),
                
                # 品質設定
                "jpeg_quality": ("INT", {"default": 95, "min": 1, "max": 100, "step": 1}),
                "webp_quality": ("INT", {"default": 90, "min": 1, "max": 100, "step": 1}),
            }
        }
    
    def __init__(self):
        self.output_dir = "output"
        self.counter = 0
    
    def hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """16進数カラーコードをRGBに変換"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """フォントを取得（フォールバック付き）"""
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
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except:
                    continue
        
        # フォールバック: デフォルトフォント
        return ImageFont.load_default()
    
    def add_text_watermark(
        self,
        image: Image.Image,
        text: str,
        position: str,
        opacity: float,
        font_size: int,
        color: str
    ) -> Image.Image:
        """テキスト透かしを追加"""
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
        
        # 位置計算
        padding = 20
        img_width, img_height = image.size
        
        if position == "bottom_right":
            x = img_width - text_width - padding
            y = img_height - text_height - padding
        elif position == "bottom_left":
            x = padding
            y = img_height - text_height - padding
        elif position == "top_right":
            x = img_width - text_width - padding
            y = padding
        elif position == "top_left":
            x = padding
            y = padding
        elif position == "center":
            x = (img_width - text_width) // 2
            y = (img_height - text_height) // 2
        elif position == "tile":
            # タイル状に配置
            for ty in range(0, img_height, text_height + 100):
                for tx in range(0, img_width, text_width + 100):
                    draw.text((tx, ty), text, font=font, fill=(*rgb_color, alpha))
            image = Image.alpha_composite(image, watermark_layer)
            return image
        else:
            x = img_width - text_width - padding
            y = img_height - text_height - padding
        
        draw.text((x, y), text, font=font, fill=(*rgb_color, alpha))
        image = Image.alpha_composite(image, watermark_layer)
        
        return image
    
    def add_image_watermark(
        self,
        image: Image.Image,
        watermark_tensor: torch.Tensor,
        position: str,
        scale: float,
        opacity: float
    ) -> Image.Image:
        """画像透かし（ロゴ）を追加"""
        if watermark_tensor is None:
            return image
        
        # テンソルをPIL画像に変換
        wm_np = watermark_tensor.cpu().numpy()
        if len(wm_np.shape) == 4:
            wm_np = wm_np[0]  # バッチの最初を使用
        wm_np = (wm_np * 255).clip(0, 255).astype(np.uint8)
        watermark = Image.fromarray(wm_np)
        
        # スケーリング
        img_width, img_height = image.size
        wm_width = int(img_width * scale)
        wm_height = int(watermark.height * (wm_width / watermark.width))
        watermark = watermark.resize((wm_width, wm_height), Image.Resampling.LANCZOS)
        
        # 透明度適用
        if watermark.mode != 'RGBA':
            watermark = watermark.convert('RGBA')
        
        alpha = watermark.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        watermark.putalpha(alpha)
        
        # 位置計算
        padding = 20
        
        if position == "bottom_right":
            x = img_width - wm_width - padding
            y = img_height - wm_height - padding
        elif position == "bottom_left":
            x = padding
            y = img_height - wm_height - padding
        elif position == "top_right":
            x = img_width - wm_width - padding
            y = padding
        elif position == "top_left":
            x = padding
            y = padding
        elif position == "center":
            x = (img_width - wm_width) // 2
            y = (img_height - wm_height) // 2
        else:
            x = img_width - wm_width - padding
            y = img_height - wm_height - padding
        
        # RGBA変換して合成
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        image.paste(watermark, (x, y), watermark)
        
        return image
    
    def embed_invisible_watermark(self, image: Image.Image, message: str) -> Image.Image:
        """
        不可視透かし（LSBステガノグラフィ）を埋め込む
        画像の最下位ビットにメッセージを隠す
        """
        if not message:
            return image
        
        # バイナリメッセージ作成
        binary_message = ''.join(format(ord(c), '08b') for c in message)
        binary_message += '00000000' * 4  # 終端マーカー
        
        # RGB変換
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        pixels = np.array(image)
        flat = pixels.flatten()
        
        # LSB埋め込み
        for i, bit in enumerate(binary_message):
            if i >= len(flat):
                break
            flat[i] = (flat[i] & 0xFE) | int(bit)
        
        pixels = flat.reshape(pixels.shape)
        return Image.fromarray(pixels.astype(np.uint8))
    
    def calculate_content_hash(self, image: Image.Image) -> str:
        """画像のSHA-256ハッシュを計算（来歴用）"""
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return hashlib.sha256(buffer.getvalue()).hexdigest()
    
    def create_metadata(
        self,
        original_hash: str,
        watermarked_hash: str,
        additional_metadata: dict
    ) -> dict:
        """メタデータを作成"""
        metadata = {
            "generator": "AICU ComfyUI",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "content_hash": {
                "original": original_hash,
                "watermarked": watermarked_hash,
                "algorithm": "SHA-256"
            },
            "watermark": {
                "applied": True,
                "type": ["text", "invisible"]
            }
        }
        
        # 追加メタデータをマージ
        if additional_metadata:
            metadata.update(additional_metadata)
        
        return metadata
    
    def save_with_watermark(
        self,
        images: torch.Tensor,
        prefix: str,
        file_format: str,
        watermark_text: str = "© AICU",
        watermark_enabled: bool = True,
        watermark_position: str = "bottom_right",
        watermark_opacity: float = 0.3,
        watermark_font_size: int = 24,
        watermark_color: str = "#FFFFFF",
        watermark_image: Optional[torch.Tensor] = None,
        watermark_image_scale: float = 0.15,
        invisible_watermark: str = "",
        invisible_watermark_enabled: bool = False,
        embed_metadata: bool = True,
        metadata_json: str = "{}",
        jpeg_quality: int = 95,
        webp_quality: int = 90
    ) -> Tuple[str, str]:
        """画像を透かし付きで保存"""
        
        results = []
        
        # タイムスタンプ生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # バッチ処理
        batch_size = images.shape[0]
        
        for i in range(batch_size):
            # テンソルをPIL画像に変換
            img_np = images[i].cpu().numpy()
            img_np = (img_np * 255).clip(0, 255).astype(np.uint8)
            image = Image.fromarray(img_np)
            
            # オリジナルのハッシュ
            original_hash = self.calculate_content_hash(image)
            
            # テキスト透かし
            if watermark_enabled and watermark_text:
                image = self.add_text_watermark(
                    image,
                    watermark_text,
                    watermark_position,
                    watermark_opacity,
                    watermark_font_size,
                    watermark_color
                )
            
            # 画像透かし
            if watermark_image is not None:
                image = self.add_image_watermark(
                    image,
                    watermark_image,
                    watermark_position,
                    watermark_image_scale,
                    watermark_opacity
                )
            
            # 不可視透かし
            if invisible_watermark_enabled and invisible_watermark:
                image = self.embed_invisible_watermark(image, invisible_watermark)
            
            # RGB変換（保存用）
            if image.mode == 'RGBA':
                # 白背景で合成
                background = Image.new('RGB', image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3])
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # 透かし後のハッシュ
            watermarked_hash = self.calculate_content_hash(image)
            
            # ファイル名生成
            self.counter += 1
            ext = file_format.lower()
            if ext == 'jpeg':
                ext = 'jpg'
            filename = f"{prefix}_{timestamp}_{self.counter:03d}.{ext}"
            
            # 保存データ作成
            buffer = BytesIO()
            
            # メタデータ
            pnginfo = None
            exif = None
            
            if embed_metadata:
                try:
                    additional = json.loads(metadata_json) if metadata_json else {}
                except:
                    additional = {}
                
                metadata = self.create_metadata(original_hash, watermarked_hash, additional)
                
                if file_format == "PNG":
                    from PIL import PngImagePlugin
                    pnginfo = PngImagePlugin.PngInfo()
                    pnginfo.add_text("aicu_metadata", json.dumps(metadata))
                    pnginfo.add_text("content_hash", watermarked_hash)
            
            # 保存
            if file_format == "PNG":
                image.save(buffer, format='PNG', pnginfo=pnginfo)
            elif file_format == "JPEG":
                image.save(buffer, format='JPEG', quality=jpeg_quality)
            elif file_format == "WEBP":
                image.save(buffer, format='WEBP', quality=webp_quality)
            
            # Base64エンコード（ブラウザダウンロード用）
            buffer.seek(0)
            base64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            results.append({
                "filename": filename,
                "hash": watermarked_hash,
                "data": base64_data,
                "format": file_format.lower()
            })
        
        # UIに結果を返す
        return {
            "ui": {
                "images": results
            },
            "result": (results[0]["filename"], results[0]["hash"])
        }


class ExtractInvisibleWatermark:
    """不可視透かしを抽出するノード"""
    
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
        """LSBステガノグラフィから隠しメッセージを抽出"""
        
        # テンソルをPIL画像に変換
        img_np = image[0].cpu().numpy()
        img_np = (img_np * 255).clip(0, 255).astype(np.uint8)
        pil_image = Image.fromarray(img_np)
        
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        
        pixels = np.array(pil_image).flatten()
        
        # LSB抽出
        binary_message = ''
        for pixel in pixels[:max_length * 8 + 32]:  # 終端マーカー分も含める
            binary_message += str(pixel & 1)
        
        # バイナリからテキストに変換
        message = ''
        for i in range(0, len(binary_message), 8):
            byte = binary_message[i:i+8]
            if len(byte) < 8:
                break
            char_code = int(byte, 2)
            if char_code == 0:  # 終端
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
