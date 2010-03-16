# $Id$

import weakref as _weakref
import Queue as _Queue
import thread as _thread


apilevel = "2.0"
threadsafety = 2

_dbmod = None
_lock = _thread.allocate_lock()
_refs = {}


def set_database(dbmod, minconns):
  if minconns < 1:
    raise ValueError("minconns must be greater than or equal to 1")
  if _dbmod is not None:
    if _dbmod == dbmod:
      return
    raise Exception("dbpool module is already in use")
  copy = ("paramstyle", "Warning", "Error", "InterfaceError", "DatabaseError",
    "DataError", "OperationalError", "IntegrityError", "InternalError",
    "ProgrammingError", "NotSupportedError")
  if len(dbmod.apilevel) != 3 or dbmod.apilevel[:2] != "2." or \
    not dbmod.apilevel[2].isdigit():
    raise ValueError("specified database module is not DB API 2.0 compliant")
  if dbmod.threadsafety < 1:
    raise ValueError("specified database module must have threadsafety level"
      " of at least 1")
  g = globals()
  g["_dbmod"] = dbmod
  g["_available"] = {}
  g["_minconns"] = minconns
  for v in copy:
    g[v] = getattr(dbmod, v)


def connect(*args, **kwargs):
  if _dbmod is None:
    raise Exception("No database module has been specified")
  try:
    return _available[repr(args) + "\0" + repr(kwargs)].get(0)
  except (KeyError, _Queue.Empty):
    return _Connection(None, None, *args, **kwargs)


def _make_available(conn):
  _lock.acquire()
  try:
    try:
      _available[repr(conn._args) + "\0" + repr(conn._kwargs)].put(conn, 0)
    except KeyError:
      q = _Queue.Queue(_minconns)
      q.put(conn, 0)
      _available[repr(conn._args) + "\0" + repr(conn._kwargs)] = q
    except _Queue.Full:
      pass
  finally:
    _lock.release()


def _connection_notinuse(ref):
  inner = _refs[ref]
  del _refs[ref]
  inner._cursorref = None
  if inner._connection is not None:
    # if the Python interpreter is exiting, _make_available might already have
    # been deleted, so check for this explicitly:
    if _make_available is not None:
      _make_available(_Connection(inner))


class _Connection:
  def __init__(self, inner, *args, **kwargs):
    if inner is None:
      self._inner = _InnerConnection(*args, **kwargs)
    else:
      self._inner = inner
    self._inner._outerref = _weakref.ref(self)
    ref = _weakref.ref(self, _connection_notinuse)
    _refs[ref] = self._inner

  def cursor(self, *args, **kwargs):
    # this method would not be necessary (i.e. the __getattr__ would take
    # care of it) but if someone does dbpool.connect().cursor() all in one
    # expression, the outer _Connection class was getting garbage-collected
    # (and hence the actual database connection being put back in the pool)
    # *in the middle of the expression*, i.e. after connect() was called but
    # before cursor() was called. So you could end up with 2 cursors on the
    # same database connection.
    return self._inner.cursor(*args, **kwargs)

  def __getattr__(self, attr):
    return getattr(self._inner, attr)

    
class _InnerConnection:
  def __init__(self, connection, *args, **kwargs):
    self._args = args
    self._kwargs = kwargs
    if connection is None:
      self._connection = _dbmod.connect(*args, **kwargs)
    else:
      self._connection = connection
    self._cursorref = None
    self._outerref = None
    self._lock = _thread.allocate_lock()

  def close(self):
    if self._cursorref is not None:
      c = self._cursorref()
      if c is not None:
        c.close()
    self._cursorref = None
    self._outerref = None
    conn = self._connection
    self._connection = None
    _make_available(_Connection(None, conn, *self._args, **self._kwargs))

  def __getattr__(self, attr):
    return getattr(self._connection, attr)

  def cursor(self, *args, **kwargs):
    self._lock.acquire()
    try:
      if self._cursorref is None or self._cursorref() is None:
        c = _Cursor(self, *args, **kwargs)
        self._cursorref = _weakref.ref(c)
        return c
    finally:
      self._lock.release()
    return connect(*self._args, **self._kwargs).cursor(*args, **kwargs)


class _Cursor:
  def __init__(self, connection, *args, **kwargs):
    self._connection = connection
    self._outer = connection._outerref()
    self._cursor = connection._connection.cursor(*args, **kwargs)
  
  def close(self):
    self._connection._cursorref = None
    self._connection = None
    self._cursor.close()
    self._outer = None

  def __getattr__(self, attr):
    return getattr(self._cursor, attr)
