# $Id$

from mod_python import apache
import jon.cgi as cgi


class Error(Exception):
  pass


class InputStream:
  def __init__(self, modpy_req):
    self._modpy_req = modpy_req
    self.closed = 0
    self.mode = "rb"
    self.name = "<mod_python input stream>"
    self.softspace = 0

  def close(self):
    self.closed = 1

  def _check_open(self):
    if self.closed:
      raise IOError, "File is closed"

  def flush(self):
    self._check_open()

  def read(self, size=-1):
    self._check_open()
    return self._modpy_req.read(size)

  def readline(self, size=-1):
    self._check_open()
    return self._modpy_req.readline(size)

  def readlines(self, size=-1):
    self._check_open()
    lines = []
    while 1:
      line = self.readline()
      if line == "":
        return lines
      lines.append(line)
      if size >= 0:
        size -= len(line)
        if size <= 0:
          return lines

  def xreadlines(self):
    self._check_open()
    import xreadlines
    return xreadlines.xreadlines(self)

  def seek(self, offset, whence=0):
    raise IOError, "cannot seek() mod_python input stream"

  def tell(self):
    raise IOError, "cannot tell() mod_python input stream"

  def truncate(self):
    raise IOError, "cannot truncate() mod_python input stream"
  
  def write(self, s):
    raise IOError, "cannot write() mod_python input stream"

  def writelines(self, s):
    raise IOError, "cannot writelines() mod_python input stream"


class Request(cgi.Request):
  def __init__(self, handler_type, modpy_req):
    self._modpy_req = modpy_req
    cgi.Request.__init__(self, handler_type)
    self._build_environ()
    self._redirected = 0

  def _build_environ(self):
    modpy_req = self._modpy_req
    modpy_req.add_common_vars()
    self.environ = {}
    env = self.environ
    for key in modpy_req.subprocess_env.keys():
      env[key] = modpy_req.subprocess_env[key]
    if len(modpy_req.path_info):
      env["SCRIPT_NAME"] = modpy_req.uri[:-len(modpy_req.path_info)]
    else:
      env["SCRIPT_NAME"] = modpy_req.uri

  def output_headers(self):
    if self._doneHeaders:
      raise cgi.SequencingError, "output_headers() called twice"
    if self._redirected:
      self._modpy_req.status = apache.HTTP_MOVED_TEMPORARILY
    self._modpy_req.send_http_header()
    self._doneHeaders = 1

  def clear_headers(self):
    if self._doneHeaders:
      raise cgi.SequencingError, "cannot clear_headers() after output_headers()"
    for key in self._modpy_req.headers_out.keys():
      del self._modpy_req.headers_out[key]
    self._redirected = 0

  def add_header(self, hdr, val):
    if self._doneHeaders:
      raise cgi.SequencingError, \
        "cannot add_header(%s) after output_headers()" % `hdr`
    if hdr == "Content-Type":
      self._modpy_req.content_type = val
    else:
      self._modpy_req.headers_out.add(hdr, val)
    if hdr == "Location":
      self._redirected = 1

  def set_header(self, hdr, val):
    if self._doneHeaders:
      raise cgi.SequencingError, \
        "cannot set_header(%s) after output_headers()" % `hdr`
    if hdr == "Content-Type":
      self._modpy_req.content_type = val
    else:
      self._modpy_req.headers_out[hdr] = val
    if hdr == "Location":
      self._redirected = 1

  def del_header(self, hdr, val):
    if self._doneHeaders:
      raise cgi.SequencingError, \
        "cannot del_header(%s) after output_headers()" % `hdr`
    if hdr == "Content-Type":
      raise Error, "cannot del_header(\"Content-Type\")"
    del self._modpy_req.headers_out[hdr]
    if hdr == "Location":
      self._redirected = 0

  def process(self):
    self._modpy_req.add_common_vars()
    self._read_cgi_data(self.environ, InputStream(self._modpy_req))
    try:
      self._handler_type().process(self)
    except:
      self.traceback()
    self.flush()
    return apache.OK
  
  def error(self, s):
    apache.log_error(s, apache.APLOG_ERR, self._modpy_req.server)

  def _write(self, s):
    if not self.aborted:
      self._modpy_req.write(s)

  def _flush(self):
    pass
