"""本地 XML 弹幕文件解析器。

负责将本地保存的 XML 弹幕文件解析为 Counter[DanmakuFingerprint]，
用于后续与线上弹幕进行比对。
"""
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from danmaku_inspector.types.models import DanmakuFingerprint

# 文件名匹配: P{num}_{desc}.xml 或 {num}.xml
_FILENAME_PATTERN = re.compile(r"^(?:P)?(\d+)")


def parse_xml(xml_path: Path) -> Counter[DanmakuFingerprint]:
    """解析单个 XML 文件，返回弹幕指纹 Counter。

    Args:
        xml_path: XML 文件路径。

    Returns:
        弹幕指纹 Counter，key 为 DanmakuFingerprint，value 为出现次数。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    counter: Counter[DanmakuFingerprint] = Counter()
    for elem in root.findall("d"):
        p_attr = elem.get("p", "")
        content = elem.text or ""

        # 解析 p 属性，至少需要 4 个字段
        parts = p_attr.split(",")
        if len(parts) < 4:
            continue

        try:
            progress_sec = float(parts[0])  # 时间轴位置（秒）
            mode = int(parts[1])            # 弹幕模式
            fontsize = int(parts[2])        # 字号
            color = int(parts[3])           # 颜色
        except (ValueError, IndexError):
            continue

        # 秒转毫秒: int(round(float(playtime) * 1000))
        progress_ms = int(round(progress_sec * 1000))

        fp = DanmakuFingerprint(
            content=content,
            progress_ms=progress_ms,
            mode=mode,
            fontsize=fontsize,
            color=color,
        )
        counter[fp] += 1

    return counter


def scan_xml_dir(xml_dir: Path) -> dict[int, Path]:
    """扫描目录，建立分P编号到文件路径的映射。

    支持格式: P01_第一集.xml / 01.xml

    Args:
        xml_dir: 包含 XML 文件的目录。

    Returns:
        分P编号到文件路径的映射。

    Raises:
        ValueError: 文件名不符合规范或分P编号重复。
    """
    mapping: dict[int, Path] = {}
    errors: list[str] = []

    for xml_file in xml_dir.glob("*.xml"):
        match = _FILENAME_PATTERN.match(xml_file.name)
        if not match:
            errors.append(f"文件名不符合规范: {xml_file.name}")
            continue

        part_num = int(match.group(1))
        if part_num in mapping:
            errors.append(f"分P编号重复: {part_num}")
            continue

        mapping[part_num] = xml_file

    if errors:
        raise ValueError("文件名解析错误:\n" + "\n".join(errors))

    return mapping


def parse_all_parts(xml_dir: Path) -> dict[int, Counter[DanmakuFingerprint]]:
    """解析目录下所有分P的 XML 文件。

    Args:
        xml_dir: 包含 XML 文件的目录。

    Returns:
        分P编号到弹幕指纹 Counter 的映射，按分P编号排序。
    """
    part_files = scan_xml_dir(xml_dir)

    result = {}
    for part_num in sorted(part_files.keys()):
        result[part_num] = parse_xml(part_files[part_num])
    return result
