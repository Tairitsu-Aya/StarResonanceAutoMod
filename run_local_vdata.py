"""
run_local_vdata.py
------------------
用途：不用抓包，直接从本地文件读取 VData，走与 star_railway_monitor 相同的解析与优化路径，
输出 TopN 模组组合（调用同一套 ModuleParser + ModuleOptimizer 逻辑与展示方式）。

示例：
  # 读取本地 .pb / .json / base64 文件，筛选“攻击”类型，要求至少命中2个指定词条，输出前30个，
  # 并强制 暴击专注 ≥ 8、智力加持 ≥ 12
  python run_local_vdata.py --vdata ./my_vdata.pb -c 攻击 -attr 智力加持 暴击专注 -mc 2 --topn 30 \
      -mas 暴击专注 8 -mas 智力加持 12
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import List, Optional, Dict

from google.protobuf.json_format import Parse as JsonParse
from google.protobuf.message import DecodeError

# 项目内模块
from BlueProtobuf_pb2 import CharSerialize, SyncContainerData  # type: ignore
from logging_config import setup_logging, get_logger
from module_parser import ModuleParser
from module_optimizer import ModuleOptimizer
from module_types import ModuleCategory

logger = get_logger(__name__)


# ---------- 读取本地 VData（JSON / base64 / protobuf） ----------
def load_vdata_from_file(path: str | Path) -> CharSerialize:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")

    data = p.read_bytes()

    # 1) 尝试解析为 SyncContainerData（二进制）
    try:
        scd = SyncContainerData()
        scd.ParseFromString(data)
        if scd.HasField("VData"):
            return scd.VData
    except DecodeError:
        pass

    # 2) 尝试解析为 CharSerialize（二进制）
    try:
        cs = CharSerialize()
        cs.ParseFromString(data)
        return cs
    except DecodeError:
        pass

    # 3) 文本：尝试 base64 / JSON
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ValueError("无法解析：既不是 protobuf 二进制，也不是 UTF-8 文本(JSON/base64)") from None

    # 3a) 仅 base64（假设为 CharSerialize 原始字节）
    try:
        raw = base64.b64decode(text, validate=True)
        cs = CharSerialize()
        cs.ParseFromString(raw)
        return cs
    except Exception:
        pass

    # 3b) JSON：既支持顶层 CharSerialize，也支持顶层 SyncContainerData(VData内嵌)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"不是有效的 JSON / base64 / protobuf：{e}") from None

    # 顶层 CharSerialize JSON
    try:
        cs = CharSerialize()
        JsonParse(json.dumps(obj), cs)
        return cs
    except Exception:
        pass

    # 顶层 SyncContainerData JSON
    try:
        scd = SyncContainerData()
        JsonParse(json.dumps(obj), scd)
        if scd.HasField("VData"):
            return scd.VData
    except Exception:
        pass

    raise ValueError("无法识别 CharSerialize/SyncContainerData（支持：二进制pb / JSON / base64）。")


# ---------- 主流程：解析 -> 优化 -> 输出 ----------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="从本地 VData 读取并输出 TopN 模组组合（替代抓包）")
    ap.add_argument("--vdata", required=True, help="VData 文件路径（.pb/.bin 或 JSON/base64）")
    ap.add_argument("--debug", "-d", action="store_true", help="启用调试日志")
    ap.add_argument("--category", "-c", type=str, choices=["攻击", "守护", "辅助", "全部"], default="全部", help="目标模组类型")
    ap.add_argument("--attributes", "-attr", nargs="+", help="包含的属性词条（可多选）")
    ap.add_argument("--exclude-attributes", "-exattr", nargs="+", help="排除的属性词条（可多选）")
    ap.add_argument("--match-count", "-mc", type=int, default=1, help="要求至少包含的指定词条数量")
    ap.add_argument("--enumeration-mode", "-enum", action="store_true", help="启用枚举模式（不走局部搜索）")
    ap.add_argument("--topn", type=int, default=40, help="输出前 N 个最优解（默认 40）")
    # ✅ 支持 -mas：强制某属性在4件套总和 ≥ VALUE（可多次）
    ap.add_argument(
        "--min-attr-sum", "-mas",
        nargs=2, action="append", metavar=("ATTR", "VALUE"),
        help="强制某属性在4件套总和≥VALUE。可多次使用，如：-mas 暴击专注 8 -mas 智力加持 12"
    )
    args = ap.parse_args(argv)

    # 日志初始化（与主程序一致）
    setup_logging(debug_mode=args.debug)

    # 解析 -mas 为 dict[str,int]
    min_attr_sum: Dict[str, int] = {}
    if args.min_attr_sum:
        for name, val in args.min_attr_sum:
            try:
                min_attr_sum[name] = int(val)
            except Exception:
                logger.warning(f"无效的 -mas 阈值：{name} {val}（应为整数）")
    if min_attr_sum:
        logger.info("硬性约束（总和 ≥）： " + ", ".join(f"{k}≥{v}" for k, v in min_attr_sum.items()))

    logger.info("=== 本地 VData 读取模式（不抓包）===")
    logger.info(f"VData: {args.vdata}")
    if args.attributes:
        logger.info(f"包含词条: {' '.join(args.attributes)}；至少命中: {args.match_count}")
    if args.exclude_attributes:
        logger.info(f"排除词条: {' '.join(args.exclude_attributes)}")
    logger.info(f"类型: {args.category}；TopN: {args.topn}；枚举: {args.enumeration_mode}")

    # 1) 读取 VData
    vdata = load_vdata_from_file(args.vdata)

    # 2) 解析模组（使用与 star_railway_monitor 同一套解析器）
    parser = ModuleParser()
    modules = parser.parse_module_info(
        v_data=vdata,
        category=args.category,
        attributes=args.attributes,
        exclude_attributes=args.exclude_attributes,
        match_count=args.match_count,
        enumeration_mode=args.enumeration_mode,
        min_attr_sum=min_attr_sum 
    )

    # 3) 调用同一 Optimizer 输出 TopN（完全等价于 star_railway_monitor 的展示）
    category_map = {
        "攻击": ModuleCategory.ATTACK,
        "守护": ModuleCategory.GUARDIAN,
        "辅助": ModuleCategory.SUPPORT,
        "全部": ModuleCategory.ALL,
    }
    target_category = category_map.get(args.category, ModuleCategory.ALL)

    optimizer = ModuleOptimizer(
        target_attributes=args.attributes,
        exclude_attributes=args.exclude_attributes,
        min_attr_sum_requirements=min_attr_sum,  # ✅ 传入硬性约束
    )
    optimizer.optimize_and_display(
        modules=modules,
        category=target_category,
        top_n=args.topn,
        enumeration_mode=args.enumeration_mode
    )

    logger.info("=== 本地 VData 模式完成 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
