
from logging_setup import get_logger

logger = get_logger(__name__)
"""
Скачивание и установка ffmpeg автоматически
"""

import requests
import zipfile
import os
import shutil
from pathlib import Path


def download_ffmpeg():
    """Скачать ffmpeg для Windows"""

    logger.info("=== USTANOVKA FFMPEG ===\n")

    # URL для скачивания ffmpeg
    url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

    # Путь для установки
    install_dir = Path("C:/ffmpeg")
    zip_file = "ffmpeg.zip"

    logger.info("Skachivanie ffmpeg...")
    logger.info(f"URL: {url}")

    try:
        # Скачиваем
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        logger.info(f"Razmer: {total_size / 1024 / 1024:.1f} MB")

        with open(zip_file, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        logger.info(f"\rProgress: {percent:.1f}%", end='')

        logger.info("\n[OK] Skachano!")

        # Распаковываем
        logger.info("\nRaspakuem...")
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(".")

        # Находим папку с ffmpeg
        extracted_dir = None
        for item in os.listdir("."):
            if item.startswith("ffmpeg-") and os.path.isdir(item):
                extracted_dir = item
                break

        if not extracted_dir:
            logger.error("[ERROR] Ne udalos nayti raspakovannyy ffmpeg")
            return False

        # Перемещаем в C:\ffmpeg
        logger.info(f"\nPeremeshchaem v {install_dir}...")

        if install_dir.exists():
            logger.info("Udalyaem staruyu versiyu...")
            shutil.rmtree(install_dir)

        shutil.move(extracted_dir, install_dir)

        # Удаляем zip
        os.remove(zip_file)

        logger.info(f"[OK] ffmpeg ustanovlen v: {install_dir}")
        logger.info(f"\nTeper dobavte v PATH: {install_dir / 'bin'}")
        logger.info("\nKak dobavit v PATH:")
        logger.info("1. Win + R -> sysdm.cpl")
        logger.info("2. Dopolnitelno -> Peremennye sredy")
        logger.info("3. Path -> Izmenit -> Sozdat")
        logger.info(f"4. Dobavte: {install_dir / 'bin'}")
        logger.info("5. OK -> Perezapustite terminal")

        return True

    except Exception as e:
        logger.error(f"\n[ERROR] {str(e)}")
        return False


if __name__ == '__main__':
    download_ffmpeg()
