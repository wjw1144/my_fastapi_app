#app/services/sftp_utils.py
import os
import stat
import logging

async def sftp_get_dir(sftp, remote_dir, local_base_dir, copied_files, host_ip, base_remote_dir=None, logger=None):
    if base_remote_dir is None:
        base_remote_dir = remote_dir.rstrip('/')

    if logger:
        logger.info(f"Listing remote directory: {remote_dir}")
        logger.info(f"Listing local directory: {local_base_dir}")

    try:
        entries = await sftp.listdir(remote_dir)
    except Exception as e:
        if logger:
            logger.error(f"Failed to list directory {remote_dir}: {e}")
        return

    for filename in entries:
        # 跳过当前目录 . 和父目录 ..
        if filename in ('.', '..'):
            continue

        remote_path = os.path.normpath(os.path.join(remote_dir, filename))
        relative_path = remote_path.lstrip('/')
        local_path = os.path.join(local_base_dir, relative_path)

        if logger:
            logger.info(f"Processing remote_path: {remote_path}, local_path: {local_path}")

        try:
            attrs = await sftp.stat(remote_path)
        except Exception as e:
            if logger:
                logger.error(f"Failed to stat {remote_path}: {e}")
            continue

        if stat.S_ISDIR(attrs.permissions):
            os.makedirs(local_path, exist_ok=True)
            if logger:
                logger.info(f"Created local directory: {local_path}")
            await sftp_get_dir(sftp, remote_path, local_base_dir, copied_files, host_ip, base_remote_dir, logger)
        else:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            if logger:
                logger.info(f"Copying file from {remote_path} to {local_path}")
            try:
                await sftp.get(remote_path, local_path)
                copied_files.append(f"{host_ip}{remote_path}")
            except Exception as e:
                if logger:
                    logger.error(f"Failed to get file {remote_path}: {e}")
