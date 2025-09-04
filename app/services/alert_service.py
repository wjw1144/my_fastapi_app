# app/services/alert_service.py
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from app.dependencies.zabbix import get_zapi
from typing import Dict, List, Tuple, Optional, Any
import os
import json
import re
import logging


logger = logging.getLogger(__name__)
# 需要监控的进程名称列表
MONITORED_PROCESSES_GSM = [
    "osmo-hlr", "osmo-stp", "osmo-msc", "osmo-bsc", "osmo-ggsn",
    "osmo-sgsn", "osmo-trx-uhd", "osmo-bts-trx", "osmo-pcu",
    "osmo-mgw", "osmo-sip-connector", "isdnrelay"
]

MONITORED_PROCESSES_5G = [
    "open5gs-amfd", "open5gs-hssd", "open5gs-nssfd", "open5gs-scpd",
    "open5gs-smfd", "open5gs-upfd", "open5gs-ausfd", "open5gs-mmed",
    "open5gs-pcfd", "open5gs-sgwcd", "open5gs-udmd", "open5gs-bsfd",
    "open5gs-nrfd", "open5gs-pcrfd", "open5gs-sgwud", "open5gs-udrd",
    "open5gs-seppd", "node"
]

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_DIR = os.path.join(BASE_DIR, 'net-conf')

# 定义北京时间时区（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))

def parse_timestamp(ts) -> str:
    try:
        ts_int = int(ts)
        if ts_int > 0:
            return datetime.fromtimestamp(ts_int, tz=BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
    except:
        pass
    return datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')


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

async def process_alerts(groupid: str) -> Dict[str, Any]:
    zapi = get_zapi()

    config = find_config_by_group_id(groupid)
    node_id = config.get("node_id") if config else None

    # 根据 node_id 判断监控哪些进程
    if node_id == 1:
        monitored_processes = MONITORED_PROCESSES_GSM
    elif node_id == 2:
        monitored_processes = MONITORED_PROCESSES_5G
    else:
        monitored_processes = MONITORED_PROCESSES_GSM  # 默认 GSM-R

    hosts = zapi.host.get(
        groupids=groupid,
        output=["hostid", "host"],
        selectInventory=["type"]
    )

    result = []
    has_alert = False
    alerts = []

    for host in hosts:
        hostid = host['hostid']
        hostname = host['host']
        monitoring_option = host.get('inventory', {}).get('type', '未设置')

        # 只处理 type 为 '1' 的主机
        if str(monitoring_option) == '1':
            for process_name in monitored_processes:
                test_key = f"proc.num[{process_name}]"
                items = zapi.item.get(
                    hostids=hostid,
                    search={"key_": test_key},
                    output=["itemid", "lastvalue", "lastclock"]
                )

                if not items:
                    iface = zapi.hostinterface.get(hostids=hostid, output=["interfaceid"])
                    interfaceid = iface[0]['interfaceid'] if iface else None

                    item_resp = zapi.item.create({
                        "name": f"{process_name} 进程数量",
                        "key_": test_key,
                        "type": 0,
                        "value_type": 3,
                        "hostid": hostid,
                        "interfaceid": interfaceid,
                        "delay": "60s"
                    })
                    itemid = item_resp['itemids'][0]
                    item_info = zapi.item.get(
                        itemids=itemid,
                        output=["lastvalue", "lastclock"]
                    )[0]
                else:
                    item_info = items[0]

                lastvalue = int(item_info.get('lastvalue', 0))
                lastclock = item_info.get('lastclock', 0)
                timestamp = parse_timestamp(lastclock)

                if lastvalue == 0:
                    has_alert = True
                    alerts.append({
                        "host": hostname,
                        "description": f"{process_name} 进程未运行",
                        "severity": "high",
                        "timestamp": timestamp
                    })

        # 返回主机基本信息
        result.append({
            'hostid': hostid,
            'host': hostname,
            'monitoring_option': monitoring_option
        })

    return {
        'groupid': groupid,
        'hosts': result,
        'hasAlert': has_alert,
        'alerts': alerts
    }
