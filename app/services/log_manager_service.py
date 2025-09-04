#app/services/log_manager_service.py
import os
import json
import re
import logging
import traceback
from typing import Dict, List, Tuple, Optional, Any
import asyncio



from app.dependencies.zabbix import get_zapi
from app.services.async_ssh_pool import ssh_pool

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_DIR = os.path.join(BASE_DIR, 'net-conf')
LOG_OFFSET_DIR = os.path.join(BASE_DIR, 'log-offsets')
LOG_MIRROR_DIR = os.path.join(BASE_DIR, 'log-mirrors')

os.makedirs(LOG_OFFSET_DIR, exist_ok=True)
os.makedirs(LOG_MIRROR_DIR, exist_ok=True)

CHUNK_SIZE = 3000  # 1MB
ANSI_ESCAPE_RE = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
logger = logging.getLogger(__name__)


def strip_ansi_codes(text: str) -> str:
    return ANSI_ESCAPE_RE.sub('', text)

def find_config_by_group_id(group_id: str) -> Optional[Dict[str, Any]]:
    for fname in os.listdir(CONFIG_DIR):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(CONFIG_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if str(cfg.get("group_id")) == str(group_id):
                    logger.info(f"[find_config] Found config for group_id={group_id} in file {fname}")
                    return cfg
        except Exception as e:
            logger.error(f"Failed to parse config file {fpath}: {e}")
    logger.warning(f"[find_config] No config found for group_id={group_id}")
    return None

def load_or_init_offsets(offset_path: str) -> Dict[str, int]:
    try:
        if os.path.exists(offset_path):
            with open(offset_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load offsets from {offset_path}: {e}")
    return {}

def save_offsets(offset_path: str, offsets: Dict[str, int]) -> None:
    try:
        os.makedirs(os.path.dirname(offset_path), exist_ok=True)
        with open(offset_path, 'w', encoding='utf-8') as f:
            json.dump(offsets, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save offsets to {offset_path}: {e}")


class LogManagerService:
    _host_cache: Dict[str, List[Tuple[str, str]]] = {}

    @classmethod
    async def get_hosts_for_group(cls, group_id: str) -> List[Tuple[str, str]]:
        if group_id in cls._host_cache:
            return cls._host_cache[group_id]

        config = find_config_by_group_id(group_id)
        if not config:
            raise ValueError(f"No config found for group_id {group_id}")

        zapi = get_zapi()
        try:
            hosts = zapi.host.get(
                groupids=group_id,
                output=["hostid", "name"],
                selectInterfaces=["ip"]
            )
        except Exception as e:
            raise RuntimeError(f"Zabbix API error: {e}")

        result = []
        for host in hosts:
            ip = host['interfaces'][0]['ip']
            host_conf = config.get("hosts", {}).get(ip)
            if not host_conf:
                continue
            log_dirs = host_conf.get("log_dir")
            if isinstance(log_dirs, list):
                for log_dir in log_dirs:
                    result.append((ip, log_dir))
            elif isinstance(log_dirs, str):
                result.append((ip, log_dirs))

        cls._host_cache[group_id] = result
        return result

    @classmethod
    async def fetch_logs(cls, group_id: str, lines_per_page: int = 40, fetch_prev_page: int = 0) -> Dict[str, Any]:
        logger.info(f"[FETCH] Start fetching logs for group_id={group_id}")
        hosts = await cls.get_hosts_for_group(group_id)
        result = {}
        errors = []

        for ip, log_dir in hosts:
            logger.info(f"[FETCH] Processing host={ip}, log_dir={log_dir}")
            dir_part = log_dir.lstrip("/")
            offset_path = os.path.join(LOG_OFFSET_DIR, f"group_{group_id}_{ip}_{dir_part.replace('/', '_')}.json")
            mirror_dir = os.path.join(LOG_MIRROR_DIR, f"group_{group_id}_{ip}", dir_part)
            os.makedirs(mirror_dir, exist_ok=True)
            offsets = load_or_init_offsets(offset_path)
            logs = {}

            try:
                ssh = await asyncio.wait_for(ssh_pool.get_connection(ip), timeout=2)
                if not ssh:
                    errors.append({"host": ip, "error": "SSH connection failed"})
                    continue

                managed_conn = ssh_pool.pool.get(ip)
                if not managed_conn:
                    errors.append({"host": ip, "error": "Managed SSH connection not found"})
                    continue

                async with managed_conn.channel_lock:
                    async with await ssh.start_sftp_client() as sftp:
                        remote_files = [f for f in await sftp.listdir(log_dir) if f.endswith(('.log', '.count'))]

                        for log_file in remote_files:
                            remote_path = os.path.join(log_dir, log_file)
                            mirror_path = os.path.join(mirror_dir, log_file)

                            offset_info = offsets.get(log_file, {})
                            if isinstance(offset_info, int):
                                offset = offset_info
                                pages = []
                            else:
                                offset = offset_info.get("offset", 0)
                                pages = offset_info.get("pages", [])


                            stat = await sftp.stat(remote_path)
                            if stat.size < offset:
                                logger.warning(f"[FETCH] Offset reset due to file truncation: {remote_path}")
                                offset = 0
                                pages = [0]
                                residual_lines = 0 
                                open(mirror_path, 'w', encoding='utf-8').close()
                            else:
                                open(mirror_path, 'a', encoding='utf-8').close()

                            if stat.size == offset:
                                logger.info(f"[FETCH] File {log_file} has no new content. Returning last page from prev_page_start.")

                                prev_page_start = 0
                                if isinstance(offset_info, dict):
                                    prev_page_start = offset_info.get("prev_page_start", 0)
                                    residual_lines = offset_info.get("residual_lines", 0)
                                else:
                                    residual_lines = 0

                                try:
                                    with open(mirror_path, 'r', encoding='utf-8') as mf:
                                        mf.seek(prev_page_start)
                                        page_data = mf.read(offset - prev_page_start)

                                    logs[log_file] = {
                                        "content": strip_ansi_codes(page_data),
                                        "start_offset": prev_page_start,
                                        "residual_lines": residual_lines,
                                        "is_end": True
                                    }

                                except Exception as e:
                                    logger.error(f"[FETCH] Failed to read last page from mirror file: {mirror_path}, error: {e}")
                                
                                continue

                            async with await sftp.open(remote_path, 'rb') as f:
                                await f.seek(offset)
                                data = await f.read(CHUNK_SIZE)

                            content = data.decode('utf-8', errors='replace') if isinstance(data, bytes) else data


                            # ---------- 分页处理 ----------
                            curr_offset = offset
                            new_pages = []
                            residual_lines = offset_info.get("residual_lines", 0)

                            logger.info(
                                f"[PAGING] Start processing file: {log_file} | "
                                f"initial_offset={offset}, existing_residual_lines={residual_lines}"
                            )

                            lines = content.splitlines(True)

                            # 检查最后一行是否不完整（没有 \n），就临时去掉，不计入分页
                            if lines and not lines[-1].endswith(('\n', '\r')):
                                partial_line = lines.pop()
                                partial_line_bytes = partial_line.encode('utf-8', errors='replace')
                                content = content[:-len(partial_line)]  # 从原始字符串也删掉它
                                data = data[:-len(partial_line_bytes)]  # 同时修剪 byte 数据，确保 offset 精确
                                logger.info(f"[PAGING] Last line is partial, will defer to next fetch: {repr(partial_line)}")

                            with open(mirror_path, 'a', encoding='utf-8') as mf:
                                mf.write(content)

                            for line in lines:
                                line_bytes = line.encode('utf-8', errors='replace')
                                curr_offset += len(line_bytes)
                                residual_lines += 1

                                if residual_lines == lines_per_page:
                                    new_pages.append(curr_offset)
                                    logger.debug(f"[PAGING] Page complete at offset={curr_offset} for {log_file}")
                                    residual_lines = 0  # 重置，因为刚好分页完一页

                            # ---------- 更新分页信息和偏移 ----------
                            pages.extend(new_pages)
                            pages = sorted(set(pages))
                            if 0 not in pages:
                                pages.insert(0, 0)
                            new_offset = offset + len(data)
                            logger.info(
                                f"[PAGING] Finished file: {log_file} | "
                                f"bytes_read={len(data)}, new_offset={new_offset}, "
                                f"new_pages_added={len(new_pages)}, residual_lines_left={residual_lines}"
                            )

                            prev_page_start = 0
                            last = 0
                            for p in pages:
                                if p >= new_offset:
                                    break
                                prev_page_start = last
                                last = p

                            offsets[log_file] = {
                                "offset": new_offset,
                                "pages": pages,
                                "prev_page_start": prev_page_start,
                                "residual_lines": residual_lines
                            }

                            logger.info(f"[FETCH] Updated offset for {log_file}: offset={new_offset}, prev_start={prev_page_start}")
                            logs[log_file] = {
                                "content": strip_ansi_codes(content),
                                "start_offset": prev_page_start,
                                "residual_lines": residual_lines,
                                "is_end": False
                            }

                            if fetch_prev_page == 1:
                                try:
                                    with open(mirror_path, 'r', encoding='utf-8') as mf:
                                        mf.seek(prev_page_start)
                                        full_data = mf.read(new_offset - prev_page_start)
                                    logs[log_file]["content"] = strip_ansi_codes(full_data)
                                    logger.info(f"[FETCH] fetch_prev_page==1 生效，返回内容从 prev_page_start={prev_page_start} 到 new_offset={new_offset}")
                                except Exception as e:
                                    logger.info(f"[FETCH] fetch_prev_page==1 读取扩展内容失败: {e}")

                        # ---------- 清理已删除的远端文件 ----------
                        local_files = [f for f in os.listdir(mirror_dir) if f.endswith(('.log', '.count'))]
                        for local_file in local_files:
                            if local_file not in remote_files:
                                os.remove(os.path.join(mirror_dir, local_file))
                                offsets.pop(local_file, None)
                                logger.info(f"[FETCH] Removed stale local file: {local_file}")

                save_offsets(offset_path, offsets)

                if logs:
                    result[f"{ip}:{log_dir}"] = logs

            except Exception as e:
                logger.error(f"[FETCH] Error while fetching logs from {ip}: {e}")
                logger.error(traceback.format_exc())
                errors.append({"host": ip, "error": str(e)})

        logger.info(f"[FETCH] Completed log fetching for group_id={group_id}")
        return {"logs": result, "errors": errors}



    @classmethod
    async def read_full_group_logs(cls, group_id: str) -> Dict[str, Any]:
        logger.info(f"[READ] Start reading full group logs for group_id={group_id}")
        hosts = await cls.get_hosts_for_group(group_id)
        result = {}
        errors = []

        for ip, log_dir in hosts:
            logger.info(f"[READ] Processing host={ip}, log_dir={log_dir}")
            dir_part = log_dir.lstrip("/")
            offset_path = os.path.join(LOG_OFFSET_DIR, f"group_{group_id}_{ip}_{dir_part.replace('/', '_')}.json")
            mirror_dir = os.path.join(LOG_MIRROR_DIR, f"group_{group_id}_{ip}", dir_part)
            logs = {}

            if not os.path.exists(offset_path):
                logger.warning(f"[READ] Offset file missing: {offset_path}, skipping host={ip}")
                continue

            try:
                offsets = load_or_init_offsets(offset_path)

                for log_file, info in offsets.items():
                    if isinstance(info, int):
                        offset = info
                        pages = []
                    else:
                        offset = info.get("offset", 0)
                        pages = info.get("pages", [])

                    if offset == 0:
                        logger.debug(f"[READ] Offset for {log_file} is 0, skipping")
                        continue

                    local_path = os.path.join(mirror_dir, log_file)
                    if not os.path.exists(local_path):
                        logger.warning(f"[READ] Local mirror missing: {local_path}, skipping file")
                        continue

                    start = 0
                    if pages:
                        pages = sorted(pages)
                        for i in range(len(pages)):
                            if pages[i] >= offset:
                                break
                            start = pages[i]

                    logger.debug(f"[READ] Reading file={log_file}, start={start}, offset={offset}, path={local_path}")

                    with open(local_path, "rb") as f:
                        f.seek(start)
                        data = f.read(offset - start)
                        content = data.decode("utf-8", errors="replace")

                    logs[log_file] = {
                        "content": strip_ansi_codes(content),
                        "start_offset": start,
                        "end_offset": offset
                    }

                    logger.info(f"[READ] Finished reading {log_file}, read_size={offset - start} bytes")

                if logs:
                    result[f"{ip}:{log_dir}"] = logs

            except Exception as e:
                logger.error(f"[READ] Error reading logs for group {group_id}, host {ip}: {e}")
                logger.error(traceback.format_exc())
                errors.append({"host": ip, "error": str(e)})

        logger.info(f"[READ] Completed log reading for group_id={group_id}")
        return {"logs": result, "errors": errors}


    @classmethod
    async def read_single_log(cls, group_id: str, host_ip: str, log_dir: str, log_file: str) -> Dict[str, Any]:
        logger.info(f"[READ_SINGLE] Start reading single log: {host_ip} {log_dir} {log_file}")

        dir_part = log_dir.lstrip("/")
        offset_path = os.path.join(LOG_OFFSET_DIR, f"group_{group_id}_{host_ip}_{dir_part.replace('/', '_')}.json")
        mirror_dir = os.path.join(LOG_MIRROR_DIR, f"group_{group_id}_{host_ip}", dir_part)
        local_path = os.path.join(mirror_dir, log_file)

        if not os.path.exists(offset_path):
            error_msg = f"Offset file missing: {offset_path}"
            logger.warning(f"[READ_SINGLE] {error_msg}")
            return {"logs": {}, "errors": [{"host": host_ip, "error": error_msg}]}

        if not os.path.exists(local_path):
            error_msg = f"Local mirror file missing: {local_path}"
            logger.warning(f"[READ_SINGLE] {error_msg}")
            return {"logs": {}, "errors": [{"host": host_ip, "error": error_msg}]}

        try:
            offsets = load_or_init_offsets(offset_path)
            info = offsets.get(log_file)
            if not info:
                error_msg = f"No offset info for log file: {log_file}"
                logger.warning(f"[READ_SINGLE] {error_msg}")
                return {"logs": {}, "errors": [{"host": host_ip, "error": error_msg}]}

            if isinstance(info, int):
                offset = info
                pages = []
            else:
                offset = info.get("offset", 0)
                pages = info.get("pages", [])

            if offset == 0:
                logger.debug(f"[READ_SINGLE] Offset for {log_file} is 0, no new content.")
                return {
                    "logs": {host_ip: {log_file: {"content": "", "start_offset": 0, "end_offset": 0}}},
                    "errors": []
                }

            start = 0
            if pages:
                pages = sorted(pages)
                # 找到满足读取内容长度 > 一页 且 < 两页的 start 和 offset
                # 先找到offset前面的那个页作为start，然后向前看一个页作为start的下界，保证长度
                for i in range(len(pages)):
                    if pages[i] >= offset:
                        break
                    start = pages[i]


            logger.debug(f"[READ_SINGLE] Reading file={log_file}, start={start}, offset={offset}, path={local_path}")

            with open(local_path, "rb") as f:
                f.seek(start)
                data = f.read(offset - start)
                content = data.decode("utf-8", errors="replace")

            log_key = f"{host_ip}:{log_dir}"

            logs = {
                log_key: {
                    log_file: {
                        "content": strip_ansi_codes(content),
                        "start_offset": start,
                        "end_offset": offset
                    }
                }
            }

            logger.info(f"[READ_SINGLE] Finished reading {log_file}, read_size={offset - start} bytes")

            return {"logs": logs, "errors": []}

        except Exception as e:
            logger.error(f"[READ_SINGLE] Error reading single log {log_file}: {e}")
            logger.error(traceback.format_exc())
            return {"logs": {}, "errors": [{"host": host_ip, "error": str(e)}]}


    @classmethod
    async def load_older_logs(cls, group_id: str, filename: str, host_ip: str, log_dir: str, offset: int, lines_per_page: int = 40) -> Dict[str, Any]:
        logger.info(f"[OLDER] Loading older logs for {host_ip}:{log_dir}/{filename} with offset {offset}")
        dir_part = log_dir.lstrip("/")
        mirror_path = os.path.join(LOG_MIRROR_DIR, f"group_{group_id}_{host_ip}", dir_part, filename)
        offset_path = os.path.join(LOG_OFFSET_DIR, f"group_{group_id}_{host_ip}_{dir_part.replace('/', '_')}.json")

        result = {}
        errors = []

        if not os.path.exists(mirror_path):
            logger.warning(f"[OLDER] Mirror file missing: {mirror_path}")
            errors.append({"host": host_ip, "error": f"Log file {filename} not found"})
            return {"logs": {}, "errors": errors}

        if not os.path.exists(offset_path):
            logger.warning(f"[OLDER] Offset file missing: {offset_path}")
            errors.append({"host": host_ip, "error": f"Offset metadata not found for {filename}"})
            return {"logs": {}, "errors": errors}

        try:
            offsets = load_or_init_offsets(offset_path)
            info = offsets.get(filename, {})
            if not isinstance(info, dict):
                raise ValueError("Offset metadata malformed")

            pages = sorted(set(info.get("pages", [])))
            logger.debug(f"[OLDER] Pages={pages}, Requested offset={offset}")

            if offset not in pages:
                logger.warning(f"[OLDER] Offset {offset} not found in pages list")
                return {"logs": {}, "errors": [{"host": host_ip, "error": "Invalid offset"}], "start_offset": offset}

            idx = pages.index(offset)
            if idx == 0:
                # 已经是第一页，没有更早的了
                logger.info(f"[OLDER] Offset {offset} is the first page, no older page")
                return {"logs": {}, "errors": [], "start_offset": offset}

            prev_page_start = pages[idx - 1]

            with open(mirror_path, "rb") as f:
                f.seek(prev_page_start)
                chunk = f.read(offset - prev_page_start)

            content = strip_ansi_codes(chunk.decode('utf-8', errors='replace'))

            log_key = f"{host_ip}:{log_dir}"
            result = {
                log_key: {
                    filename: {
                        "content": content,
                        "start_offset": prev_page_start,
                        "end_offset": offset
                    }
                }
            }
            logger.info(f"[OLDER] Loaded older chunk: {prev_page_start}-{offset}")

            return {
                "logs": result,
                "errors": []
            }

        except Exception as e:
            logger.error(f"[OLDER] Error loading older logs for {host_ip}: {e}")
            logger.error(traceback.format_exc())
            errors.append({"host": host_ip, "error": str(e)})
            return {"logs": {}, "errors": errors, "start_offset": 0}
