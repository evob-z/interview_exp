"""
excel_reader.py - 投递情况 Excel 读取模块
用 openpyxl 读取本地 Excel 文件，提取公司投递信息。
支持通过单元格背景颜色判断投递状态：
  红色 → 已结束（挂了）
  橙色 → 长期无消息
  黄色 → 流程中
  绿色 → 已拿offer
  无颜色 → 刚投递
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import openpyxl
    from openpyxl.styles.colors import Color
except ImportError:
    openpyxl = None
    logger.warning("openpyxl 未安装，Excel 读取功能将不可用。请执行: pip install openpyxl")


# 颜色→状态映射（基于 RGB 色相范围）
def _color_to_status(rgb_hex: str) -> str:
    """
    将 RGB 十六进制颜色映射为投递状态。
    rgb_hex 格式: "AARRGGBB" 或 "RRGGBB"
    """
    if not rgb_hex or rgb_hex in ("00000000", "FFFFFFFF", "00FFFFFF"):
        return "已投递"

    # 取 RGB 部分
    if len(rgb_hex) == 8:
        r, g, b = int(rgb_hex[2:4], 16), int(rgb_hex[4:6], 16), int(rgb_hex[6:8], 16)
    elif len(rgb_hex) == 6:
        r, g, b = int(rgb_hex[0:2], 16), int(rgb_hex[2:4], 16), int(rgb_hex[4:6], 16)
    else:
        return "已投递"

    # 白色/接近白色
    if r > 240 and g > 240 and b > 240:
        return "已投递"

    # 红色系：R高, G低, B低
    if r > 180 and g < 100 and b < 100:
        return "已结束"

    # 绿色系：G高, R低
    if g > 150 and r < 150 and b < 150:
        return "offer"

    # 橙色系：R高, G中, B低
    if r > 200 and 100 < g < 200 and b < 100:
        return "无消息"

    # 黄色系：R高, G高, B低
    if r > 200 and g > 200 and b < 100:
        return "流程中"

    # 浅红/粉红（Excel 常用的浅红表示失败）
    if r > 200 and g < 180 and b < 180 and r - g > 50:
        return "已结束"

    # 浅橙
    if r > 200 and g > 150 and b < 150 and r - b > 80 and g - b > 50:
        return "无消息"

    # 浅黄
    if r > 200 and g > 200 and b < 180 and r - b > 60:
        return "流程中"

    # 浅绿
    if g > 180 and r < 220 and b < 220 and g - r > 20:
        return "offer"

    return "已投递"


def _get_row_color(cells) -> str:
    """获取一行的背景颜色（取第一个有颜色的单元格）"""
    for cell in cells:
        if cell.fill and cell.fill.fgColor:
            color = cell.fill.fgColor
            # 忽略 theme 为 0 且 tint 为 0 的默认无色
            if color.type == "rgb" and color.rgb and color.rgb != "00000000":
                return color.rgb
            elif color.type == "indexed":
                # indexed 颜色的常见映射
                idx = color.indexed
                if idx is not None and idx != 64:  # 64 = 无颜色
                    # 常见 indexed 颜色
                    indexed_map = {
                        2: "FFFF0000",  # 红
                        3: "FF00FF00",  # 绿
                        5: "FFFFFF00",  # 黄
                        53: "FFFF8000",  # 橙
                    }
                    return indexed_map.get(idx, "")
            elif color.type == "theme":
                # theme 颜色较复杂，暂时跳过
                pass
    return ""


class ExcelReader:
    def __init__(self, excel_path: str):
        """初始化，指定 Excel 文件路径"""
        self.excel_path = Path(excel_path)
        self._headers: list[str] = []
        self._rows: list[dict] = []
        self._loaded = False

    def read(self) -> dict:
        """读取 Excel 内容
        返回: {
            headers: list[str],     # 表头
            rows: list[dict],       # 每行数据（以表头为 key）
            total: int,             # 总行数
            file_path: str          # 文件路径
        }
        """
        if self._loaded:
            return {
                "headers": self._headers,
                "rows": self._rows,
                "total": len(self._rows),
                "file_path": str(self.excel_path),
            }

        if openpyxl is None:
            logger.error("openpyxl 未安装，无法读取 Excel 文件")
            self._loaded = True
            return self._empty_result()

        if not self.excel_path.exists():
            logger.warning(f"Excel 文件不存在: {self.excel_path}")
            self._loaded = True
            return self._empty_result()

        try:
            # 不使用 read_only 模式，以便读取单元格样式（颜色）
            wb = openpyxl.load_workbook(self.excel_path, data_only=True)
            ws = wb.active

            rows_iter = ws.iter_rows()

            # 第一行为表头
            header_row = next(rows_iter, None)
            if header_row is None:
                logger.warning(f"Excel 文件为空: {self.excel_path}")
                wb.close()
                self._loaded = True
                return self._empty_result()

            self._headers = [str(h.value).strip() if h.value is not None else f"列{i+1}"
                             for i, h in enumerate(header_row)]

            # 读取数据行（含颜色→状态映射）
            self._rows = []
            for row_cells in rows_iter:
                # 跳过完全为空的行
                values = [cell.value for cell in row_cells]
                if all(v is None or str(v).strip() == "" for v in values):
                    continue

                row_dict = {}
                for i, cell in enumerate(row_cells):
                    if i < len(self._headers):
                        key = self._headers[i]
                        row_dict[key] = str(cell.value).strip() if cell.value is not None else ""

                # 从行颜色推断投递状态
                color_hex = _get_row_color(row_cells)
                row_dict["_status"] = _color_to_status(color_hex)
                row_dict["_color"] = color_hex

                self._rows.append(row_dict)

            wb.close()
            self._loaded = True

            # 统计各状态
            status_counts = {}
            for row in self._rows:
                s = row.get("_status", "已投递")
                status_counts[s] = status_counts.get(s, 0) + 1

            logger.info(
                f"Excel 读取完成：{len(self._rows)} 行数据，"
                f"状态分布: {status_counts}"
            )
            return {
                "headers": self._headers,
                "rows": self._rows,
                "total": len(self._rows),
                "status_counts": status_counts,
                "file_path": str(self.excel_path),
            }

        except Exception as e:
            logger.error(f"读取 Excel 失败 {self.excel_path}: {e}")
            self._loaded = True
            return self._empty_result()

    def search(self, company: str = None, status: str = None) -> list[dict]:
        """按公司名或状态筛选
        Args:
            company: 公司名关键词（模糊匹配）
            status: 状态关键词（模糊匹配）
        返回: 匹配的行列表
        """
        if not self._loaded:
            self.read()

        if not company and not status:
            return self._rows

        results = []
        for row in self._rows:
            match = True

            if company:
                company_lower = company.lower()
                # 在所有字段中查找公司名
                found_company = False
                for key, value in row.items():
                    if "公司" in key or "企业" in key or "name" in key.lower():
                        if company_lower in value.lower():
                            found_company = True
                            break
                # 如果没有明确的公司列，在所有值中查找
                if not found_company:
                    found_company = any(
                        company_lower in v.lower() for v in row.values()
                    )
                if not found_company:
                    match = False

            if status:
                status_lower = status.lower()
                found_status = False
                for key, value in row.items():
                    if "状态" in key or "进度" in key or "status" in key.lower():
                        if status_lower in value.lower():
                            found_status = True
                            break
                if not found_status:
                    found_status = any(
                        status_lower in v.lower() for v in row.values()
                    )
                if not found_status:
                    match = False

            if match:
                results.append(row)

        return results

    def get_stats(self) -> dict:
        """统计信息：各状态数量（基于颜色）、总投递数等"""
        if not self._loaded:
            self.read()

        if not self._rows:
            return {"total": 0, "status_counts": {}, "file_exists": self.excel_path.exists()}

        # 基于颜色的状态统计
        status_counts = {}
        for row in self._rows:
            status_val = row.get("_status", "已投递")
            status_counts[status_val] = status_counts.get(status_val, 0) + 1

        return {
            "total": len(self._rows),
            "status_counts": status_counts,
            "headers": self._headers,
            "file_path": str(self.excel_path),
            "file_exists": self.excel_path.exists(),
        }

    def _empty_result(self) -> dict:
        """返回空结果"""
        return {
            "headers": [],
            "rows": [],
            "total": 0,
            "file_path": str(self.excel_path),
        }
