# $Id$

from mod_python import apache
import cgi, fakefile


class Error(Exception):
  pass


class InputStream(fakefile.FakeInput):
  def __init__(self, modpy_req):
    fakefile.FakeInput.__init__(self)
    self._modpy_req = modpy_req

  def _read(self, size=-1):
    return self._modpy_req.read(size)


class Request(cgi.Request):
  def _init(self, modpy_req):
    self._modpy_req = modpy_req
    self._build_environ()
    self._redirected = 0
    self.stdin = InputStream(modpy_req)
    cgi.Request._init(self)

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

  def process(self, modpy_req):
    self._init(modpy_req)
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
