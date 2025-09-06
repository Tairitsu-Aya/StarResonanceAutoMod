"""
日志配置
"""

import logging
import os
import sys
from datetime import datetime


def setup_logging(level=logging.INFO, debug_mode=False):
    """
    日志配置
    
    Args:
        level: 日志级别
        debug_mode: 是否为调试模式
    """
    # 如果已经配置过，直接返回
    if logging.getLogger().handlers:
        return
    
    # 设置日志级别
    if debug_mode:
        level = logging.DEBUG
    
    # 创建日志目录，打包环境下放在可执行文件所在目录。若无法写入
    #（例如位于只读路径），则回退到用户主目录下的临时文件夹。
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    log_dir = os.path.join(base_dir, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        # 若在打包后的目录无写入权限，使用用户主目录作为日志目录
        fallback = os.path.join(os.path.expanduser("~"), "StarResonanceLogs")
        try:
            os.makedirs(fallback, exist_ok=True)
            log_dir = fallback
        except OSError:
            # 仍然失败则放弃文件日志
            log_dir = None

    # 生成日志文件名（包含时间戳）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"star_resonance_{timestamp}.log") if log_dir else None
    
    # 配置日志格式
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    
    # 文件处理器
    file_handler = None
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
        except OSError as e:
            # 打包环境可能无写入权限，打印警告但不中断程序
            print(f"[WARN] 无法创建日志文件 {log_file}: {e}")
    
    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    if file_handler:
        root_logger.addHandler(file_handler)

    # 捕获未处理的异常并写入日志
    def _handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logging.getLogger().error(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _handle_exception
    
    # 记录日志配置信息
    logger = logging.getLogger(__name__)
    logger.info(f"日志系统已初始化 - 级别: {logging.getLevelName(level)}")
    if log_file:
        logger.info(f"日志文件: {log_file}")
    else:
        logger.info("日志文件: <disabled>")


def get_logger(name):
    """
    获取指定名称的日志器
    
    Args:
        name: 日志器名称
    
    Returns:
        Logger实例
    """
    return logging.getLogger(name)
