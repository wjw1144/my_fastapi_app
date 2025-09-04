import os
import sqlite3
import traceback
from datetime import datetime
from .file_service import FILES_DIR, find_config_by_group_id
from app.dependencies.zabbix import get_zapi
from app.services.async_ssh_pool import ssh_pool


class UserService:
    @staticmethod
    def get_db_path_and_host_ip(group_id: str):
        print(f"[DEBUG] get_db_path_and_host_ip called with group_id={group_id}")
        config = find_config_by_group_id(group_id)
        if not config:
            print(f"[ERROR] No config found for group {group_id}")
            raise FileNotFoundError(f"No config for group {group_id}")

        for ip, host_conf in config.get("hosts", {}).items():
            if "user_mgmt" in host_conf.get("roles", []):
                db_path = host_conf.get("db_path")
                if not db_path:
                    print(f"[ERROR] No db_path specified for host {ip}")
                    raise ValueError(f"No db_path specified for host {ip}")
                full_path = os.path.join(FILES_DIR, ip, db_path.lstrip("/"))
                print(f"[DEBUG] Found db_path: {full_path}, host_ip: {ip}, db_path_remote: {db_path}")
                return full_path, ip, db_path

        print(f"[ERROR] No host with role 'user_mgmt' found in group {group_id}")
        raise FileNotFoundError(f"No host with role 'user_mgmt' found in group {group_id}")

    @staticmethod
    async def sync_db_file_to_remote(host_ip: str, db_path_relative: str):
        local_file_path = os.path.join(FILES_DIR, host_ip, db_path_relative.lstrip("/"))
        print(f"[DEBUG] sync_db_file_to_remote called with host_ip={host_ip}, db_path_relative={db_path_relative}")
        if not os.path.isfile(local_file_path):
            err_msg = f"本地文件不存在: {local_file_path}"
            print(f"[ERROR] {err_msg}")
            raise FileNotFoundError(err_msg)

        ssh = await ssh_pool.get_connection(host_ip)
        if not ssh:
            err_msg = f"无法建立SSH连接到 {host_ip}"
            print(f"[ERROR] {err_msg}")
            raise ConnectionError(err_msg)

        try:
            async with await ssh.start_sftp_client() as sftp:
                remote_path = db_path_relative if db_path_relative.startswith("/") else "/" + db_path_relative
                print(f"[DEBUG] Uploading local {local_file_path} to remote {remote_path}")
                await sftp.put(local_file_path, remote_path)
                print(f"[DEBUG] Downloading remote {remote_path} to local {local_file_path}")
                await sftp.get(remote_path, local_file_path)
                print("[DEBUG] sync_db_file_to_remote success")
        except Exception as e:
            print(f"[ERROR] 同步失败: {e}")
            print(traceback.format_exc())
            raise RuntimeError(f"同步失败: {e}")

    @staticmethod
    def get_users(group_id: str):
        print(f"[DEBUG] get_users called with group_id={group_id}")
        db_path, _, _ = UserService.get_db_path_and_host_ip(group_id)
        if not os.path.exists(db_path):
            print(f"[ERROR] 数据库文件不存在: {db_path}")
            raise FileNotFoundError("数据库文件不存在")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriber")
        rows = cursor.fetchall()
        conn.close()

        users = []
        for row in rows:
            user = {k: v for k, v in zip(row.keys(), row) if v not in (None, "")}
            users.append(user)
        print(f"[DEBUG] get_users returning {len(users)} users")
        return users

    @staticmethod
    def add_user(group_id, imsi, msisdn, msc_number):
        print(f"[DEBUG] add_user called with group_id={group_id}, imsi={imsi}, msisdn={msisdn}, msc_number={msc_number}")
        try:
            db_path, host_ip, db_path_remote = UserService.get_db_path_and_host_ip(group_id)
            print(f"[DEBUG] DB path: {db_path}, host_ip: {host_ip}, remote_db_path: {db_path_remote}")

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO subscriber (imsi, msisdn, msc_number, nam_cs, nam_ps, ms_purged_cs, ms_purged_ps, last_lu_seen) "
                "VALUES (?, ?, ?, 1, 1, 0, 0, ?)",
                (imsi, msisdn, msc_number or 'unnamed-MSC', now)
            )
            conn.commit()
            conn.close()
            print(f"[DEBUG] add_user success, returning host_ip and db_path_remote")
            return host_ip, db_path_remote
        except Exception as e:
            print(f"[ERROR] add_user exception:\n{traceback.format_exc()}")
            raise

    @staticmethod
    def update_user(group_id, imsi, msisdn, msc_number):
        print(f"[DEBUG] update_user called with group_id={group_id}, imsi={imsi}, msisdn={msisdn}, msc_number={msc_number}")
        try:
            db_path, host_ip, db_path_remote = UserService.get_db_path_and_host_ip(group_id)
            print(f"[DEBUG] DB path: {db_path}, host_ip: {host_ip}, remote_db_path: {db_path_remote}")

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            if msc_number is not None:
                cursor.execute(
                    "UPDATE subscriber SET msisdn=?, msc_number=? WHERE imsi=?",
                    (msisdn, msc_number or 'unnamed-MSC', imsi)
                )
            else:
                cursor.execute(
                    "UPDATE subscriber SET msisdn=? WHERE imsi=?",
                    (msisdn, imsi)
                )
            if cursor.rowcount == 0:
                conn.close()
                err_msg = "IMSI not found"
                print(f"[ERROR] {err_msg}")
                raise ValueError(err_msg)
            conn.commit()
            conn.close()
            print(f"[DEBUG] update_user success, returning host_ip and db_path_remote")
            return host_ip, db_path_remote
        except Exception as e:
            print(f"[ERROR] update_user exception:\n{traceback.format_exc()}")
            raise

    @staticmethod
    def delete_user(group_id, imsi):
        print(f"[DEBUG] delete_user called with group_id={group_id}, imsi={imsi}")
        try:
            db_path, host_ip, db_path_remote = UserService.get_db_path_and_host_ip(group_id)
            print(f"[DEBUG] DB path: {db_path}, host_ip: {host_ip}, remote_db_path: {db_path_remote}")

            if not os.path.exists(db_path):
                print(f"[ERROR] Database path does not exist: {db_path}")
                raise FileNotFoundError(f"数据库文件不存在: {db_path}")

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            print(f"[DEBUG] Executing DELETE FROM subscriber WHERE imsi='{imsi}'")
            cursor.execute("DELETE FROM subscriber WHERE imsi=?", (imsi,))
            print(f"[DEBUG] DELETE affected rows: {cursor.rowcount}")
            if cursor.rowcount == 0:
                conn.close()
                err_msg = f"[ERROR] IMSI not found in DB: {imsi}"
                print(err_msg)
                raise ValueError("IMSI not found")
            conn.commit()
            conn.close()
            print(f"[DEBUG] delete_user success, returning host_ip and db_path_remote")
            return host_ip, db_path_remote
        except Exception as e:
            print(f"[ERROR] delete_user exception:\n{traceback.format_exc()}")
            raise

    @staticmethod
    def batch_add_users(group_id, users):
        print(f"[DEBUG] batch_add_users called with group_id={group_id}, users count={len(users)}")
        try:
            db_path, host_ip, db_path_remote = UserService.get_db_path_and_host_ip(group_id)
            print(f"[DEBUG] DB path: {db_path}, host_ip: {host_ip}, remote_db_path: {db_path_remote}")

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            for user in users:
                imsi = user.get('imsi')
                msisdn = user.get('msisdn')
                msc_number = user.get('msc_number', 'unnamed-MSC')
                if not imsi or not msisdn:
                    print(f"[WARN] Skipping user with missing imsi or msisdn: {user}")
                    continue
                cursor.execute(
                    "INSERT INTO subscriber (imsi, msisdn, msc_number, nam_cs, nam_ps, ms_purged_cs, ms_purged_ps, last_lu_seen) "
                    "VALUES (?, ?, ?, 1, 1, 0, 0, ?)",
                    (imsi, msisdn, msc_number or 'unnamed-MSC', now)
                )
            conn.commit()
            conn.close()
            print(f"[DEBUG] batch_add_users success, returning host_ip and db_path_remote")
            return host_ip, db_path_remote
        except Exception as e:
            print(f"[ERROR] batch_add_users exception:\n{traceback.format_exc()}")
            raise
