import sys
import os
import argparse
from typing import Optional, Tuple, List
from datetime import datetime

from tqdm import tqdm

# 复用现有逻辑
from src.logic.image_logic.image_manager import manipulate_image
from src.logic.vid_logic.vid_manager import vid_manager

SUPPORTED_IMG_EXTS = {".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


# ========== 工具函数 ==========
def wrap_color(name: Optional[str]) -> list:
    return [name] if name else ["Linear Average"]

def wrap_compare(name: Optional[str]) -> list:
    return [name] if name else ["Absolute Difference"]

def parse_crop(crop: Optional[str]) -> Optional[list]:
    if not crop:
        return None
    parts = [p.strip() for p in crop.split(',')]
    if len(parts) != 4:
        raise ValueError('--crop 必须为 "x1,y1,x2,y2"；x2/y2 可用 max')
    return [parts[0] or "0", parts[1] or "0", parts[2] or "Max", parts[3] or "Max"]

def read_blocklist_file(path: Optional[str]) -> List[str]:
    """
    从文本文件读取方块名（黑名单/白名单），一行一个。
    忽略空行与注释行（以 # 或 // 开头）。
    """
    if not path:
        return []
    items: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#") or s.startswith("//"):
                continue
            items.append(s)
    return items

def merge_blocklists(list_from_args: Optional[List[str]], list_from_file: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    seen = set()
    for name in (list_from_args or []) + (list_from_file or []):
        if name not in seen:
            out.append(name)
            seen.add(name)
    return out

def list_images_in_dir(d: str) -> List[str]:
    files = []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.path.splitext(p)[1] in SUPPORTED_IMG_EXTS:
            files.append(p)
    return files

def make_default_output_dir() -> str:
    out_dir = "./mcIVASMAKER_output"
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

def timestamp() -> str:
    return datetime.now().strftime("%y_%m_%d-%H_%M_%S")

def _ext_for_kind(kind: str) -> str:
    """根据 kind 决定默认输出扩展名。"""
    if kind in ('any-image', 'lamps-image'):
        return '.png'
    if kind == 'any-mcs':
        return '.mcstructure'
    # 其余都当作 schem
    return '.schem'

# ========== 图片（单张/目录） ==========
def build_image_details(args) -> dict:
    # 合并黑名单：命令行列表 + 文件
    file_list = read_blocklist_file(args.blocklist_file)
    merged_blocklist = merge_blocklists(args.blocklist or [], file_list)

    return {
        'blocklist': merged_blocklist,
        'mode': args.mode,
        'dither': args.dither,
        'alternate': args.alternate,
        'color_set': wrap_color(args.color_set),
        'color_compare': wrap_compare(args.color_compare),
        'side': args.side.lower(),
        'brightness': args.brightness,
        'place_redstone_blocks': args.place_redstone_blocks
    }

def do_image(args):
    img_type_map = {
        'any-image': 'Image To Any Block Image',
        'any-schem': 'Image To Any Block Schematic',
        'lamps-image': 'Image To Redstone Lamps Image',
        'lamps-schem': 'Image To Redstone Lamps Schematic',
        'any-mcs': 'Image To Any Block MCStructure',   # 新增：MCStructure 输出
    }
    manipulation = img_type_map[args.kind]
    # 直接使用倍数缩放（float）
    scale = args.scale
    details = build_image_details(args)
    crop_val = parse_crop(args.crop)

    # 目录批量模式
    if os.path.isdir(args.input):
        in_dir = args.input
        files = list_images_in_dir(in_dir)
        if not files:
            print(f"[warn] 目录中没有可处理的图片：{in_dir}")
            return

        # 输出目录：若 -o 指向一个目录或以 / 结尾则用之；否则用默认输出目录
        if args.output and (os.path.isdir(args.output) or args.output.endswith(('/', '\\'))):
            out_dir = args.output.rstrip('/\\')
            os.makedirs(out_dir, exist_ok=True)
        else:
            out_dir = make_default_output_dir()

        # 外层进度条：文件维度
        with tqdm(total=len(files), desc="Files", unit="img") as files_bar:
            for in_path in files:
                base = os.path.splitext(os.path.basename(in_path))[0]
                ext = _ext_for_kind(args.kind)  # 使用统一扩展名判断
                out_path = os.path.join(out_dir, f"{base}_{timestamp()}{ext}")
                _run_single_image(in_path, out_path, manipulation, scale, details, crop_val)
                files_bar.update(1)

        print(f"[ok] 全部完成，输出目录：{out_dir}")
        return

    # 单文件模式
    output = args.output
    if not output:
        out_dir = make_default_output_dir()
        ext = _ext_for_kind(args.kind)  # 使用统一扩展名判断
        output = os.path.join(out_dir, f"output{timestamp()}{ext}")

    _run_single_image(args.input, output, manipulation, scale, details, crop_val)
    print(f"[ok] saved to: {output}")

def _run_single_image(in_path: str, out_path: str, manipulation: str, scale: float, details: dict, crop_val: Optional[list]):
    # 内层进度条：列（tile/x）维度
    total_cols = None
    last_x = -1
    pbar = None

    for prog in manipulate_image(
        filepath=in_path,
        output=out_path,
        manipulation=manipulation,
        crop=crop_val,
        scale=scale,  # 直接传倍数（float）
        details=details
    ):
        # 生成器约定：首次 yield int 为总列数/宽度；之后连续 yield 当前列索引 x
        if isinstance(prog, int):
            if total_cols is None:
                total_cols = prog
                pbar = tqdm(total=total_cols, desc=f"Processing {os.path.basename(in_path)}", unit="col")
            else:
                # prog 是当前 x（0..width-1），转换为增量
                delta = (prog - last_x) if last_x >= 0 else 1
                if delta < 0:
                    delta = 0
                pbar.update(delta)
                last_x = prog
        elif prog == "Done Processing!":
            if pbar:
                # 补齐进度条
                remaining = pbar.total - pbar.n
                if remaining > 0:
                    pbar.update(remaining)
                pbar.close()
            print(f"[save] writing file: {os.path.basename(out_path)}")
        elif prog == "Done!":
            break

# ========== 视频（进度条） ==========
def do_video(args):
    vid_type_map = {
        'any-image': 'Video To Any Block Image',
        'any-schem': 'Video To Any Block Schematic',
        'lamps-image': 'Video To Redstone Lamps Image',
        'lamps-schem': 'Video To Redstone Lamps Schematic',
    }
    manipulation = vid_type_map[args.kind]
    scale = args.scale  # 直接倍数（float）

    # 合并黑名单（视频同样适用 Any Block 路径）
    file_list = read_blocklist_file(args.blocklist_file)
    merged_blocklist = merge_blocklists(args.blocklist or [], file_list)

    details = {
        'blocklist': merged_blocklist,
        'mode': args.mode,
        'quality': args.quality,
        'frame_rate': args.fps,
        'dither': args.dither,
        'alternate': args.alternate,
        'color_set': wrap_color(args.color_set),
        'color_compare': wrap_compare(args.color_compare),
        'side': args.side.lower(),
        'brightness': args.brightness,
        'process_count': max(1, min(16, args.processes))
    }

    # —— 决定输出路径：目录→自动命名；文件→强制 .mp4 ——
    out_arg = args.output
    in_dir = os.path.dirname(args.input) or "."
    def _auto_name_mp4(dst_dir: str) -> str:
        os.makedirs(dst_dir, exist_ok=True)
        return os.path.join(dst_dir, f"output{timestamp()}.mp4")

    if not out_arg:
        output = _auto_name_mp4(in_dir)            # 未指定 → 放到原视频目录
    else:
        out_arg = out_arg.rstrip()
        root, ext = os.path.splitext(out_arg)
        if os.path.isdir(out_arg) or out_arg.endswith(('/', '\\')) or ext == "":
            output = _auto_name_mp4(out_arg)       # 目录或无扩展名 → 目录自动命名
        else:
            if ext.lower() != ".mp4":              # 指定了文件名但不是 .mp4 → 改成 .mp4
                print(f"[warn] 输出扩展名 {ext} 非 .mp4，已改为 .mp4")
                output = root + ".mp4"
            else:
                output = out_arg

    # 构造 tqdm 进度条（抽帧 & 处理）
    bars = {
        "extract": None,   # 抽帧（近似用帧总数 * 百分比）
        "process": None,   # 处理（逐帧计数）
    }
    state = {
        "frame_total": None,
        "extract_last": 0.0,
        "process_done": 0
    }

    def cli_progress(ev):
        name, payload = ev
        if name == '-Image_Count-':
            state["frame_total"] = int(payload)
            bars["extract"] = tqdm(total=state["frame_total"], desc="Extract", unit="frame")
            bars["process"] = tqdm(total=state["frame_total"], desc="Process", unit="frame")
        elif name == '-Set_Images_Done-':
            pass
        elif name == '-Img_Conversion-':
            if state["frame_total"] and bars["extract"]:
                pct = float(payload)
                if pct <= 1:
                    target = pct * state["frame_total"]
                    delta = max(0, target - state["extract_last"])
                    bars["extract"].update(delta)
                    state["extract_last"] = target
                else:
                    remaining = bars["extract"].total - bars["extract"].n
                    if remaining > 0:
                        bars["extract"].update(remaining)
        elif name == '-Image_Done-':
            if bars["process"]:
                bars["process"].update(1)
                state["process_done"] += 1
        # 单帧内 0~100 的细颗粒进度不额外画条，避免刷屏

    vid_manager(
        window=None,
        filepath=args.input,
        output=output,
        manipulation=manipulation,
        scale=scale,        # 直接倍数传入；你已在 image_manager 中兼容 float
        details=details,
        progress_cb=cli_progress
    )

    # 收尾
    for key in ("extract", "process"):
        if bars[key]:
            remain = bars[key].total - bars[key].n
            if remain > 0:
                bars[key].update(remain)
            bars[key].close()

    print(f"[ok] saved to: {output}")

# ========== 参数解析 ==========
def build_parser():
    p = argparse.ArgumentParser(prog='mcIVASMaker', description='Minecraft Image/Video AnyBlock/Lamps Converter (CLI)')
    sub = p.add_subparsers(dest='cmd', required=True)

    def common_block_args(sp):
        sp.add_argument('--side', default='top', choices=['top','bottom','north','south','east','west'], help='采样方位（方块贴图朝向）')
        sp.add_argument('--mode', default='All', choices=['All','Whitelist','Blacklist'], help='筛选模式')
        sp.add_argument('--blocklist', nargs='*', help='白/黑名单的方块名列表（与资源键一致）')
        sp.add_argument('--blocklist-file', help='从文本文件读取黑名单/白名单，每行一个，支持注释行(# 或 //)')
        sp.add_argument('--color-set', help='颜色聚合方式，如 "Linear Average"/"RMS Average"/"HSL"/"HSV"/"Lab"/"Dominant"（依据资源数据命名）')
        sp.add_argument('--color-compare', help='颜色差异算法，如 "Absolute Difference"/"Euclidean Difference"/"Weighted Euclidean"/"Redmean Difference"/"CIE76 DelE"')

    # image
    pi = sub.add_parser('image', help='处理单张图片或目录（目录将批量处理）')
    pi.add_argument('kind', choices=['any-image','any-schem','lamps-image','lamps-schem','any-mcs'], help='输出类型')
    pi.add_argument('-i','--input', required=True, help='输入图片路径或目录')
    pi.add_argument('-o','--output', help='输出文件或目录（目录模式下建议指定为目录；默认 ./mcIVASMAKER_output）')
    pi.add_argument('--scale', type=float, default=1.0, help='缩放倍数（1.0=原图分辨率，0.5=一半，2.0=两倍）')
    pi.add_argument('--crop', help='裁剪区域：x1,y1,x2,y2；x2/y2 可用 max')
    pi.add_argument('--brightness', type=int, default=127, help='Lamps 模式阈值（0~255）')
    pi.add_argument('--dither', action='store_true', help='Lamps 使用抖动')
    pi.add_argument('--alternate', action='store_true', help='Lamps 使用 alternate 模式')
    pi.add_argument('--place-redstone-blocks', action='store_true', help='Lamps schematic 在灯下放置红石块')
    common_block_args(pi)
    pi.set_defaults(func=do_image)

    # video
    pv = sub.add_parser('video', help='处理视频')
    pv.add_argument('kind', choices=['any-image','any-schem','lamps-image','lamps-schem'], help='输出类型')
    pv.add_argument('-i','--input', required=True, help='输入视频路径')
    pv.add_argument('-o','--output', help='输出文件路径（默认放到 ./mcIVASMAKER_output）')
    pv.add_argument('--scale', type=float, default=1.0, help='缩放倍数（1.0=原尺寸，0.5=一半，2.0=两倍）')
    pv.add_argument('--fps', type=int, default=12, help='抽帧帧率（与 GUI 滑条一致）')
    pv.add_argument('--quality', action='store_true', help='使用 PNG 中间帧（更高质量更慢）；不指定则使用 JPG')
    pv.add_argument('--brightness', type=int, default=127, help='Lamps 模式阈值')
    pv.add_argument('--dither', action='store_true', help='Lamps 使用抖动')
    pv.add_argument('--alternate', action='store_true', help='Lamps 使用 alternate 模式')
    pv.add_argument('--processes', type=int, default=2, help='并行处理进程数（1~16）')
    common_block_args(pv)
    pv.set_defaults(func=do_video)

    return p

def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    # === 简化模式：python -m src.cli <输入> <倍数> [输出(可为目录或文件)] ===
    if len(argv) >= 2 and os.path.exists(argv[0]):
        in_path = argv[0]
        try:
            scale_val = float(argv[1])
        except ValueError:
            scale_val = None

        if scale_val is not None:
            out_arg = argv[2] if len(argv) >= 3 else None
            if len(argv) >= 4:
                print("[warn] 额外参数已忽略：", " ".join(argv[3:]))

            ext = os.path.splitext(in_path)[1].lower()
            is_video = ext in SUPPORTED_VIDEO_EXTS
            in_dir = os.path.dirname(in_path) or "."

            # —— 统一构造输出路径（目录→自动命名；文件→强制扩展名） ——
            def _auto_name(dst_dir: str, suffix: str) -> str:
                os.makedirs(dst_dir, exist_ok=True)
                return os.path.join(dst_dir, f"output{timestamp()}{suffix}")

            if not out_arg:
                output_path = _auto_name(in_dir, ".mp4" if is_video else ".png")
            else:
                out_arg = out_arg.rstrip()
                root, ext_o = os.path.splitext(out_arg)
                if os.path.isdir(out_arg) or out_arg.endswith(('/', '\\')) or ext_o == "":
                    output_path = _auto_name(out_arg, ".mp4" if is_video else ".png")
                else:
                    # 指定了具体文件名 → 强制正确扩展名
                    need = ".mp4" if is_video else ".png"
                    if ext_o.lower() != need:
                        print(f"[warn] 输出扩展名 {ext_o} 非 {need}，已改为 {need}")
                        output_path = root + need
                    else:
                        output_path = out_arg

            # 保护：避免覆盖输入
            if os.path.abspath(in_path) == os.path.abspath(output_path):
                fallback = _auto_name("./mcIVASMAKER_output", ".mp4" if is_video else ".png")
                print(f"[warn] 输出与输入相同，已改为：{fallback}")
                output_path = fallback

            if is_video:
                # —— 构造简单视频参数并调用 do_video ——
                class SimpleArgsV:
                    kind = 'any-image'     # 视频默认：任意方块视频
                    input = in_path
                    output = output_path
                    scale = scale_val
                    fps = 12
                    quality = False
                    brightness = 127
                    dither = False
                    alternate = False
                    processes = 2
                    side = 'top'
                    mode = 'All'
                    blocklist = []
                    blocklist_file = None
                    color_set = None
                    color_compare = None
                do_video(SimpleArgsV())
            else:
                # —— 构造简单图片参数并调用 do_image ——
                class SimpleArgsI:
                    kind = 'any-image'     # 图片默认：任意方块图片
                    input = in_path
                    output = output_path
                    scale = scale_val
                    crop = None
                    brightness = 127
                    dither = False
                    alternate = False
                    place_redstone_blocks = False
                    side = 'top'
                    mode = 'All'
                    blocklist = []
                    blocklist_file = None
                    color_set = None
                    color_compare = None
                do_image(SimpleArgsI())
            return

    # === 正常模式 ===
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)

if __name__ == '__main__':
    main()
