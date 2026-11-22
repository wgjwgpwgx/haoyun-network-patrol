"""PDF 报告生成器

转换策略（按优先级）：
  1. win32com 直接调用 Word（Windows + Microsoft Word）
  2. LibreOffice 命令行（Linux / Windows）
  3. 失败时抛出异常

文件命名：巡检报告_{设备名称}_{日期时间}.pdf

中文处理：
  Word 模板使用微软雅黑，转换后 PDF 自动嵌入字体。
  Linux 需要安装中文字体：apt install fonts-wqy-microhei

页眉页脚：
  通过 Word 模板的页眉页脚功能实现。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from patrol.models import PatrolReport
from patrol.reporter.base import BaseReporter
from patrol.reporter.word import WordReporter, generate_word_filename

logger = logging.getLogger(__name__)


class PDFReporter(BaseReporter):
    """生成 PDF 格式的巡检报告（通过 Word 转换）"""

    def __init__(self) -> None:
        self._word_reporter = WordReporter()

    def generate(self, report: PatrolReport, output_path: Path) -> Path:
        """生成 PDF 报告。

        流程：先生成 Word → 转换为 PDF → 清理临时 Word 文件。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 先生成 Word
        word_filename = generate_word_filename(report).replace(".docx", "_tmp.docx")
        word_path = output_path.parent / word_filename
        self._word_reporter.generate(report, word_path)

        # 转换为 PDF
        try:
            self._convert_to_pdf(word_path, output_path)
        finally:
            # 清理临时 Word 文件
            if word_path.exists():
                try:
                    word_path.unlink()
                except Exception:
                    pass

        logger.info("PDF 报告已生成: %s", output_path)
        return output_path

    def _convert_to_pdf(self, word_path: Path, pdf_path: Path) -> None:
        """将 Word 文件转换为 PDF。

        优先使用 win32com（Windows + Word），
        回退到 LibreOffice 命令行。
        """
        # 方案 1：win32com（Windows）
        if self._try_win32com(word_path, pdf_path):
            return

        # 方案 2：LibreOffice（跨平台）
        if self._try_libreoffice(word_path, pdf_path):
            return

        raise RuntimeError(
            "PDF 转换失败：需要安装 Microsoft Word 或 LibreOffice。\n"
            "Windows: 安装 Microsoft Word\n"
            "Linux: sudo apt install libreoffice-writer fonts-wqy-microhei"
        )

    def _try_win32com(self, word_path: Path, pdf_path: Path) -> bool:
        """使用 win32com 直接调用 Word 转换 PDF。"""
        try:
            import win32com.client
        except ImportError:
            logger.debug("win32com 不可用（非 Windows 或未安装 pywin32）")
            return False

        word = None
        doc = None
        try:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            abs_word = str(word_path.resolve())
            abs_pdf = str(pdf_path.resolve())
            doc = word.Documents.Open(abs_word)
            doc.SaveAs2(abs_pdf, FileFormat=17)  # 17 = wdFormatPDF
            doc.Close()
            if pdf_path.exists():
                logger.info("PDF 转换成功（win32com）: %s", pdf_path)
                return True
        except Exception as e:
            # PDF 可能已成功生成，只是 Quit() 失败
            if pdf_path.exists():
                logger.info("PDF 转换成功（win32com，Quit 异常已忽略）: %s", pdf_path)
                return True
            logger.debug("win32com 转换失败: %s", e)
        finally:
            try:
                if doc:
                    doc.Close()
            except Exception:
                pass
            try:
                if word:
                    word.Quit()
            except Exception:
                pass

        return False

    def _try_libreoffice(self, word_path: Path, pdf_path: Path) -> bool:
        """使用 LibreOffice 命令行转换。"""
        libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
        if not libreoffice:
            logger.debug("LibreOffice 未找到")
            return False

        try:
            output_dir = pdf_path.parent
            result = subprocess.run(
                [
                    libreoffice,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(output_dir),
                    str(word_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            expected_pdf = output_dir / (word_path.stem + ".pdf")
            if expected_pdf.exists() and expected_pdf != pdf_path:
                expected_pdf.rename(pdf_path)

            if pdf_path.exists():
                logger.info("PDF 转换成功（LibreOffice）: %s", pdf_path)
                return True
            else:
                logger.warning("LibreOffice 转换失败: %s", result.stderr)
        except Exception as e:
            logger.debug("LibreOffice 转换失败: %s", e)

        return False


def generate_pdf_filename(report: PatrolReport) -> str:
    """生成 PDF 报告文件名：巡检报告_{设备名称}_{日期时间}.pdf"""
    from patrol.utils.filename import safe_component

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if report.devices:
        device_name = safe_component(report.devices[0].asset.name)
        return f"巡检报告_{device_name}_{ts}.pdf"
    return f"巡检报告_{ts}.pdf"


def check_pdf_capability() -> dict[str, bool]:
    """检查当前环境的 PDF 转换能力。"""
    result = {
        "win32com": False,
        "libreoffice": False,
    }

    try:
        import win32com.client
        result["win32com"] = True
    except (ImportError, Exception):
        pass

    lo = shutil.which("libreoffice") or shutil.which("soffice")
    result["libreoffice"] = lo is not None

    return result
