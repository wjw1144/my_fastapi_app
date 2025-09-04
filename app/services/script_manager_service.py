import os
import json
import logging
from app.services.async_ssh_pool import ssh_pool
import asyncssh
import asyncio
import uuid


logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'net-conf'))

def find_config_by_group_id(group_id: str):
    for fname in os.listdir(CONFIG_DIR):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(CONFIG_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if str(cfg.get("group_id")) == str(group_id):
                    return cfg
        except Exception as e:
            logger.error(f"Failed to parse config file {fpath}: {e}")
    return None

async def manage_script(group_id: str, action: str):
    config = find_config_by_group_id(group_id)
    if not config:
        return {"status": "error", "message": f"No config file found for group_id {group_id}"}, 404

    hosts = config.get("hosts", {})
    results = {}

    for ip, host_conf in hosts.items():
        start_script = host_conf.get("start_script_path")
        stop_script = host_conf.get("stop_script_path")
        script_path = start_script if action == 'start' else stop_script

        if not script_path:
            results[ip] = {'status': 'skipped', 'message': f"No {action} script path configured."}
            continue

        try:
            ssh = await ssh_pool.get_connection(ip)
            if not ssh:
                results[ip] = {'status': 'error', 'message': 'SSH connection failed'}
                continue

            script_dir = os.path.dirname(script_path)
            script_name = os.path.basename(script_path)
            cmd = f'cd "{script_dir}" && ./"{script_name}"'

            logger.info(f"Executing on {ip}: {cmd}")

            result = await ssh.run(cmd, check=False, timeout=10)
            results[ip] = {
                'status': 'success' if result.exit_status == 0 else 'error',
                'exit_code': result.exit_status,
                'stdout': result.stdout.strip(),
                'stderr': result.stderr.strip()
            }
            
        except Exception as e:
            logger.error(f"Error executing script on {ip}: {e}")
            results[ip] = {'status': 'error', 'message': str(e)}

    return {"status": "success", "results": results}, 200

async def send_command_to_group(group_id: str, command: str):
    config = find_config_by_group_id(group_id)
    if not config:
        return {"status": "error", "message": f"No config found for group_id {group_id}"}, 404

    hosts = config.get("hosts", {})
    results = {}
    log_path = "/home/wjw/5g-r/script/gnb.log"

    for ip in hosts:
        try:
            ssh = await ssh_pool.get_connection(ip)
            if not ssh:
                results[ip] = {"status": "error", "message": "SSH connection failed"}
                continue

            # 使用唯一标识符作为日志标记
            marker = f"CMD_MARKER_{uuid.uuid4().hex}"
            mark_cmd = f'echo "{marker}" >> {log_path}'
            await ssh.run(mark_cmd, check=False)

            # 发送命令到 screen
            screen_cmd = f"sudo screen -S gnb -X stuff '{command}\\r'"
            send_result = await ssh.run(screen_cmd, check=False)
            if send_result.exit_status != 0:
                results[ip] = {
                    "status": "error",
                    "message": f"Failed to send command: {send_result.stderr.strip()}"
                }
                continue

            # 轮询日志，获取 marker 之后的新内容
            output_lines = []
            found_marker = False

            for _ in range(20):  # 最多等 10 次，每次 1 秒
                await asyncio.sleep(1)
                read_cmd = f'tail -n 100 {log_path}'
                log_result = await ssh.run(read_cmd, check=False)

                if log_result.exit_status != 0:
                    continue

                lines = log_result.stdout.splitlines()
                if marker in lines:
                    idx = lines.index(marker)
                    new_output = lines[idx + 1:]
                    if new_output:
                        output_lines = new_output
                        break
                    else:
                        found_marker = True  # 标记找到了，但还没内容，继续等

            results[ip] = {
                "status": "success" if output_lines else "timeout",
                "stdout": "\n".join(output_lines) if output_lines else "(No output yet)",
                "marker": marker
            }

        except Exception as e:
            logger.error(f"Error sending command on {ip}: {e}")
            results[ip] = {"status": "error", "message": str(e)}

    return {"status": "success", "results": results}, 200


async def check_status(group_id: str):
    config = find_config_by_group_id(group_id)
    if not config:
        return {"status": "error", "message": f"No config found for group_id {group_id}"}, 404

    hosts = config.get("hosts", {})
    results = {}
    status_cmd = "sudo service apache2 status"

    for ip in hosts:
        try:
            ssh = await ssh_pool.get_connection(ip)
            if not ssh:
                results[ip] = {"status": "error", "message": "SSH connection failed"}
                continue

            result = await ssh.run(status_cmd, check=False, timeout=10)
            results[ip] = {
                "status": "success" if result.exit_status == 0 else "error",
                "exit_code": result.exit_status,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()
            }

        except Exception as e:
            logger.error(f"Error checking status on {ip}: {e}")
            results[ip] = {"status": "error", "message": str(e)}

    return {"status": "success", "results": results}, 200


async def ping_host_from_remote(group_id: str, target_ip: str):
    config = find_config_by_group_id(group_id)
    if not config:
        return {"status": "error", "message": f"No config found for group_id {group_id}"}, 404

    hosts = config.get("hosts", {})
    results = {}

    ping_cmd = f"ping -c 1 -W 1 {target_ip}"

    for ip in hosts:
        try:
            ssh = await ssh_pool.get_connection(ip)
            if not ssh:
                results[ip] = {"status": "error", "message": "SSH connection failed"}
                continue

            result = await ssh.run(ping_cmd, check=False, timeout=5)
            reachable = result.exit_status == 0

            results[ip] = {
                "status": "success",
                "reachable": reachable,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "exit_code": result.exit_status
            }

        except Exception as e:
            logger.error(f"Error pinging from {ip}: {e}")
            results[ip] = {"status": "error", "message": str(e)}

    return {"status": "success", "results": results}, 200

