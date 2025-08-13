#!/bin/sh
set -e

# --- 基于脚本自身定位 ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MC_DIR="$SCRIPT_DIR/../mcIVASmaker"

SRC_JSON="$MC_DIR/assets/blocks/img_generator_code/out_all_colours.json"
TMP_JSON="$SCRIPT_DIR/out_all_colours.json"
BACKUP_JSON="$SCRIPT_DIR/out_all_colours_.json"

INPUT="$1"
A2="$2"
A3="$3"
A4="$4"

if [ -z "$INPUT" ]; then
  echo "用法: $0 <图片或视频路径> [schem|mcs] [scale] [输出路径]"
  echo "      三个可选项顺序不限；例如："
  echo "      1) 1.sh <图>                  # 默认 any-image, scale=4.0"
  echo "      2) 1.sh <图> 8                # scale=8"
  echo "      3) 1.sh <图> mcs              # any-mcs, 默认scale=4.0"
  echo "      4) 1.sh <图> 8 mcs            # any-mcs, scale=8"
  echo "      5) 1.sh <图> mcs /sdcard/out/ # 输出到目录，自动命名 .mcstructure"
  exit 2
fi

# --- 判断是否视频 ---
ext_lc=$(printf '%s' "${INPUT##*.}" | tr 'A-Z' 'a-z')
case "$ext_lc" in
  mp4|mov|mkv|avi|webm|m4v) is_video=1 ;;
  *) is_video=0 ;;
esac

# --- 工具函数 ---
is_dir_hint() {
  [ -d "$1" ] && return 0
  case "$1" in
    */|*\\) return 0 ;;
  esac
  return 1
}

ext_for_kind() {
  case "$1" in
    any-image|lamps-image) printf ".png" ;;
    any-schem|lamps-schem) printf ".schem" ;;
    any-mcs)               printf ".mcstructure" ;;
    *)                     printf ".png" ;;
  esac
}

timestamp() {
  date +"%y_%m_%d-%H_%M_%S"
}

base_noext() {
  b=$(basename -- "$1")
  printf "%s" "${b%.*}"
}

ensure_file_ext() {
  # $1: path, $2: ext (with dot)
  bn=$(basename -- "$1")
  case "$bn" in
    *.*) printf "%s" "$1" ;;           # 已经有扩展名
    *)   printf "%s%s" "$1" "$2" ;;     # 没有扩展名就补上
  esac
}

# --- 解析三个可选项（顺序不限） ---
type_tok=""
scale=""
output=""

for tok in $A2 $A3 $A4; do
  [ -z "$tok" ] && continue
  if [ -z "$type_tok" ] && { [ "$tok" = "schem" ] || [ "$tok" = "mcs" ]; }; then
    type_tok="$tok"
    continue
  fi
  if [ -z "$scale" ] && printf '%s' "$tok" | grep -Eq '^[0-9]+([.][0-9]+)?$'; then
    scale="$tok"
    continue
  fi
  if [ -z "$output" ]; then
    output="$tok"
    continue
  fi
done

[ -z "$scale" ] && scale="4.0"

# kind 由是否指定类型决定
if [ -n "$type_tok" ]; then
  kind="any-$type_tok"
else
  kind="any-image"
fi

# --- 组装输出路径规则 ---
if [ "$is_video" -eq 0 ]; then
  # 单张图片：确保 -o 是“带扩展名的文件路径”
  img_ext="$(ext_for_kind "$kind")"
  if [ -z "$output" ]; then
    d="$(dirname "$INPUT")"
    output="$d/$(base_noext "$INPUT")_$(timestamp)$img_ext"
  elif is_dir_hint "$output"; then
    d="${output%/}"
    output="$d/$(base_noext "$INPUT")_$(timestamp)$img_ext"
  else
    # 给了具体文件名：如果没扩展名就补正确的
    output="$(ensure_file_ext "$output" "$img_ext")"
  fi
else
  # 视频：不给 -o 就让 Python 端自动命名 .mp4；
  # 若给了目录，Python 端也能处理；若给了具体文件名建议带 .mp4（本脚本不强改）。
  :
fi

# --- JSON 替换与自动还原 ---
restore() { cp "$BACKUP_JSON" "$SRC_JSON" 2>/dev/null || true; }
trap restore EXIT INT TERM
cp "$TMP_JSON" "$SRC_JSON"

# --- 执行命令 ---
cd "$MC_DIR"
if [ "$is_video" -eq 1 ]; then subcmd="video"; else subcmd="image"; fi

cmd="python -m src.cli $subcmd $kind -i \"$INPUT\" --scale \"$scale\" --side top"
if [ "$is_video" -eq 1 ]; then
  [ -n "$output" ] && cmd="$cmd -o \"$output\""
else
  cmd="$cmd -o \"$output\""
fi

echo "运行命令: $cmd"
eval "$cmd"
