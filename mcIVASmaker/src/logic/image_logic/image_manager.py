import math
import os
import mcschematic
import logging
from typing import Union

from PIL import Image, ImageFile

# 现有逻辑复用的两个模块
from src.logic.image_logic import image_to_redstone_lamps, img_to_blocks as img_to_block_img
from src.logic.image_logic.block_parser import block_parser

logger = logging.getLogger(__name__)
ImageFile.LOAD_TRUNCATED_IMAGES = True

# 可选：Bedrock 结构导出（pip install mcstructure）
try:
    from mcstructure import Block, Structure
except Exception:
    Block = None
    Structure = None


def _normalize_scale_to_tile(step: Union[str, float, int]) -> int:
    """
    将用户传入的 scale 统一换算为算法需要的“瓦片步长”（用于 //scale 缩小），确保是 >=1 的整数。
    规则：
      - 如果是百分比字符串（如 "50%"、"12.5%"），先转成倍数（0.5、0.125），再计算。
      - 如果是数字（0.5、1、2.0），直接作为倍数。
      - 计算公式：tile = round(16 / 倍数)，并保证最小为 1。
        例：1.0 → 16；0.5 → 32；2.0 → 8
    """
    # 解析成倍数
    if isinstance(step, str):
        s = step.strip().lower()
        s = s.replace('×', 'x').replace('*', 'x').replace('x', '').strip()
        if s.endswith('%'):
            mult = float(s[:-1]) / 100.0
        else:
            mult = float(s)
    elif isinstance(step, (int, float)):
        mult = float(step)
    else:
        raise ValueError(f"Invalid scale type: {type(step)}")

    if mult <= 0:
        raise ValueError(f"scale must be > 0, got {mult}")

    tile = round(16.0 / mult)
    if tile < 1:
        tile = 1
    return tile


# Convert an image, to what the user specified
def manipulate_image(
        filepath: str, output: str, manipulation: str, crop: list | None, scale: Union[str, float, int], details: dict
):
    img = Image.open(filepath)
    # Validating the cropping
    if crop is not None:
        for i in range(4):
            if len(str(crop[i])) > 8:
                return False

            if crop[i] == "Max":
                crop[i] = img.width if i == 2 else img.height
            else:
                crop[i] = int(crop[i])

        if not all(1000000 > crop[i] >= 0 for i in range(4)):
            return False
        # Cropping the image
        img = img.crop((crop[0], crop[1], crop[2], crop[3]))

    # Scale to numeric tile step (integer >= 1)
    scale: int = _normalize_scale_to_tile(scale)

    # Getting the img to a multiple of 16 so textures match up
    if img.width % scale != 0:
        new_width = img.width + (scale - (img.width % scale))
    else:
        new_width = img.width

    if img.height % scale != 0:
        new_height = img.height + (scale - (img.height % scale))
    else:
        new_height = img.height

    img = img.crop((0, 0, new_width, new_height))
    img.thumbnail((img.width // scale, img.height // scale))
    yield img.width

    if manipulation == "Image To Any Block Image":
        img = img.convert("RGBA")
        for value in img_to_blocks(img, output, details):
            yield value
        return

    elif manipulation == "Image To Any Block Schematic":
        img = img.convert("RGBA")
        for value in img_to_blocks_schem(img, output, details):
            yield value
        return

    elif manipulation == "Image To Redstone Lamps Image":
        img = img.convert("RGB")
        for value in img_to_lamps(img, output, details):
            yield value
        return

    elif manipulation == "Image To Redstone Lamps Schematic":
        img = img.convert("RGB")
        for value in img_to_lamps_schem(img, output, details):
            yield value
        return

    # ==== 直接导出为 Bedrock 的 .mcstructure（基岩坐标原生写入） ====
    elif manipulation in ("image-mcs", "Image To Any Block MCStructure"):
        img = img.convert("RGBA")
        for value in img_to_blocks_mcs(img, output, details):
            yield value
        return

    # 兜底
    return


def img_to_lamps(img: Image.Image, output: str, details: dict):
    brightness = details['brightness']
    dither = details['dither']
    alternate = details['alternate']
    for value in image_to_redstone_lamps.img_to_redstone_lamps(img, brightness, dither, alternate):
        if isinstance(value, Image.Image):
            img = value
        else:
            yield value
    yield "Done Processing!"
    img.save(output)
    img.close()
    yield "Done!"
    return


def img_to_lamps_schem(img: Image.Image, output: str, details: dict):
    brightness = details['brightness']
    dither = details['dither']
    alternate = details['alternate']
    place_redstone_blocks = details['place_redstone_blocks']

    schem: mcschematic.MCSchematic = ...
    for value in image_to_redstone_lamps.img_to_redstone_lamps_schem(
            img, brightness, place_redstone_blocks, dither, alternate
    ):
        if isinstance(value, mcschematic.MCSchematic):
            schem: mcschematic.MCSchematic = value
        else:
            yield value
    yield "Done Processing!"
    head, tail = os.path.split(output)
    tail = tail.split(".")[0]
    schem.save(head, tail, mcschematic.Version.JE_1_20_1)
    yield "Done!"
    return


def img_to_blocks(img: Image.Image, output: str, details: dict):
    for value in img_to_block_img.img_to_blocks(
            img,
            {
                'side': details['side'],
                'blocked_list': details['blocklist'],
                'mode': details['mode'],
                'color_set': details['color_set'][0],
                'color_compare': details['color_compare'][0]
            }
    ):
        if isinstance(value, Image.Image):
            img = value
        else:
            yield value
    yield "Done Processing!"
    # --- JPEG 容错：退化为 RGB ---
    ext = os.path.splitext(output)[1].lower()
    if ext in ('.jpg', '.jpeg') and img.mode == 'RGBA':
        img = img.convert('RGB')
    img.save(output)
    img.close()
    yield "Done!"
    return


def img_to_blocks_schem(img: Image.Image, output: str, details: dict):
    schem: mcschematic.MCSchematic = ...
    for value in img_to_block_img.img_to_blocks_schem(
            img,
            {
                'side': details['side'],
                'blocked_list': details['blocklist'],
                'mode': details['mode'],
                'color_set': details['color_set'][0],
                'color_compare': details['color_compare'][0]
            }
    ):
        if isinstance(value, mcschematic.MCSchematic):
            schem: mcschematic.MCSchematic = value
        else:
            yield value
    yield "Done Processing!"
    head, tail = os.path.split(output)
    tail = tail.split(".")[0]
    schem.save(head, tail, mcschematic.Version.JE_1_20_1)
    yield "Done!"
    return


# ================= 新增：导出为 .mcstructure（基岩坐标原生） =================
def _parse_block_for_mcs(block_val) -> tuple[str, dict]:
    """
    兼容 block_parser(...) 的返回：
    - 若是字符串，支持 "minecraft:stone[axis=y,lit=true]" 简易解析
    - 若是字典，期望 {"name":"minecraft:stone", "states":{...}}
    返回: (full_name, states_dict)
    """
    def _norm(name: str) -> str:
        if not isinstance(name, str) or not name:
            return "minecraft:air"
        return name if name.startswith("minecraft:") else f"minecraft:{name}"

    # dict 形式
    if isinstance(block_val, dict):
        name = _norm(block_val.get("name", "minecraft:air"))
        states = block_val.get("states", {}) or {}
        if not isinstance(states, dict):
            states = {}
        return name, states

    # 字符串形式（可能带 [key=val,...]）
    if isinstance(block_val, str):
        s = block_val.strip()
        if "[" in s and s.endswith("]"):
            name, raw = s.split("[", 1)
            name = _norm(name.strip())
            raw = raw[:-1]  # 去掉尾部 ']'
            states = {}
            if raw:
                for pair in raw.split(","):
                    if "=" not in pair:
                        continue
                    k, v = pair.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    # 转成合适的类型
                    if v.lower() in ("true", "false"):
                        v = (v.lower() == "true")
                    else:
                        try:
                            if "." in v:
                                v = float(v)
                            else:
                                v = int(v)
                        except Exception:
                            pass
                    states[k] = v
            return name, states
        else:
            return _norm(s), {}

    # 兜底
    return "minecraft:air", {}


def img_to_blocks_mcs(image: Image.Image, output: str, details: dict):
    """
    将图片映射为方块并直接写出 .mcstructure
    映射规则：像素 (x, y) -> 结构坐标 (x, 1, y)
    即落在 x–z 平面，Y 固定为 1
    """
    if Block is None or Structure is None:
        yield "ERROR: mcstructure 库未安装，请先 `pip install mcstructure`"
        return

    # —— 参数与默认值 —— 
    blocked_list = details.get('blocked_list', details.get('blocklist', []))
    mode = details.get('mode', 'All')
    _raw_cs = details.get('color_set')
    color_set = _raw_cs[0] if isinstance(_raw_cs, (list, tuple)) and _raw_cs else (_raw_cs or 'Linear Average')
    _raw_cc = details.get('color_compare')
    color_compare = _raw_cc[0] if isinstance(_raw_cc, (list, tuple)) and _raw_cc else (_raw_cc or 'Absolute Difference')

    # —— 色板/色差函数 —— 
    all_blocks_data = getattr(img_to_block_img, 'blocks_data', None)
    if all_blocks_data is None:
        yield "ERROR: 未能加载 blocks_data（请确认 img_to_blocks 模块内已初始化 blocks_data）"
        return
    dist_fn = getattr(img_to_block_img, 'color_compare_to_function', None)
    if dist_fn is None:
        yield "ERROR: 未找到 color_compare_to_function"
        return
    distance_function = dist_fn(color_compare)

    # 过滤清单
    if mode == "Whitelist":
        new_blocks_list = [b for b in all_blocks_data if b[0] in blocked_list]
    elif mode == "Blacklist":
        new_blocks_list = [b for b in all_blocks_data if b[0] not in blocked_list]
    else:
        new_blocks_list = all_blocks_data
    if not new_blocks_list:
        yield "ERROR"
        return

    # 像素 -> 方块（挑选最接近颜色的方块）
    def pix_to_block(pix):
        best_idx, best_diff = -1, math.inf
        # 为兼容旧资源，按常见顺序找可用面
        side_order = ('top','north','south','east','west','bottom')
        for idx, block_val in enumerate(new_blocks_list):
            chosen_side = next((s for s in side_order if s in block_val[1]), None)
            if not chosen_side:
                continue
            col = block_val[1][chosen_side]['color'].get(color_set)
            if col is None:
                continue
            diff = distance_function(pix, col)
            if diff < best_diff:
                best_diff = diff
                best_idx = idx
        if best_idx < 0:
            return "minecraft:air"
        return block_parser(new_blocks_list[best_idx][0])

    W, H = image.width, image.height

    # —— 关键：结构尺寸设为 (W, 2, H)，这样 y=1 才合法 —— 
    y_level = 1
    struct = Structure((W, y_level + 1, H), Block("minecraft:air"))

    # 写入：像素 (x,y) -> (x, 1, y)
    for x in range(W):
        for y in range(H):
            pix = image.getpixel((x, y))
            if isinstance(pix, (tuple, list)) and len(pix) >= 4 and pix[3] <= 10:
                continue
            blk_val = pix_to_block(pix)
            name, states = _parse_block_for_mcs(blk_val)
            if name == "minecraft:air" and not states:
                continue
            pos = (x, y_level, y)  # x,z 由像素 x,y 组成，y 固定为 1
            try:
                struct.set_block(pos, Block(name, **states))
            except Exception:
                pass
        yield x

    # 写出 .mcstructure
    head, tail = os.path.split(output)
    base = os.path.splitext(tail)[0] or "out"
    out_path = os.path.join(head or ".", base + ".mcstructure")
    try:
        with open(out_path, "wb") as f:
            struct.dump(f)
        yield "Done Processing!"
        yield "Done!"
    except Exception as e:
        yield f"ERROR: 写出 .mcstructure 失败: {e}"
    return
