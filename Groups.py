import select
import selectors
import socket
import queue
import cv2
import numpy as np
from paddleocr import PaddleOCR
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import pymysql
import redis
from dbutils.pooled_db import PooledDB


def recvall(sock, count):
    buf = b''  # buf是一个byte类型
    while count:
        # 接受TCP套接字的数据。数据以字符串形式返回，count指定要接收的最大数据量.
        try:
            newbuf = sock.recv(count)
            if not newbuf: return None
            buf += newbuf
            count -= len(newbuf)
        except Exception as e:
            print(e)
            pass
    return buf


def read_pic(port):
    length = recvall(port, 16)  # 获得图片文件的长度,16代表获取长度
    stringData = recvall(port, int(length))  # 根据获得的文件长度，获取图片文件
    data = np.frombuffer(stringData, np.uint8)  # 将获取到的字符流数据转换成1维数组
    decimg = cv2.imdecode(data, cv2.IMREAD_COLOR)  # 将数组解码成图像
    msg_lock[port].acquire()
    msg_dic[port].put(decimg)
    msg_lock[port].notify()
    msg_lock[port].release()


def ocr_pic(port):
    db = pd.connection()
    cur = db.cursor()
    re_connect = redis.Redis(connection_pool=redis_pool)
    msg_lock[port].acquire()
    while msg_dic[port].empty():
        msg_lock[port].wait()
    image = msg_dic[port].get_nowait()
    msg_lock[port].release()
    result = ocr.ocr(image, rec=True)
    for rect1 in result:
        text = rect1[1][0]
        judge = re_connect.get(text)
        if judge is None:
            sql = "select cangku from xiangmu where number = %s"
            cur.execute(sql, text)
            judge = cur.fetchone()
            if judge is None:
                judge = "null"
        rect1[0][0][0] = int(rect1[0][0][0])
        rect1[0][0][1] = int(rect1[0][0][1])
        rect1[0][1][0] = int(rect1[0][1][0])
        rect1[0][1][1] = int(rect1[0][1][1])
        rect1[0][2][0] = int(rect1[0][2][0])
        rect1[0][2][1] = int(rect1[0][2][1])
        rect1[0][3][0] = int(rect1[0][3][0])
        rect1[0][3][1] = int(rect1[0][3][1])
        rect1[1][1] = int(rect1[1][1])
        rect1[1][0] = judge
    data = json.dumps(result)
    try:
        port.sendall(bytes(data.encode('utf-8')))
    except Exception as e:
        print("{}的连接断开".format(port))


print("wait connect")


def Bossgroup():
    global w1group
    i = 1
    while True:
        readable, writeable, exceptional = select.select(inputs, outputs, inputs)

        for r in readable:
            if r is server:  # 代表来了一个新连接
                conn, addr = server.accept()
                print("来了个新连接", conn)
                if i == 1:
                    w1group.append(conn)  # 是因为这个新建立的连接还没发数据过来，现在就接收的话程序就报错了
                    i = 0
                else:
                    w2group.append(conn)
                    i = 1
                # 所以要想实现这个客户端发数据来时server端能知道，就需要让select再监测这个conn
                msg_dic[conn] = queue.Queue(maxsize=0)  # 初始化一个队列，后面存要返回给这个客户端的数据
                msg_lock[conn] = threading.Condition()
                msg_thread_read[conn] = ThreadPoolExecutor(1)
                msg_thread_write[conn] = ThreadPoolExecutor(2)


def workgroup1():
    global w1group
    # print(workgroup)
    while True:
        readable, writeable, exceptional = select.select(w1group, outputs, w1group, 1)
        print("来了")
        for r in readable:
            msg_thread_read[r].submit(read_pic, r)
            outputs.append(r)

        for w in writeable:  # 要返回给客户端的连接列表
            msg_thread_write[w].submit(ocr_pic, w)
            outputs.remove(w)  # 确保下次循环的时候writeable,不返回这个已经处理完的连接了

        for e in exceptional:
            if e in outputs:
                outputs.remove(e)

            w1group.remove(e)

            del msg_dic[e]


def workgroup2():
    global w2group
    # print(workgroup)
    while True:
        readable, writeable, exceptional = select.select(w2group, outputs, w2group, 1)
        print("来了")
        for r in readable:
            msg_thread_read[r].submit(read_pic, r)
            outputs.append(r)

        for w in writeable:  # 要返回给客户端的连接列表
            msg_thread_write[w].submit(ocr_pic, w)
            outputs.remove(w)  # 确保下次循环的时候writeable,不返回这个已经处理完的连接了

        for e in exceptional:
            if e in outputs:
                outputs.remove(e)

            w2group.remove(e)

            del msg_dic[e]


if __name__ == "__main__":
    ocr = PaddleOCR()
    # 创建的redis的连接池
    redis_pool = redis.ConnectionPool(host='localhost', port=6379, decode_responses=True)
    pd = PooledDB(pymysql,
                  5,
                  host='localhost',
                  user='root',
                  passwd='root',
                  db='xiangmuocr',
                  port=3306)
    server = socket.socket()
    server.bind(('', 9000))
    server.listen(1000)
    server1 = socket.socket()
    server1.bind(('', 8000))
    server2 = socket.socket()
    server2.bind(('', 7000))
    cond = threading.Condition()  # 锁
    # server.setblocking(False)  # 不阻塞
    # server1.setblocking(False)  # 不阻塞
    msg_dic = {}  # 每个端口对应一个队列
    msg_lock = {}  # 每个端口对应一个锁
    msg_thread_read = {}  # 每个端口对应一个读线程池
    msg_thread_write = {}  # 每个端口对应一个写线程池
    inputs = [server, ]  # BossGroup的文件描述符
    w1group = [server1, ]  # WorkGroup1的文件描述符
    w2group = [server2, ]  # WorkGroup2的文件描述符
    outputs = []  #

    thread1 = threading.Thread(target=Bossgroup)
    thread2 = threading.Thread(target=workgroup1)
    thread3 = threading.Thread(target=workgroup2)
    thread1.start()
    thread2.start()
    thread3.start()
    thread1.join()
    thread2.join()
    thread3.join()
