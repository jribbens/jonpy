# $Id$

import os, time, hmac, sha, Cookie, re, UserDict, random
import jon.cgi as cgi
try:
  import cPickle as pickle
except ImportError:
  import pickle


class Error(Exception):
  pass


class Session(UserDict.UserDict):
  def make_hash(self, sid, secret):
    """Create a hash for 'sid'
    
    This function may be overridden by subclasses."""
    return hmac.new(secret, sid, sha).hexdigest()[:8]

  def create(self, secret):
    """Create a new session ID and, optionally hash
    
    This function must insert the new session ID (which must be 8 hexadecimal
    characters) into self["id"].

    It may optionally insert the hash into self["hash"]. If it doesn't, then
    make_hash will automatically be called later.

    This function may be overridden by subclasses.
    """
    rnd = str(time.time()) + str(random.random()) + \
      str(self.req.environ.get("UNIQUE_ID"))
    self["id"] = sha.new(rnd).hexdigest()[:8]

  def load(self):
    """Load the session dictionary from somewhere
    
    This function may be overridden by subclasses.
    It should return 1 if the load was successful, or 0 if the session could
    not be found. Any other type of error should raise an exception as usual."""
    return 1

  def save(self):
    """Save the session dictionary to somewhere
    
    This function may be overridden by subclasses."""
    pass

  def __init__(self, req, secret, cookie="jonsid", url=0, root=""):
    UserDict.UserDict.__init__(self)
    self["id"] = None
    self.req = req
    self.relocated = 0

    if self.req.cookies.has_key(cookie):
      self["id"] = req.cookies[cookie].value[:8]
      self["hash"] = req.cookies[cookie].value[8:]
      if self["hash"] != self.make_hash(self["id"], secret):
        self["id"] = None

    if url:
      for i in xrange(1, 4):
        requrl = self.req.environ.get("REDIRECT_" * i + "SESSION")
        if requrl:
          break
      if requrl and self["id"] is None:
        self["id"] = requrl[:8]
        self["hash"] = requrl[8:]
        if self["hash"] != self.make_hash(self["id"], secret):
          self["id"] = None

    if self["id"] is not None:
      if not self.load():
        self["id"] = None

    if self["id"] is None:
      if self.has_key("hash"):
        del self["hash"]
      self.create(secret)
      if not self.has_key("hash"):
        self["hash"] = self.make_hash(self["id"], secret)
      c = Cookie.SimpleCookie()
      c[cookie] = self["id"] + self["hash"]
      self.req.add_header("Set-Cookie", c[cookie].OutputString())

    if url:
      if not requrl or self["id"] != requrl[:8] or self["hash"] != requrl[8:]:
        requrl = self.req.environ["REQUEST_URI"][len(root):]
        requrl = re.sub("^/[A-Fa-f0-9]{16}/", "/", requrl)
        self.req.add_header("Location", "http://" + 
          self.req.environ["SERVER_NAME"] + root + "/" + self["id"] +
          self["hash"] + requrl)
        self.relocated = 1
      self.surl = root + "/" + self["id"] + self["hash"] + "/"


class FileSession(Session):
  def create(self, secret):
    import os, errno
    while 1:
      Session.create(self, secret)
      try:
        os.lstat("%s/%s" % (self.basedir, self["id"][:2]))
      except OSError, x:
        if x[0] == errno.ENOENT:
          os.mkdir("%s/%s" % (self.basedir, self["id"][:2]), 0700)
      try:
        os.open("%s/%s/%s" % (self.basedir, self["id"][:2], self["id"][2:]),
          os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0700)
      except OSError, x:
        if x[0] != errno.EEXIST:
          raise
      break
    self["hash"] = self.make_hash(self["id"], secret)

  def load(self):
    import fcntl, errno
    try:
      f = open("%s/%s/%s" % (self.basedir, self["id"][:2], self["id"][2:]),
        "r+")
    except IOError, x:
      if x[0] != errno.ENOENT:
        raise
      return 0
    fcntl.lockf(f.fileno(), fcntl.LOCK_EX)
    data = f.read()
    if data:
      self.data.update(pickle.loads(data))
    return 1

  def save(self):
    import fcntl
    f = open("%s/%s/%s" % (self.basedir, self["id"][:2], self["id"][2:]), "r+")
    fcntl.lockf(f.fileno(), fcntl.LOCK_EX)
    pickle.dump(self.data, f, 1)
    f.flush()
    f.truncate()
    
  def __init__(self, req, secret, basedir=None, **kwargs):
    import os, errno
    if basedir is None:
      tmp = os.environ.get("TMPDIR", "/tmp")
      while tmp[-1] == "/":
        tmp = tmp[:-1]
      basedir = "%s/jon-sessions-%d" % (tmp, os.getuid())
    self.basedir = basedir
    try:
      st = os.lstat(basedir)
      if st[4] != os.getuid():
        raise Error, "Sessions basedir is not owned by user %d" % \ os.getuid()
    except OSError, x:
      if x[0] == errno.ENOENT:
        os.mkdir(basedir, 0700)
    Session.__init__(self, req, secret, **kwargs)


class SQLSession(Session):
  def create(self, secret):
    self.dbc.execute("LOCK TABLES %s WRITE" % (self.table,))
    while 1:
      Session.create(self, secret)
      self.dbc.execute("SELECT 1 FROM %s WHERE ID=%%(ID)s" % (self.table,),
        { "ID": long(self["id"], 16) })
      if self.dbc.rowcount == 0:
        break
    self["hash"] = self.make_hash(self["id"], secret)
    self.dbc.execute("INSERT INTO %s (ID,hash,firstAccess,lastAccess) VALUES " \
      "(%%(ID)s,%%(hash)s,NOW(),NOW())" % (self.table,),
      { "ID": long(self["id"], 16), "hash": self["hash"] })
    self.dbc.execute("UNLOCK TABLES")

  def load(self):
    self.dbc.execute("SELECT data FROM %s WHERE ID=%%(ID)s" % (self.table,),
      { "ID": long(self["id"], 16) })
    if self.dbc.rowcount == 0:
      return 0
    self.data.update(pickle.loads(self.dbc.fetchone()["data"]))
    self.dbc.execute("UPDATE %s SET lastAccess=NOW() WHERE ID=%%(ID)s" %
      (self.table,), { "ID": long(self["id"], 16) })
    return 1

  def save(self):
    self.dbc.execute("UPDATE %s SET data=%%(data)s WHERE ID=%%(ID)s" %
      (self.table,), { "ID": long(self["id"], 16),
      "data": pickle.dumps(self.data, 1) })
    
  def __init__(self, req, secret, dbc=None, table="sessions", **kwargs):
    self.dbc = dbc
    self.table = table
    Session.__init__(self, req, secret, **kwargs)
