#! /usr/bin/python3
import statsd
import Adafruit_DHT
import time
import boto3
import sys
import subprocess
import os
from timeit import default_timer as timer

from dotenv import load_dotenv
load_dotenv()

DHT_PIN = 4
STATSD_ENDPOINT = os.environ['statsd_url']

statsd = statsd.StatsClient(STATSD_ENDPOINT, 8125, prefix='totomz.homelab')

skip_ipmi = dict()


def str2float(string, default=0.0):
    res = default
    try:
        res = float(string)
    except Exception:
        res = default

    return res


def collect_sensor():
    humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, DHT_PIN)
    # humidity, temperature = 0, 1
    results = dict()
    results['humidity'] = humidity
    results['temperature'] = temperature
    return results


def collect_ipmi(hostname, ip):

    results = dict()
    if skip_ipmi.get(hostname, 0) > 0:
        print(f"Host {hostname} is in the skipped list")
        skip_ipmi[hostname] = skip_ipmi.get(hostname, 0) - 1
        return results

    try:
        out = subprocess.check_output("ipmitool -P root -U root -H {ip} sensor".format(ip=ip),
                                      stderr=subprocess.STDOUT,
                                      shell=True)
        stdout = str(out.decode('utf-8'))

        metrics = stdout.split("\n")
        for line in metrics:
            metric_line = line.lower()

            if "temp" not in metric_line:
                continue

            p = metric_line.split("|")

            metric_name = str.lower(str.strip(str.strip(p[0]))).replace(" ", "_")
            metric_value = str2float(str.strip(p[1]), 0)
            results[metric_name] = metric_value

    except Exception as e:
        step = 5
        print(f"Error processing IPMI for {hostname} - slpeeping for {step} steps")
        skip_ipmi[hostname] = step

    return results


print("Starting temperature and humidity monitoring service....")
sys.stdout.flush()

while True:

    ####################
    # Environment data #
    ####################
    start = timer()

    metricset = collect_sensor()
    print("{2} Temp={0:0.1f}*C Humidity={1:0.1f}%".format(metricset['temperature'], metricset['humidity'], time.strftime("%Y-%m-%d %H:%M:%S")))
    sys.stdout.flush()

    for k in metricset:
        statsd.gauge(f"rack.{k}", metricset[k])

    end = timer()
    print("temp & humidity: {}".format(end - start))

    ################
    # IPMI Metrics #
    ################
    hosts = (
        ("ziobob", "192.168.10.30"),
        ("ziocharlie", "192.168.10.31"),
    )
    start = timer()
    for host in hosts:
        metricset = ipmi = collect_ipmi(hostname=host[0], ip=host[1])

        for k in metricset:
            statsd.gauge(f"host.{host}.{k}", metricset[k])

    end = timer()
    print("IPMI: {}".format(end - start))

    time.sleep(5)
