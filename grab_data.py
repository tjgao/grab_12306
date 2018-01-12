#!/home/tiejun/.virtualenv/python3/bin/python

import sys, os
import datetime
import requests
import psycopg2
import json
from pathlib import Path

url_base ='https://kyfw.12306.cn/otn/'
start_url = url_base + 'leftTicket/init'
station_url = url_base + 'leftTicket/query'
price_url = url_base + 'leftTicket/queryTicketPrice'


def load_route_tasks(route_tasks_file):
    tasks = {}
    with open(route_tasks_file) as f:
        for ln in f:
            route = [x.strip().upper() for x in ln.split(',')]
            key = '-'.join(route[:2])
            if key in tasks: continue
            visited = True
            if len(route) < 3: visited = False
            elif route[2] == 'False': visited = False
            tasks[key] = [route[0], route[1], visited]
    return tasks

def load_price_tasks(price_tasks_file):
    tasks, price_file = {}, Path(price_tasks_file)
    if not price_file.is_file(): return tasks

    with open(price_tasks_file) as f:
        for ln in f:
            seg = [x.strip().upper() for x in ln.split(',')]
            key = '-'.join(seg[:4])
            visited = True
            if len(seg) < 5: visited = False
            elif route[4] == 'False': visited = False
            tasks[key] = route[:4] + [visited]
    return tasks

def load_tasks(route_tasks_file, price_tasks_file):
    return load_route_tasks(route_tasks_file), load_price_tasks(price_tasks_file) 

def store_tasks_to_disk(route_tasks, rfile, price_tasks, pfile):
    with open(rfile, 'w') as f:
        for r in route_tasks:
            f.write(', '.join([str(i) for i in route_tasks[r]]) + '\n')
    with open(pfile, 'w') as f:
        for p in price_tasks:
            f.write(', '.join([str(i) for i in price_tasks[r]]) + '\n')

def store_tickets(conn, fro, to, tdate, content):
    try:
        cur = conn.cursor()
        cur.execute("""insert into tickets (from_station, to_station, travel_date, content, update_time) values (%s,%s,%s,%s,now())""", (fro, to, tdate, content))
        conn.commit()
        return True
    except:
        conn.rollback()
        return False

def grab_tickets(ses, fro, to, tdate):
    global station_url
    print(station_url)
    resp = ses.get('{}?leftTicketDTO.from_station={}&leftTicketDTO.to_station={}&leftTicketDTO.train_date={}&purpose_codes=ADULT'.format(station_url, fro, to, tdate)) 
    try:
        o = json.loads(resp.text)
        if o.get('c_url') and o.get('status') is not None:
            print('url changed')
            station_url = url_base + o.get('c_url')
            return grab_tickets(ses, fro, to, tdate)
        print(resp.text)
        return resp.text
    except:
        return ''


def retrieve_price(text):
    obj, lst = json.loads(text), []
    if not obj.get('status') or obj.get('httpstatus') != 200 or len(obj['data']['result']) == 0:
        return []

    for r in obj['data']['result']:
        s = [i.strip() for i in r.split('|')]
        lst.append([s[2],s[16], s[17], s[35],s[13], False])
    return lst

def store_ticket_price(conn, train_no, fro_no, to_no, seat_types, content):
    cur = conn.cursor()
    cur.execute("""insert into ticket_price (train_no, from_station_no, to_station_no, seat_types, content, update_time) values (%s,%s,%s,%s,%s,now())""")

def contain_price(data):
    for k in data:
        if k == 'train_no' or k == 'OT': continue
        else: return True
    return False

def grab_ticket_price(ses, train_no, fro_no, to_no, seat_types, tdate):
    resp = ses.get('{}?train_no={}&from_station_no={}&to_station_no={}&seat_types={}&train_date={}'.format(price_url, train_no, fro_no, to_no, seat_types, tdate))
    try:
        o = json.loads(resp.text)
        if o.get('httpstatus') == 200 and o.get('status'):
            if contain_price(o['data']):
                return resp.text
        return ''
    except:
        return ''

if __name__ == '__main__':
    session = requests.Session()
    resp = session.get(start_url)

    conn_str = "dbname='ticket_cache' user='dbuser' host='localhost' password='dbuser'"
    conn = psycopg2.connect(conn_str)

    tdate = (datetime.date.today() + datetime.timedelta(days=25)).strftime('%Y-%m-%d')
    route_tasks, price_tasks = load_tasks('route_tasks.csv', 'price_tasks.csv')
    try:
        for key in route_tasks:
            r = route_tasks[key]
            print(r)
            if r[2]: continue
            text = grab_tickets(session, r[0], r[1], tdate)
            if text == '': 
                print('fail to grab ticket info: {} -> {} on {}'.format(r[0], r[1], tdate))
                continue

            price_lists = retrieve_price(text)
            for p in price_lists:
                k = '-'.join(p[:4])
                if k in price_tasks: continue
                price_tasks[k] = p

            if store_tickets(conn, r[0], r[1], tdate, text):
                route_tasks[key][2] = True
                print('Ticket {} -> {} DONE'.format(r[0], r[1]))

        
        for key in price_tasks:
            r = price_tasks[key]
            if r[4]: continue
            text = grab_ticket_price(session,r[0], r[1], r[2], r[3], r[4])  
            if text == '':
                print('fail to grab price info: #{}  {} -> {} ({}) on {}'.format(r[0], r[1], r[2], r[3], r[4]))
                continue
            if store_ticket_price(conn, r[0], r[1], r[2], r[3], text):
                price_tasks[key][5] = True
                print('Price for #{} {} -> {} on {} DONE'.format(r[0], r[1], r[2], r[3], r[4]))
    except:
        print('Uncaught excpetion: ', sys.exc_info()[0])
    finally:
        store_tasks_to_disk(route_tasks, 'route_tasks.csv',price_tasks, 'price_tasks.csv')
