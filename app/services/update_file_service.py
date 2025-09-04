#app/services/update_file_service.py
import os
import logging
from app.services.async_ssh_pool import ssh_pool
from typing import List
from app.schemas.update_file import FileContentItem



logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FILES_DIR = os.path.join(BASE_DIR, 'files')
os.makedirs(FILES_DIR, exist_ok=True)

async def update_files(mcc: str, mnc: str, file_paths: list):
    if not mcc or not mnc or not file_paths:
        return {"status": "error", "message": "缺少必要参数：mcc, mnc, file_paths"}, 400

    try:
        for full_path in file_paths:
            parts = full_path.split("/", 1)
            if len(parts) != 2:
                logger.warning(f"文件路径格式错误: {full_path}")
                continue
            host_ip, relative_path = parts
            local_file_path = os.path.join(FILES_DIR, host_ip, relative_path)

            if not os.path.isfile(local_file_path):
                logger.warning(f"文件不存在: {local_file_path}")
                continue

            # 读取并修改本地文件内容
            with open(local_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("network country code"):
                    new_lines.append(f"network country code    {mcc}\n")
                elif stripped.startswith("mobile network code"):
                    new_lines.append(f"mobile network code     {mnc}\n")
                else:
                    new_lines.append(line)

            with open(local_file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            # 远程上传覆盖，远程下载同步
            ssh = await ssh_pool.get_connection(host_ip)
            if not ssh:
                logger.error(f"无法连接远端主机 {host_ip}")
                continue

            try:
                sftp = await ssh.start_sftp_client()
                remote_path = "/" + relative_path.lstrip("/")

                logger.info(f"上传本地文件 {local_file_path} 到远端 {remote_path}")
                await sftp.put(local_file_path, remote_path)

                logger.info(f"从远端拉取最新文件 {remote_path} 到本地 {local_file_path}")
                await sftp.get(remote_path, local_file_path)

                await sftp.exit()
            except Exception as e:
                logger.error(f"SFTP 上传/下载错误: {e}")
                continue

        return {"status": "success", "message": "文件已更新并同步"}, 200
    except Exception as e:
        logger.error(f"更新文件出错: {e}")
        return {"status": "error", "message": str(e)}, 500

async def update_files_full(files: List[FileContentItem]):
    try:
        if not files:
            return {"status": "error", "message": "未提供文件列表"}, 400

        for f in files:
            path = f.path
            content = f.content

            if not path or not content:
                continue

            parts = path.split("/", 1)
            if len(parts) != 2:
                continue

            host_ip, relative_path = parts
            local_file_path = os.path.join(FILES_DIR, host_ip, relative_path)

            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

            # 写入本地文件
            with open(local_file_path, "w", encoding="utf-8") as fw:
                fw.write(content)

            # 推送到远程并拉回
            ssh = await ssh_pool.get_connection(host_ip)
            if not ssh:
                logger.error(f"无法连接远端主机 {host_ip}")
                continue

            try:
                sftp = await ssh.start_sftp_client()
                remote_path = "/" + relative_path.lstrip("/")

                logger.info(f"上传本地文件 {local_file_path} 到远端 {remote_path}")
                await sftp.put(local_file_path, remote_path)

                logger.info(f"从远端拉取最新文件 {remote_path} 到本地 {local_file_path}")
                await sftp.get(remote_path, local_file_path)

                await sftp.exit()
            except Exception as e:
                logger.error(f"SFTP 错误: {e}")
                continue

        return {"status": "success", "message": "文件已保存、同步并回传校验"}, 200

    except Exception as e:
        logger.error(f"处理 update_file_full 出错: {e}")
        return {"status": "error", "message": str(e)}, 500
