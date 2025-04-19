import os
import re
import logging
import argparse  # 导入 argparse
from pathlib import Path
from typing import Optional, Generator

from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def sanitize_filename(title: str) -> str:
    """
    清理字符串，移除或替换用作文件名时的非法字符，并限制长度。

    Args:
        title: 原始标题字符串。

    Returns:
        清理后的、适合用作文件名的字符串。
    """
    # 移除非法字符 (Windows: <>:"/\|?*) 及其他特殊符号
    clean_title = re.sub(r'[\\/*?:"<>|《》（）()‘’“”]', '', title).strip()
    # 合并多个空格为一个空格
    clean_title = re.sub(r'\s+', ' ', clean_title)
    # 移除或替换换行符为空格
    clean_title = re.sub(r'[\n\r]+', ' ', clean_title)
    # 限制最大长度 (考虑路径总长度限制，文件名本身不宜过长)
    max_len = 150
    if len(clean_title) > max_len:
        clean_title = clean_title[:max_len].strip()
    # 移除末尾可能存在的点和空格
    clean_title = clean_title.rstrip('. ')
    # 如果清理后为空，返回一个默认名称或标记
    if not clean_title:
        return "untitled"
    return clean_title

def extract_pdf_title(pdf_path: Path) -> Optional[str]:
    """
    尝试从 PDF 文件中提取标题。
    首先尝试读取元数据中的 Title 字段，如果失败或为空，
    则尝试从第一页的文本内容中提取可能的标题行。

    Args:
        pdf_path: PDF 文件的 Path 对象。

    Returns:
        提取到的标题字符串，如果无法提取则返回 None。
    """
    try:
        with pdf_path.open('rb') as f:
            reader = PdfReader(f)

            # 1. 尝试从元数据获取标题
            meta = reader.metadata
            if meta and meta.title:
                # PyPDF2 >= 3.0.0 使用 meta.title
                # 对于旧版本，可能需要检查 meta.get('/Title')
                title = meta.title.strip()
                if title:
                    logging.debug(f"从元数据提取标题 '{title}' 来自 {pdf_path.name}")
                    return title

            # 2. 如果元数据没有标题，尝试从第一页提取
            if reader.pages:
                first_page = reader.pages[0]
                try:
                    text = first_page.extract_text()
                    if text:
                        lines = [line.strip() for line in text.split('\n') if line.strip()]
                        # 简单的启发式规则：找第一个足够长且看起来不像页码的行
                        for line in lines:
                            # 调整规则：长度适中，避免太短或太长，非纯数字
                            if 5 < len(line) < 100 and not line.isdigit():
                                logging.debug(f"从第一页文本提取标题 '{line}' 来自 {pdf_path.name}")
                                return line
                        # 如果没有合适的长行，退回到第一行（如果存在）
                        if lines:
                            logging.debug(f"使用第一行文本 '{lines[0]}' 作为标题 来自 {pdf_path.name}")
                            return lines[0]
                except Exception as text_extract_error:
                    # 单独捕获文本提取可能发生的错误
                    logging.warning(f"提取 {pdf_path.name} 第一页文本时出错: {text_extract_error}")

    except FileNotFoundError:
        logging.error(f"文件未找到: {pdf_path}")
    except PdfReadError as pdf_error:
        logging.error(f"读取 PDF 文件 {pdf_path.name} 时出错: {pdf_error}")
    except Exception as e:
        # 捕获其他可能的意外错误
        logging.error(f"处理文件 {pdf_path.name} 时发生未知错误: {e}", exc_info=True)

    logging.warning(f"无法为文件 {pdf_path.name} 提取标题")
    return None

def find_available_filename(target_dir: Path, base_name: str, extension: str) -> Path:
    """
    查找一个可用的文件名，如果目标文件名已存在，则在后面添加计数器。

    Args:
        target_dir: 目标目录的 Path 对象。
        base_name: 清理后的基础文件名 (不含扩展名)。
        extension: 文件扩展名 (例如 '.pdf')。

    Returns:
        一个在目标目录中当前不存在的完整文件路径 Path 对象。
    """
    counter = 1
    new_filename = f"{base_name}{extension}"
    new_path = target_dir / new_filename
    while new_path.exists():
        new_filename = f"{base_name}_{counter}{extension}"
        new_path = target_dir / new_filename
        counter += 1
    return new_path

def rename_pdfs_in_folder(folder_path_str: str):
    """
    遍历指定文件夹中的所有 PDF 文件，尝试根据提取的标题进行重命名。

    Args:
        folder_path_str: 包含 PDF 文件的文件夹路径字符串。
    """
    folder_path = Path(folder_path_str)
    if not folder_path.is_dir():
        logging.error(f"指定的路径不是一个有效的目录: {folder_path_str}")
        return

    pdf_files: Generator[Path, None, None] = folder_path.glob('*.pdf')
    rename_count = 0
    fail_count = 0

    for pdf_path in pdf_files:
        logging.info(f"正在处理文件: {pdf_path.name}")
        title = extract_pdf_title(pdf_path)

        if title:
            clean_title = sanitize_filename(title)
            if clean_title == "untitled" and pdf_path.stem == "untitled":
                 logging.warning(f"文件名已经是 'untitled.pdf' 且无法提取更好标题，跳过: {pdf_path.name}")
                 continue # 如果已经是untitled且无法提取更好标题，避免无效重命名

            if not clean_title: # sanitize_filename 现在返回 "untitled" 而不是空
                logging.warning(f"清理后的标题为空，跳过: {pdf_path.name}")
                continue

            # 检查清理后的名称是否与原名称（不含扩展名）相同
            if clean_title == pdf_path.stem:
                logging.info(f"文件名 '{pdf_path.name}' 无需更改。")
                continue

            new_path = find_available_filename(folder_path, clean_title, pdf_path.suffix)

            try:
                pdf_path.rename(new_path)
                logging.info(f"重命名成功: {pdf_path.name} -> {new_path.name}")
                rename_count += 1
            except OSError as e:
                logging.error(f"重命名文件 {pdf_path.name} 失败: {e}")
                fail_count += 1
            except Exception as e:
                 logging.error(f"重命名文件 {pdf_path.name} 时发生未知错误: {e}", exc_info=True)
                 fail_count += 1
        else:
            # 提取标题失败已在 extract_pdf_title 中记录日志
            fail_count += 1

    logging.info(f"处理完成。成功重命名 {rename_count} 个文件，失败或跳过 {fail_count} 个文件。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量重命名指定文件夹中的 PDF 文件，根据其标题。")
    parser.add_argument(
        "target_folder",
        type=str,
        help="包含要重命名的 PDF 文件的目标文件夹路径。"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="启用详细日志记录 (DEBUG 级别)。"
    )

    args = parser.parse_args()

    # 根据 verbose 参数设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("已启用详细日志记录。")

    target_folder_path = args.target_folder
    logging.info(f"开始处理目录: {target_folder_path}")
    rename_pdfs_in_folder(target_folder_path)
    logging.info("脚本执行完毕。")
