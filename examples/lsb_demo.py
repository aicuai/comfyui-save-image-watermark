#!/usr/bin/env python3
"""
LSB（Least Significant Bit）ステガノグラフィ デモスクリプト

このスクリプトは、画像に隠されたメッセージを抽出し、
LSBの仕組みを視覚的に解説します。

============================================================
セットアップ方法（初回のみ）
============================================================

# 1. このディレクトリに移動
cd examples

# 2. Python仮想環境を作成
python3 -m venv venv

# 3. 仮想環境を有効化
#    macOS/Linux:
source venv/bin/activate
#    Windows:
#    venv\\Scripts\\activate

# 4. 必要なライブラリをインストール
pip install Pillow

============================================================
使い方
============================================================

# サンプル画像から隠しメッセージを抽出
python lsb_demo.py

# 指定画像から抽出
python lsb_demo.py your_image.png

# メッセージを埋め込み
python lsb_demo.py --embed "秘密のメッセージ" output.png

# 元画像を指定して埋め込み
python lsb_demo.py --embed "秘密" output.png source.png

# グレー画像を生成して実験
python lsb_demo.py --create-gray

============================================================
"""

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("❌ PILが必要です: pip install Pillow")
    sys.exit(1)


def visualize_lsb_concept():
    """LSBの仕組みを視覚的に解説"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           🔐 LSB（最下位ビット）ステガノグラフィ解説            ║
╚══════════════════════════════════════════════════════════════════╝

【ピクセルの色はどう表現される？】

    1ピクセル = R(赤) + G(緑) + B(青)
    各色 = 0〜255 の値 = 8ビット(2進数)

    例: 黄色っぽいピクセル
    ┌─────────────────────────────────────┐
    │  R = 254  →  1111111[0]            │
    │  G = 215  →  1101011[1]            │
    │  B = 102  →  0110011[0]            │
    └─────────────────────────────────────┘
                        ↑
                    最下位ビット(LSB)
                    ここを変えても色はほぼ変わらない！


【メッセージの埋め込み】

    "Hi" を埋め込む場合:

    H = 72  = 01001000
    i = 105 = 01101001

    ピクセル1: R[0], G[1], B[0]  → "010"
    ピクセル2: R[0], G[1], B[0]  → "010"
    ピクセル3: R[0], G[0], B[0]  → "000"  ← Hの8ビット完了
    ...以下続く


【なぜバレない？】

    元の色:  R=254, G=215, B=102  →  ██ (黄色)
    変更後:  R=255, G=214, B=102  →  ██ (ほぼ同じ黄色)

    人間の目では区別できない！ 👁️

""")


def extract_lsb(image_path: str) -> str:
    """画像からLSBメッセージを抽出"""
    img = Image.open(image_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')

    pixels = list(img.getdata())
    bits = []

    for pixel in pixels:
        for channel in pixel[:3]:  # R, G, B
            bits.append(channel & 1)

    # ビットをバイトに変換
    message_bytes = []
    null_count = 0

    for i in range(0, len(bits) - 7, 8):
        byte_val = 0
        for j in range(8):
            byte_val = (byte_val << 1) | bits[i + j]

        if byte_val == 0:
            null_count += 1
            if null_count >= 4:  # 終端マーカー検出
                break
        else:
            null_count = 0
            message_bytes.append(byte_val)

    try:
        return bytes(message_bytes).decode('utf-8')
    except UnicodeDecodeError:
        return bytes(message_bytes).decode('utf-8', errors='replace')


def embed_lsb(image_path: str, message: str, output_path: str):
    """画像にLSBメッセージを埋め込み"""
    img = Image.open(image_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # メッセージをビット列に変換（終端マーカー付き）
    message_bytes = message.encode('utf-8') + b'\x00\x00\x00\x00'
    bits = []
    for byte in message_bytes:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)

    pixels = list(img.getdata())

    if len(bits) > len(pixels) * 3:
        print(f"❌ メッセージが長すぎます（最大 {len(pixels) * 3 // 8} バイト）")
        return False

    new_pixels = []
    bit_idx = 0

    for pixel in pixels:
        new_pixel = list(pixel)
        for c in range(3):  # R, G, B
            if bit_idx < len(bits):
                new_pixel[c] = (pixel[c] & ~1) | bits[bit_idx]
                bit_idx += 1
        new_pixels.append(tuple(new_pixel))

    new_img = Image.new('RGB', img.size)
    new_img.putdata(new_pixels)
    new_img.save(output_path, 'PNG')
    return True


def show_first_pixels(image_path: str, count: int = 5):
    """最初の数ピクセルのLSBを可視化"""
    img = Image.open(image_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')

    pixels = list(img.getdata())[:count]

    print(f"\n📊 最初の{count}ピクセルのLSB解析:\n")
    print("┌─────┬───────────────┬───────────────┬───────────────┬─────────┐")
    print("│ No. │      R        │      G        │      B        │  LSBs   │")
    print("├─────┼───────────────┼───────────────┼───────────────┼─────────┤")

    for i, pixel in enumerate(pixels):
        r, g, b = pixel[:3]
        r_bin = format(r, '08b')
        g_bin = format(g, '08b')
        b_bin = format(b, '08b')
        lsbs = f"{r & 1}{g & 1}{b & 1}"

        # LSBを強調表示
        r_display = f"{r_bin[:7]}[{r_bin[7]}]"
        g_display = f"{g_bin[:7]}[{g_bin[7]}]"
        b_display = f"{b_bin[:7]}[{b_bin[7]}]"

        print(f"│ {i+1:3} │ {r_display:13} │ {g_display:13} │ {b_display:13} │   {lsbs}   │")

    print("└─────┴───────────────┴───────────────┴───────────────┴─────────┘")
    print("                                                        ↑")
    print("                                          これを集めてメッセージに復元！")


def create_gray_image(size: int = 128, gray_value: int = 128) -> str:
    """グレー画像を生成して保存"""
    script_dir = Path(__file__).parent
    output_path = script_dir / f"gray{gray_value}_{size}x{size}.png"

    img = Image.new('RGB', (size, size), (gray_value, gray_value, gray_value))
    img.save(output_path, 'PNG')
    return str(output_path)


def run_gray_experiment():
    """グレー画像でLSB埋め込み実験"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║              🧪 グレー画像でLSB実験                              ║
╚══════════════════════════════════════════════════════════════════╝
""")

    script_dir = Path(__file__).parent

    # Step 1: グレー画像生成
    print("【Step 1】グレー画像を生成")
    print("-" * 50)
    gray_path = create_gray_image(128, 128)
    print(f"   ✅ 生成: {gray_path}")
    print(f"   　 色: RGB(128, 128, 128) = グレー50%")
    print(f"   　 サイズ: 128x128 ピクセル")

    # 元画像のピクセル表示
    print("\n   元のピクセル値（すべて同じ）:")
    img = Image.open(gray_path)
    pixel = img.getpixel((0, 0))
    print(f"   　 R={pixel[0]:3d} = {format(pixel[0], '08b')}")
    print(f"   　 G={pixel[1]:3d} = {format(pixel[1], '08b')}")
    print(f"   　 B={pixel[2]:3d} = {format(pixel[2], '08b')}")
    print(f"   　 LSB = {pixel[0]&1}{pixel[1]&1}{pixel[2]&1}")

    # Step 2: メッセージ埋め込み
    print("\n\n【Step 2】秘密メッセージを埋め込み")
    print("-" * 50)
    secret_message = "Hello LSB!"
    output_path = str(script_dir / "gray128_with_secret.png")

    print(f"   メッセージ: \"{secret_message}\"")
    print(f"   バイト列: {secret_message.encode('utf-8')}")
    print(f"   ビット列（先頭16ビット）:")

    bits = ''.join(format(b, '08b') for b in secret_message.encode('utf-8')[:2])
    print(f"   　 '{secret_message[0]}' = {format(ord(secret_message[0]), '08b')}")
    print(f"   　 '{secret_message[1]}' = {format(ord(secret_message[1]), '08b')}")

    embed_lsb(gray_path, secret_message, output_path)
    print(f"\n   ✅ 埋め込み完了: {output_path}")

    # Step 3: 変化を確認
    print("\n\n【Step 3】ピクセルの変化を確認")
    print("-" * 50)

    img_original = Image.open(gray_path)
    img_modified = Image.open(output_path)

    print("\n   最初の3ピクセルの比較:")
    print("   ┌──────────────────────────────────────────────────────────┐")
    print("   │  ピクセル  │     元の値      │    埋め込み後    │ 変化  │")
    print("   ├──────────────────────────────────────────────────────────┤")

    for i in range(3):
        orig = img_original.getpixel((i, 0))
        modi = img_modified.getpixel((i, 0))

        for c, name in enumerate(['R', 'G', 'B']):
            orig_val = orig[c]
            modi_val = modi[c]
            changed = "→" if orig_val != modi_val else " "

            print(f"   │  [{i}].{name}     │  {orig_val:3d} ({format(orig_val, '08b')}) │  {modi_val:3d} ({format(modi_val, '08b')}) │  {changed}   │")

    print("   └──────────────────────────────────────────────────────────┘")

    # 視覚的な違い
    print("\n   👁️ 視覚的な違い:")
    print(f"   　 元画像:     RGB(128, 128, 128) = グレー")
    print(f"   　 埋め込み後: RGB(129, 128, 128) = ほぼ同じグレー（人間には区別不可能）")

    # Step 4: 抽出
    print("\n\n【Step 4】メッセージを抽出")
    print("-" * 50)

    extracted = extract_lsb(output_path)
    print(f"   抽出結果: \"{extracted}\"")

    if extracted == secret_message:
        print("   ✅ 完全一致！埋め込み・抽出が正常に動作しています")
    else:
        print("   ⚠️ 不一致があります")

    print("\n\n" + "=" * 60)
    print("実験完了！生成されたファイル:")
    print(f"  - {gray_path} (元のグレー画像)")
    print(f"  - {output_path} (秘密メッセージ入り)")
    print("=" * 60 + "\n")


def main():
    # デフォルトはサンプル画像
    script_dir = Path(__file__).parent
    default_image = script_dir / "aicuty_000011.png"

    # コマンドライン引数の処理
    if len(sys.argv) >= 2 and sys.argv[1] == "--create-gray":
        # グレー画像実験モード
        visualize_lsb_concept()
        run_gray_experiment()
        return

    if len(sys.argv) >= 4 and sys.argv[1] == "--embed":
        # 埋め込みモード
        visualize_lsb_concept()
        message = sys.argv[2]
        output = sys.argv[3]
        source = sys.argv[4] if len(sys.argv) > 4 else str(default_image)

        print(f"📝 埋め込むメッセージ: {message}")
        print(f"📷 元画像: {source}")
        print(f"💾 出力先: {output}")

        if embed_lsb(source, message, output):
            print(f"\n✅ 埋め込み完了！")
            print(f"   確認: python lsb_demo.py {output}")
        return

    # コンセプト説明
    visualize_lsb_concept()

    # 抽出モード
    image_path = sys.argv[1] if len(sys.argv) > 1 else str(default_image)

    if not Path(image_path).exists():
        print(f"❌ ファイルが見つかりません: {image_path}")
        return

    print(f"🖼️  解析対象: {image_path}\n")
    print("=" * 60)

    # 最初のピクセルを可視化
    show_first_pixels(image_path)

    # メッセージ抽出
    print("\n\n🔍 隠しメッセージを抽出中...")
    print("=" * 60)

    message = extract_lsb(image_path)

    if message:
        print(f"\n✅ 発見されたメッセージ:\n")
        print(f"   ┌{'─' * (len(message) + 4)}┐")
        print(f"   │  {message}  │")
        print(f"   └{'─' * (len(message) + 4)}┘")
    else:
        print("\n❌ メッセージが見つかりませんでした")

    print("\n")


if __name__ == "__main__":
    main()
