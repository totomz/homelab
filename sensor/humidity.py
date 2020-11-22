#! /usr/bin/python3
import logging
import multiprocessing
from concurrent.futures.thread import ThreadPoolExecutor
from multiprocessing import Process
import statsd
import Adafruit_DHT
import time
import boto3
import sys
import subprocess
import os
from timeit import default_timer as timer
from threading import Thread
from threading import Lock
from queue import Queue
from dotenv import load_dotenv
load_dotenv()

DHT_PIN = 4
STATSD_ENDPOINT = os.environ['statsd_url']

statsd = statsd.StatsClient(STATSD_ENDPOINT, 8125, prefix='totomz.homelab')

skip_ipmi = dict()
q = Queue()

HOSTS = {
    'zione': {'ipmi': False},
    'ziobob': {'ipmi': '192.168.10.30', 'lock': Lock()},
    'ziocharlie': {'ipmi': '192.168.10.31', 'lock': Lock()},
}

vgpulock = Lock()
sensorlock = Lock()


def str2float(string, default=0.0):
    res = default
    try:
        res = float(string)
    except Exception:
        res = default

    return res


def collect_sensor():
    log = multiprocessing.get_logger()
    log.info("  --> Collecting temperature and humifity")
    global q
    lock = sensorlock.acquire(blocking=False)
    if lock is False:
        log.info(f"  --> Collecting sensors :: still being queried....skipping")
        return

    try:
        humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, DHT_PIN)
        # humidity, temperature = 0, 1
    finally:
        sensorlock.release()

    results = dict()
    results['rack.humidity'] = humidity
    results['rack.temperature'] = temperature

    log.info(f"  --> Temperature: {temperature} Humidity: {humidity}")

    if len(results) > 0:
        q.put(results)


def collect_ipmi():
    log = multiprocessing.get_logger()
    global q
    results = dict()
    log.info("  --> Collecting ipmi")

    def ipmi_poll(hostname):
        if skip_ipmi.get(hostname, 0) > 0:
            print(f"Host {hostname} is in the skipped list")
            skip_ipmi[hostname] = skip_ipmi.get(hostname, 0) - 1
            return results

        lock = HOSTS[hostname]['lock'].acquire(blocking=False)
        if lock is False:
            log.info(f"  --> Collecting ipmi :: {hostname} still being queried....skipping")
            return

        try:
            log.info(f"  --> Collecting ipmi :: {hostname} querying")
            out = subprocess.check_output("ipmitool -P root -U root -H {ip} sensor".format(ip=HOSTS[hostname]['ipmi']),
                                          stderr=subprocess.STDOUT,
                                          shell=True)
            stdout = str(out.decode('utf-8'))
            log.info(f"  --> Collecting ipmi :: {hostname} got readings")
            metrics = stdout.split("\n")
            for line in metrics:
                metric_line = line.lower()

                if "temp" not in metric_line:
                    continue

                p = metric_line.split("|")

                metric_name = f"host.{hostname}.{str.lower(str.strip(str.strip(p[0]))).replace(' ', '_')}"
                metric_value = str2float(str.strip(p[1]), 0)
                results[metric_name] = metric_value

        except Exception as e:
            step = 5
            print(f"Error processing IPMI for {hostname} - slpeeping for {step} steps")
            skip_ipmi[hostname] = step
        finally:
            HOSTS[hostname]['lock'].release()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.map(ipmi_poll, ['ziobob', 'ziocharlie'])

    log.info("  --> Collecting ipmi done")
    if len(results) > 0:
        q.put(results)


def collect_vgpu():
    log = multiprocessing.get_logger()
    global q
    global vgpulock
    hostname = "zione"
    log.info("  --> Collecting vGPU")
    results = dict()

    lock = vgpulock.acquire(blocking=False)
    if lock is False:
        log.info(f"  --> Collecting vGPU :: still being queried....skipping")
        return

    try:

        out = subprocess.check_output(f"ssh root@{hostname} \"nvidia-smi -q\"",
                                      stderr=subprocess.STDOUT,
                                      shell=True)
        stdout = str(out.decode('utf-8'))
    except Exception as e:
        log.error(f"Error vGPU", e)
    finally:
        vgpulock.release()

    lines = stdout.split("\n")
    current_gpu = None

    def pop_metric(name_prefix):
        m = lines.pop(0).lower().split(":")
        metric_name = f"{name_prefix}.{m[0].strip().replace(' ', '_')}"
        metric_value = m[1].split()[0].strip()
        results[f"host.zione.gpu.{metric_name}"] = str2float(metric_value)

    while len(lines):
        line = lines.pop(0)

        if line.startswith('GPU 0000:'):
            current_gpu = line.split('GPU ')[1].split(':')[1]

        if current_gpu is None:
            continue

        if line.startswith("    FB Memory Usage"):
            pop_metric(f"{current_gpu}.memory.framebuffer")    # total
            pop_metric(f"{current_gpu}.memory.framebuffer")    # used
            pop_metric(f"{current_gpu}.memory.framebuffer")    # free

        if line.startswith("    BAR1 Memory Usage"):
            pop_metric(f"{current_gpu}.memory.bar")    # total
            pop_metric(f"{current_gpu}.memory.bar")    # used
            pop_metric(f"{current_gpu}.memory.bar")    # free
            line = lines.pop(0)

        if line.startswith("    Utilization"):
            pop_metric(f"{current_gpu}.utilization")    # gpu
            pop_metric(f"{current_gpu}.utilization")    # memory
            pop_metric(f"{current_gpu}.utilization")    # encoder
            pop_metric(f"{current_gpu}.utilization")    # decoder
            line = lines.pop(0)

        if line.startswith("    Temperature"):
            pop_metric(f"{current_gpu}.temp")    # gpu

        if line.startswith("    Power Readings"):
            lines.pop(0)    # Skip Power Management
            pop_metric(f"{current_gpu}.power")    # Draw

        if line == "    Clocks":
            pop_metric(f"{current_gpu}.power")    # Graphics
            pop_metric(f"{current_gpu}.power")    # SM
            pop_metric(f"{current_gpu}.power")    # Memory
            pop_metric(f"{current_gpu}.power")    # Video
    log.info(f"  --> Collecting vGPU :: {len(results)}")

    if len(results) > 0:
        q.put(results)


def statsd_writer():
    log = multiprocessing.get_logger()
    global q

    while True:
        log.info("Waiting for metrics")
        metrics = q.get(block=True)

        for k in metrics:
            log.info(f":statsd {k} ==> {metrics[k]}")
            statsd.gauge(k, metrics[k])

        log.info(f"--> Bobmaaaa {len(metrics)}")


print("Starting temperature and humidity monitoring service....")
sys.stdout.flush()


if __name__ == '__main__':
    log = multiprocessing.get_logger()
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('    --> [%(asctime)s] - %(processName)s - %(message)s'))
    log.addHandler(handler)

    log.info("# Starting statsd writer")
    worker = Thread(target=statsd_writer)
    worker.daemon = True    # Die with your parent
    worker.start()

    while True:

        log.info("# waking up workers")

        for func in [
            # collect_vgpu,
            # collect_ipmi,
            collect_sensor
        ]:
            worker = Thread(target=func)
            worker.daemon = True    # Die with your parent
            worker.start()

        time.sleep(5)
