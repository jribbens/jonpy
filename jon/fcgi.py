# $Id$

import cgi, struct, socket, sys, threading, errno, os, select, errno

log_level = 0

FCGI_LISTENSOCK_FILENO = 0
FCGI_VERSION_1 = 1

FCGI_BEGIN_REQUEST = 1
FCGI_ABORT_REQUEST = 2
FCGI_END_REQUEST = 3
FCGI_PARAMS = 4
FCGI_STDIN = 5
FCGI_STDOUT = 6
FCGI_STDERR = 7
FCGI_DATA = 8
FCGI_GET_VALUES = 9
FCGI_GET_VALUES_RESULT = 10
FCGI_UNKNOWN_TYPE = 11

FCGI_KEEP_CONN = 1

FCGI_RESPONDER = 1
FCGI_AUTHORIZER = 2
FCGI_FILTER = 3

FCGI_REQUEST_COMPLETE = 0
FCGI_CANT_MPX_CONN = 1
FCGI_OVERLOADED = 2
FCGI_UNKNOWN_ROLE = 3


class Record:
  def __init__(self, inf=None):
    if inf:
      data = inf.read(8)
      if not data:
        raise EOFError, "End-of-file reading record"
      (self.version, self.type, self.request_id, content_length,
        padding_length) = struct.unpack("!BBHHBx", data)
      self.content_data = inf.read(content_length)
      inf.read(padding_length)
    else:
      self.version = FCGI_VERSION_1

  def encode(self):
    padding_length = -len(self.content_data) & 7
    return struct.pack("!BBHHBB", self.version, self.type, self.request_id,
      len(self.content_data), padding_length, 0) + self.content_data + \
      "\x00" * padding_length


class NameValueData:
  def __init__(self, data=""):
    self.values = []
    pos = 0
    while pos < len(data):
      if ord(data[pos]) & 128:
        name_length = struct.unpack("!I", data[pos:pos+4])[0] & 0x7fffffff
        pos += 4
      else:
        name_length = ord(data[pos])
        pos += 1
      if ord(data[pos]) & 128:
        value_length = struct.unpack("!I", data[pos:pos+4])[0] & 0x7fffffff
        pos += 4
      else:
        value_length = ord(data[pos])
        pos += 1
      if pos + name_length + value_length > len(data):
        raise ValueError, "Unexpected end-of-data in NameValueRecord"
      self.values.append((data[pos:pos+name_length],
        data[pos+name_length:pos+name_length+value_length]))
      pos += name_length + value_length

  def encode_one(self, nameval):
    if len(nameval[0]) > 127:
      data = struct.pack("!I", len(nameval[0]) | 0x80000000)
    else:
      data = chr(len(nameval[0]))
    if len(nameval[1]) > 127:
      data += struct.pack("!I", len(nameval[1]) | 0x80000000)
    else:
      data += chr(len(nameval[1]))
    return data + nameval[0] + nameval[1]

  def encode(self):
    return reduce(lambda x,y: x+y, map(self.encode_one, self.values), "")


class InputStream:
  def __init__(self):
    self.data = []
    self.eof = 0
    self.pos = 0
    self.sema = threading.Semaphore(0)

  def add_data(self, s):
    if s:
      self.data.append(s)
    else:
      self.eof = 1
    self.sema.release()
  
  def read(self, nbytes=-1):
    if self.eof and not self.data:
      return ""
    ret = ""
    while not self.eof and nbytes != 0:
      while not self.eof and not self.data:
        self.sema.acquire()
      if self.eof:
        break
      if nbytes < 0:
        ret += self.data.pop(0)
        continue
      s = self.data[0][self.pos:self.pos+nbytes]
      self.pos += nbytes
      ret += s
      nbytes -= len(s)
      if self.pos >= len(self.data[0]):
        self.data.pop(0)
        self.pos = 0
    return ret


class Connection(threading.Thread):
  def __init__(self, socket, handler_types, *args, **kwargs):
    threading.Thread.__init__(self, *args, **kwargs)
    self.socket = socket
    self.socketf = socket.makefile("r+b", 0)
    self.socketlock = threading.Lock()
    self.handler_types = handler_types
    self.fileno = self.socket.fileno()

  def log(self, level, request_id, message):
    if log_level >= level:
      if request_id:
        log_file.write("%3d/%3d %s\n" % (self.fileno, request_id, message))
      else:
        log_file.write("%3d     %s\n" % (self.fileno, message))

  def close(self):
    self.socketlock.acquire()
    try:
      self.socketf.close()
    finally:
      self.socketlock.release()

  def write(self, rec):
    self.socketlock.acquire()
    try:
      self.socketf.write(rec.encode())
    finally:
      self.socketlock.release()

  def run(self):
    self.log(2, 0, "New connection running")
    self.requests = {}
    while 1:
      try:
        # this select *should* be pointless, however it works around a bug
        # in OpenBSD whereby the read() does not get interrupted when
        # another thread closes the socket (and it does no harm on other
        # OSes)
        select.select([self.socketf], [], [])
        rec = Record(self.socketf)
      except:
        x = sys.exc_info()[1]
        if isinstance(x, EOFError) or isinstance(x, ValueError) or \
          (isinstance(x, socket.error) and x[0] == errno.EBADF):
          self.log(2, 0, "EOF received on connection")
          for req in self.requests.values():
            req.aborted = 2
          break
        else:
          raise
      if rec.type == FCGI_GET_VALUES:
        data = NameValueData(rec.content_data)
        self.log(3, 0, "FCGI_GET_VALUES: %s" % `data.values`)
        reply = Record()
        reply.type = FCGI_GET_VALUES_RESULT
        reply.request_id = 0
        reply_data = NameValueData()
        for nameval in data.values:
          if nameval[0] == "FCGI_MAX_CONNS":
            reply_data.values.append(("FCGI_MAX_CONNS", "10"))
          elif nameval[0] == "FCGI_MAX_REQS":
            reply_data.values.append(("FCGI_MAX_REQS", "10"))
          elif nameval[0] == "FCGI_MPXS_CONNS":
            reply_data.values.append(("FCGI_MPXS_CONNS", "1"))
        reply.content_data = reply_data.encode()
        self.write(reply)
      elif rec.type == FCGI_BEGIN_REQUEST:
        (role, flags) = struct.unpack("!HB", rec.content_data[:3])
        handler_type = self.handler_types.get(role)
        self.log(2, rec.request_id,
          "FCGI_BEGIN_REQUEST: role = %d, flags = %d" % (role, flags))
        if not handler_type:
          self.log(2, rec.request_id, "no handler for this role, rejecting")
          reply = Record()
          reply.type = FCGI_END_REQUEST
          reply.request_id = rec.request_id
          reply.content_data = struct.pack("!IBBBB",
            0, FCGI_UNKNOWN_ROLE, 0, 0, 0)
          self.write(reply)
        else:
          req = Request(handler_type, self, rec.request_id, flags)
          self.requests[rec.request_id] = req
      elif rec.type == FCGI_PARAMS:
        req = self.requests.get(rec.request_id)
        if req:
          if rec.content_data:
            data = NameValueData(rec.content_data)
            self.log(3, rec.request_id, "FCGI_PARAMS: %s" % `data.values`)
            for nameval in data.values:
              req.environ[nameval[0]] = nameval[1]
          else:
            self.log(2, rec.request_id, "starting request thread")
            req.start()
        else:
          self.log(2, rec.request_id, "unknown request_id (FCGI_PARAMS)")
      elif rec.type == FCGI_ABORT_REQUEST:
        req = self.requests.get(rec.request_id)
        if req:
          self.log(2, rec.request_id, "FCGI_ABORT_REQUEST")
          req.aborted = 1
        else:
          self.log(2, rec.request_id, "unknown request_id (FCGI_ABORT_REQUEST)")
      elif rec.type == FCGI_STDIN:
        req = self.requests.get(rec.request_id)
        if req:
          if log_level >= 4:
            self.log(4, rec.request_id, "FCGI_STDIN: %s" % `rec.content_data`)
          req.fcgi_stdin.add_data(rec.content_data)
        else:
          self.log(2, rec.request_id, "unknown request_id (FCGI_STDIN)")
      elif rec.type == FCGI_DATA:
        req = self.requests.get(rec.request_id)
        if req:
          if log_level >= 4:
            self.log(4, rec.request_id, "FCGI_DATA: %s" % `rec.content_data`)
          req.fcgi_data.add_data(rec.content_data)
        else:
          self.log(2, rec.request_id, "unknown request_id (FCGI_DATA)")
      else:
        self.log(2, rec.request_id, "unknown type %d" % rec.type)
        reply = Record()
        reply.type = FCGI_UNKNOWN_TYPE
        reply.request_id = 0
        reply.content_data = chr(rec.type) + "\x00" * 7
        self.write(reply)
      

class Server:
  def __init__(self, handler_types, max_requests=0):
    self.handler_types = handler_types
    self.max_requests = max_requests

  def log(self, level, message):
    if log_level >= level:
      log_file.write("        %s\n" % message)

  def run(self):
    self.log(1, "Server.run()")
    web_server_addrs = os.environ.get("FCGI_WEB_SERVER_ADDRS", "").split(",")
    self.log(1, "web_server_addrs = %s" % `web_server_addrs`)
    sock = socket.fromfd(sys.stdin.fileno(), socket.AF_INET, socket.SOCK_STREAM)
    try:
      sock.getpeername()
    except socket.error, x:
      if x[0] != errno.ENOTSOCK and x[0] != errno.ENOTCONN:
        raise
      if x[0] == errno.ENOTSOCK:
        self.log(1, "stdin not socket - falling back to CGI")
        cgi.CGIRequest(self.handler_types[FCGI_RESPONDER]).process()
        return
    sock.setblocking(1)
    while 1:
      (newsock, addr) = sock.accept()
      self.log(1, "accepted connection %d" % newsock.fileno())
      if web_server_addrs and addr not in web_server_addrs:
        self.log(1, "not in web_server_addrs - rejected")
        newsock.close()
        continue
      Connection(newsock, self.handler_types).start()
      del newsock
      if self.max_requests > 0:
        self.max_requests -= 1
        if self.max_requests <= 0:
          self.log(1, "reached max_requests, exiting")
          break
    sock.close()


class Request(cgi.Request, threading.Thread):
  def __init__(self, handler_type, connection, request_id, flags,
    *args, **kwargs):
    cgi.Request.__init__(self, handler_type)
    threading.Thread.__init__(self, *args, **kwargs)
    self.__connection = connection
    self.__request_id = request_id
    self.__flags = flags
    self.fcgi_data = InputStream()
    self.fcgi_stdin = InputStream()
    self.environ = {}
    self._stderr_used = 0
  
  def log(self, level, message):
    if log_level >= level:
      log_file.write("%3d/%3d %s\n" % (self.__connection.fileno,
        self.__request_id, message))

  def run(self):
    self.log(2, "New request running")
    self._read_cgi_data(self.environ, self.fcgi_stdin)
    self.log(3, "Read CGI data: %s" % `self.params`)
    self.log(2, "Calling handler")
    self._handler_type().process(self)
    self.log(2, "Handler finished")
    self.flush()
    if self.aborted < 2:
      try:
        rec = Record()
        rec.type = FCGI_STDOUT
        rec.request_id = self.__request_id
        rec.content_data = ""
        self.__connection.write(rec)
        self.log(2, "Closed FCGI_STDOUT")
        if self._stderr_used:
          rec.type = FCGI_STDERR
          self.__connection.write(rec)
          self.log(2, "Closed FCGI_STDERR")
        rec.type = FCGI_END_REQUEST
        rec.request_id = self.__request_id
        rec.content_data = struct.pack("!IBBBB", 0, FCGI_REQUEST_COMPLETE,
          0, 0, 0)
        self.__connection.write(rec)
        self.log(2, "Sent FCGI_END_REQUEST")
      except IOError, x:
        if x[0] == errno.EPIPE:
          self.log(2, "EPIPE during request finalisation")
        else:
          raise
    if not self.__flags & FCGI_KEEP_CONN:
      self.__connection.close()
      self.log(2, "Closed connection")
    del self.__connection.requests[self.__request_id]
    self.log(2, "Request complete")

  def _write(self, s):
    if log_level >= 4:
      self.log(4, "FCGI_STDOUT: %s" % `s`)
    self._recwrite(FCGI_STDOUT, s)

  def error(self, s):
    if log_level >= 4:
      self.log(4, "FCGI_STDERR: %s" % `s`)
    self._recwrite(FCGI_STDERR, s)
    self._stderr_used = 1

  def _recwrite(self, type, s):
    if s:
      pos = 0
      while pos < len(s):
        if self.aborted:
          return
        rec = Record()
        rec.type = type
        rec.request_id = self.__request_id
        if pos == 0 and len(s) <= 65535:
          # (avoid copying in the common case of s <= 65535 bytes)
          rec.content_data = s
        else:
          rec.content_data = s[pos:pos+65535]
        pos += len(rec.content_data)
        try:
          self.__connection.write(rec)
        except IOError, x:
          if x[0] == errno.EPIPE:
            self.aborted = 2
            self.log(2, "Aborted due to EPIPE")
          else:
            raise

  def _flush(self):
    pass


if log_level > 0:
  log_file = open("/tmp/fcgi.log", "a", 1)
