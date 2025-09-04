#app/services/file_service.py
import os
import json
from app.utils import async_config_manager as cfg_mgr
from app.dependencies.zabbix import get_zapi
from app.services.async_ssh_pool import ssh_pool
from app.services.sftp_utils import sftp_get_dir
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FILES_DIR = os.path.join(BASE_DIR, 'files')
CONFIG_DIR = os.path.join(BASE_DIR, 'net-conf')

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

def find_config_by_group_id(group_id: str):
    for filename in os.listdir(CONFIG_DIR):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(CONFIG_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                conf = json.load(f)
            if str(conf.get("group_id")) == str(group_id):
                logger.info(f"Found config {filename} for group_id {group_id}")
                return conf
        except Exception as e:
            logger.error(f"Failed to load config file {filepath}: {e}")
    return None

async def copy_files_by_group_id(group_id: str):
    config = find_config_by_group_id(group_id)
    if not config:
        return {"status": "error", "message": f"No config file found for group_id {group_id}"}, 404

    zapi = get_zapi()
    hosts = zapi.host.get(groupids=group_id, output=["hostid", "name"], selectInterfaces=["ip"])

    if not hosts:
        return {"status": "error", "message": "No hosts found in the specified group."}, 404

    copied_files = []
    failures = []

    for host in hosts:
        host_ip = host['interfaces'][0]['ip']
        host_conf = config.get("hosts", {}).get(host_ip)
        if not host_conf:
            logger.warning(f"No config entry for host IP {host_ip}, skipping")
            continue

        conf_dir = host_conf.get("conf_dir")
        conf_paths = host_conf.get("conf_paths", [])

        ssh = await ssh_pool.get_connection(host_ip)
        if not ssh:
            logger.error(f"Unable to establish SSH connection to {host_ip}")
            failures.append({"host": host_ip, "error": "SSH connection failed"})
            continue

        try:
            sftp = await ssh.start_sftp_client()
            local_dir = os.path.join(FILES_DIR, host_ip)
            os.makedirs(local_dir, exist_ok=True)

            if conf_dir:
                try:
                    logger.info(f"Start copying directory {conf_dir} from {host_ip}")
                    await sftp_get_dir(sftp, conf_dir, local_dir, copied_files, host_ip, logger=logger)
                except Exception as e:
                    logger.error(f"Failed to copy directory {conf_dir} from {host_ip}: {e}")
                    failures.append({"host": host_ip, "directory": conf_dir, "error": str(e)})

            for remote_path in conf_paths:
                try:
                    relative_path = remote_path.lstrip('/')
                    local_file_path = os.path.join(local_dir, relative_path)
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

                    logger.info(f"Copying file {remote_path} from {host_ip} to {local_file_path}")
                    await sftp.get(remote_path, local_file_path)

                    copied_files.append(f"{host_ip}{remote_path}")
                except Exception as e:
                    logger.error(f"Failed to copy file {remote_path} from {host_ip}: {e}")
                    failures.append({"host": host_ip, "file": remote_path, "error": str(e)})
            sftp.exit()

        except Exception as e:
            logger.error(f"General SSH/SFTP error on {host_ip}: {e}")
            failures.append({"host": host_ip, "error": str(e)})

    return {
        "status": "success",
        "copied": copied_files,
        "failures": failures
    }, 200
