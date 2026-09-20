# -*- coding: utf-8 -*-
"""生成 QuarkPlay 应用图标 icon.ico（云朵 + 播放按钮）"""
import os
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 背景圆角方块
d.rounded_rectangle([10, 10, S - 10, S - 10], radius=52, fill=(22, 30, 46, 255))

# 云朵（几个圆 + 底部矩形）
white = (238, 243, 252, 255)
d.ellipse([46, 116, 148, 198], fill=white)
d.ellipse([96, 78, 186, 168], fill=white)
d.rectangle([64, 146, 186, 198], fill=white)

# 播放按钮徽章
d.ellipse([142, 126, 236, 220], fill=(255, 145, 48, 255))
d.polygon([(178, 150), (178, 196), (216, 173)], fill=(22, 30, 46, 255))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                     (64, 64), (128, 128), (256, 256)])
print("icon saved:", out)
