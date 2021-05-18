# LzpNIO
运用分段锁，NIO主从多线程模式模式设计网络图片的传输和识别


# 初期

通过生产者消费者模式在客户端将图片传输给服务器端的时候，服务端通过一个线程操作栈来接收，栈顶始终保持最新的图片，对栈的操作需要上锁，另外一个线程通过获取锁来读取栈顶的图片，然后进行神经网络检测，将检测后的图片重发发送给客户端，客户端新开线程进行接收图片并进行显示。


# 后期

后期发现传输图片耗时特别长，所以在服务端将神经网络检测后的数据发还给客户端，让客户端进行标志然后显示，因此客户端必须进行同步等待，发送一张照片给服务端之后必须等待服务端发还回处理结果，才可以进行处理其他的图片。

# socket连接请求影响性能

而后发现当多个客户端与服务端进行连接的时候，服务端都得开启一个线程去接收这个请求，然后还要继续另开一个线程去处理这个图片。严重影响了实时性。

# NIO主从Reactor多线程模式

所以采用NIO的之后，使用单Reactor单线程模式，在一个主线程里面，采用select来进行处理客户端的连接请求同时在线程里面完成图片的接收和处理以及传输结果给客户端，返现实时性虽然提高了，但是还是没到到要求。

继而采用主从Reactor多线程模式，大幅度提高了实时性，开启三个线程，一个线程里面的一个select充当主Reactor来专门处理客户端的连接请求，监听到请求连接之后会重新分配一个端口与客户端进行数据传输，这个端口就会被包装到另外两个线程里面的select充当从Reactor，专门来数据处理和发送。

采用轮询的方式，分别分配给这两个Reactor，达到一定程度负载均衡。

# 将读写任务交给线程池来完成

因为从Reactor线程，在接收的时候接收的是图片，接收耗时非常的长，所以我们将接受任务提交给线程池来处理，同时神经网络检测图片的任务以及传输数据返回给客户端的任务也提交给线程池来解决，从而保证了主线程快速运行。这里经过了反复的实验，得出的结论就是为每个端口也同时分配读线程池和写线程池，读线程的线程数量最多只能是一个newSingleThreadExecutor，或者可以上锁，因为如果两个线程同时对端口进行recv获取到本该在一起的数据，那么就发生永久性的阻塞，因为接收图片是根据数据的长度来进行计算接收的。线程池的阻塞队列可以是无穷的队列，写线程池可以适量。为了防止出现TCP粘包和拆包的现象，定制自己的协议。先把图片进行编码成流数据，然后赋值到内存缓存中去，将流数据转换为矩阵，然后矩阵字符串化，然后发送字符串的长度给服务端，告诉服务端总共需要接收多少数据。服务端根据总长度来进行接收多少数据后停止。
放置多个线程同时对一个channel进行recv而阻塞

# 仿照jdk1.7 ConcurrentHashMap

同时为每个与客户端进行数据传输的端口配置一个队列，python中的字典，就相当于key-value结构，key代表这个端口，value就是这个端口对应的队列。想要对某个端口的任务队列进行插入或者读取任务的时候，需要对这个队列上锁，而队列又在字典里面，所以我们根据jdk1.7concurrenthashmap的原理，对字典上分段锁，减小锁的粒度，假设要取8080端口对应的任务队列里面的任务的时候，只对这个key-value上锁，其他线程依然可以对字典中其他端口的任务队列进行操作。同时如果任务队列里面的任务为空时，获取到读取任务的锁的时候，会调用condition.await将自己挂起，然后将锁释放出去，同时通过while操作循环检查任务队列是否为空，防止虚假唤醒。当有线程往队列里面插入数据的时候，就会唤醒一个因队列为空而被挂起的线程。

# 采用redis存储数据，增加响应速度

因为每个货单号都会对应一个仓库，因为数据检测量较大，所以采用redis存储热数据，分担数据库的压力，可以将货单号和仓库号存储到redis中，将通过神经网络检测到的货单号在redis中进行查询，可以立刻返回检测结果，如果检测不到数据结果，在到数据库进行查询。同时设计zset数据结构，存储每个仓库的货物数量，value值为仓库的名字，score值为仓库的货物的数量，通过货物的数量对仓库进行排序，方便进行直接查询，zset的底层结构后面复习redis的时候继续填写。redis进行写数据的时候就需要进行锁机制
