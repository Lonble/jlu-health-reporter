#!/usr/bin/env python3
import os, sys, re, json, random, logging as log, threading, urllib3, requests, getopt
from time import time, sleep, ctime
DEBUG = 0#+1
# times to retry a failed task
RETRIES = 90
# network timeout
TIMEOUT = 10
# retry interval
INTERVAL = 30
# random delay to lower the load of ehall
RAND_DELAY = 30 * 60

# parse arguments
try:
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'i')
except getopt.GetoptError as e:
    sys.stderr.write('error: ' + e.msg + '\n')
    exit(1)

# define CONFIG
if len(args) == 0:
    CONFIG = sys.path[0] + '/config.json'
elif len(args) == 1:
    CONFIG = args[0]
else:
    sys.stderr.write('error: too many arguments\n')
    exit(1)

# whether run immediately or not
imm = False
for opt in opts:
    if '-i' == opt[0]:
        imm = True
if imm:
    RETRIES = 50
    INTERVAL = 2

def runTask(task):
    if not imm:
        sleep(random.random()*RAND_DELAY) # sleep random minutes in each thread
    for _ in range(RETRIES):
        hour = int(ctime().split()[-2].split(':')[0])
        if hour not in range(6, 12) and hour not in range(21, 24):
            log.error('Not in the period')
            return
        try:
            s = requests.Session()
            s.headers.update({'Referer': 'https://ehall.jlu.edu.cn/'})
            s.verify = False
            
            log.info('Authenticating...')
            r = s.get('https://ehall.jlu.edu.cn/jlu_portal/login', timeout=TIMEOUT)
            pid = re.search('(?<=name="pid" value=")[a-z0-9]{8}', r.text)[0]
            log.debug(f"PID: {pid}")
            postPayload = {'username': task['username'], 'password': task['password'], 'pid': pid}
            r = s.post('https://ehall.jlu.edu.cn/sso/login', data=postPayload, timeout=TIMEOUT)

            log.info('Requesting form...')
            r = s.get(f"https://ehall.jlu.edu.cn/infoplus/form/{task['transaction']}/start", timeout=TIMEOUT)
            csrfToken = re.search('(?<=csrfToken" content=").{32}', r.text)[0]
            log.debug(f"CSRF: {csrfToken}")
            postPayload = {'idc': task['transaction'], 'csrfToken': csrfToken}
            r = s.post('https://ehall.jlu.edu.cn/infoplus/interface/start', data=postPayload, timeout=TIMEOUT)
            sid = re.search('(?<=form/)\\d*(?=/render)', r.text)[0]
            log.debug(f"Step ID: {sid}")
            postPayload = {'stepId': sid, 'csrfToken': csrfToken}
            r = s.post('https://ehall.jlu.edu.cn/infoplus/interface/render', data=postPayload, timeout=TIMEOUT)
            data = json.loads(r.content)['entities'][0]

            log.info('Submitting form...')
            for k, v in task['fields'].items():
                if eval(task['conditions'].get(k, 'True')):
                    data['data'][k] = v
            postPayload = {
                'actionId': 1,
                'formData': json.dumps(data['data']),
                'nextUsers': '{}',
                'stepId': sid,
                'timestamp': int(time()),
                'boundFields': ','.join(data['fields'].keys()),
                'csrfToken': csrfToken
            }
            log.debug(f"Payload: {postPayload}")
            r = s.post('https://ehall.jlu.edu.cn/infoplus/interface/doAction', data=postPayload, timeout=TIMEOUT)
            log.debug(f"Result: {r.text}")
            if json.loads(r.content)['ecode'] != 'SUCCEED' :
                raise Exception('The server returned a non-successful status.')
            log.info('Success!')
            return
        except Exception as e:
            log.error(e)
            sleep(INTERVAL)
    log.error('Failed too many times, exiting...')

log.basicConfig(
    level=log.INFO-10*DEBUG,
    format='%(asctime)s %(threadName)s:%(levelname)s %(message)s'
)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log.warning('Started.')

log.info(f'Reading config from {CONFIG}')
config = json.load(open(CONFIG))
for task in config.get('tasks', config.get('users', [{}])):
    for k in ['username', 'password', 'transaction']:
        task.setdefault(k, config.get(k))
    for k in ['fields', 'conditions']:
        task[k] = {**config.get(k, {}), **task.get(k, {})}
    if task['transaction']:
        threading.Thread(
            target=runTask,
            name=f"{task['transaction']}:{task['username']}",
            args=(task,)
        ).start()
    if imm:
        sleep(INTERVAL)
