# $Id$

import sys, re, os, Cookie, errno


class Error(Exception):
  pass
class SequencingError(Error):
  pass


_url_encre = re.compile(r"[^A-Za-z0-9-]")
_url_decre = re.compile(r"%([0-9A-Fa-f]{2})")
_html_encre = re.compile("[&<>\"'+]")
_html_encodes = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;",
                  "'": "&#39;", "+": "&#43;" }

def html_encode(raw):
  return re.sub(_html_encre, lambda m: _html_encodes[m.group(0)], str(raw))

def url_encode(raw):
  return re.sub(_url_encre, lambda m: "%%%02X" % ord(m.group(0)), str(raw))

def url_decode(enc):
  s = enc.replace("+", " ")
  return re.sub(_url_decre, lambda m: chr(int(m.group(1), 16)), s)


class Request:
  def __init__(self, handler_type):
    self._handler_type = handler_type
    self._doneHeaders = 0
    self._headers = []
    self._bufferOutput = 0
    self._output = []
    self.params = {}
    self.cookies = Cookie.SimpleCookie()
    self.aborted = 0
    self.set_header("Content-Type", "text/html; charset=iso-8859-1")

  def output_headers(self):
    if self._doneHeaders:
      raise SequencingError, "output_headers() called twice"
    for pair in self._headers:
      self._write("%s: %s\r\n" % pair)
    self._write("\r\n")
    self._doneHeaders = 1

  def clear_headers(self):
    if self._doneHeaders:
      raise SequencingError, "cannot clear_headers() after output_headers()"
    self._headers = []

  def add_header(self, hdr, val):
    if self._doneHeaders:
      raise SequencingError, \
        "cannot add_header(%s) after output_headers()" % `hdr`
    self._headers.append((hdr, val))

  def set_header(self, hdr, val):
    if self._doneHeaders:
      raise SequencingError, \
        "cannot set_header(%s) after output_headers()" % `hdr`
    self.del_header(hdr)
    self._headers.append((hdr, val))

  def del_header(self, hdr):
    if self._doneHeaders:
      raise SequencingError, \
        "cannot del_header(%s) after output_headers()" % `hdr`
    while 1:
      for s in self._headers:
        if s[0] == hdr:
          self._headers.remove(s)
          break
      else:
        break

  def set_buffering(self, f):
    if self._output and not f:
      self.flush()
    self._bufferOutput = f

  def flush(self):
    if not self._doneHeaders:
      self.output_headers()
    for s in self._output:
      self._write(s)
    self._output = []
    self._flush()

  def clear_output(self):
    if not self._bufferOutput:
      raise SequencingError, "cannot clear output when not buffering"
    self._output = []

  def error(self, s):
    raise NotImplementedError, "error must be overridden"

  def _write(self, s):
    raise NotImplementedError, "_write must be overridden"

  def _flush(self):
    raise NotImplementedError, "_flush must be overridden"

  def write(self, s):
    if self._bufferOutput:
      self._output.append(str(s))
    else:
      if not self._doneHeaders:
        self.output_headers()
      self._write(s)

  def _mergevars(self, encoded):
    """Extracts the variable-value pairs from the URL-encoded input string and
    merges them into the output dictionary. Variable-value pairs are separated
    from each other by the '&' character. Missing values are allowed.

    If the variable name ends with a '*' character, then the value that is
    placed in the dictionary will be a list. This is useful for multiple-value
    fields."""
    for pair in encoded.split("&"):
      if pair == "":
        continue
      nameval = pair.split("=", 1)
      name = url_decode(nameval[0])
      if len(nameval) > 1:
        val = url_decode(nameval[1])
      else:
        val = None
      if name.endswith("!") or name.endswith("!*"):
        continue
      if name.endswith("*"):
        if self.params.has_key(name):
          self.params[name].append(val)
        else:
          self.params[name] = [val]
      else:
        self.params[name] = val

  def _mergemime(self, encoded):
    """Extracts the variable-value pairs from the URL-encoded input string and
    merges them into the output dictionary. Variable-value pairs are separated
    from each other by the '&' character. Missing values are allowed.

    If the variable name ends with a '*' character, then the value that is
    placed in the dictionary will be a list. This is useful for multiple-value
    fields. If the variable name ends with a '!' character (before the '*' if
    present) then the value will be a jmime.Entity object."""
    import mime
    headers = "Content-Type: %s\n" % os.environ["CONTENT_TYPE"]
    body = encoded.read()
    for entity in mime.Entity(body, mime=1, headers=headers).entities:
      if not entity.content_disposition:
        continue
      if entity.content_disposition[0] != 'form-data':
        continue
      name = entity.content_disposition[1].get("name")
      if name[-1:] == "*":
        if self.params.has_key(name):
          if name[-2:-1] == "!":
            self.params[name].append(entity)
          else:
            self.params[name].append(entity.body)
        else:
          if name[-2:-1] == "!":
            self.params[name] = [entity]
          else:
            self.params[name] = [entity.body]
      elif name[-1:] == "!":
        self.params[name] = entity
      else:
        self.params[name] = entity.body

  def read_cgi_data(self, environ, inf):
    if environ.has_key("QUERY_STRING"):
      self._mergevars(environ["QUERY_STRING"])
    if environ.get("REQUEST_METHOD") == "POST":
      if environ.get("CONTENT_TYPE", "").startswith("multipart/form-data"):
        self._mergemime(inf)
      else:
        self._mergevars(inf.read(int(environ.get("CONTENT_LENGTH", "-1"))))
    if environ.has_key("HTTP_COOKIE"):
      self.cookies.load(environ["HTTP_COOKIE"])

  def traceback(self):
    import traceback
    exc = sys.exc_info()
    try:
      self.clear_headers()
      self.clear_output()
      self.set_header("Content-Type", "text/html; charset=iso-8859-1")
    except SequencingError:
      pass
    self.write("<html><head><title>wt traceback</title></head><body>"
      "<h1>wt traceback</h1><pre><b>")
    for line in traceback.format_exception_only(exc[0], exc[1]):
      self.write(html_encode(line))
      self.error(line)
    self.write("</b>\n")
    lines = traceback.format_tb(exc[2])
    lines.reverse()
    for line in lines:
      self.write(html_encode(line))
      self.error(line)
    self.write("</body></html>\n")


class CGIRequest(Request):
  def __init__(self, handler_type):
    Request.__init__(self, handler_type)
    self.__out = sys.stdout
    self.__err = sys.stderr
    self.environ = os.environ

  def process(self):
    self.read_cgi_data(self.environ, sys.stdin)
    try:
      self._handler_type().process(self)
    except:
      self.traceback()
    self.flush()

  def error(self, s):
    self.__err.write(s)

  def _write(self, s):
    if not self.aborted:
      try:
        self.__out.write(s)
      except IOError, x:
        # Ignore EPIPE, caused by the browser having gone away
        if x[0] != errno.EPIPE:
          raise
        self.aborted = 1

  def _flush(self):
    if not self.aborted:
      try:
        self.__out.flush()
      except IOError, x:
        # Ignore EPIPE, caused by the browser having gone away
        if x[0] != errno.EPIPE:
          raise
        self.aborted = 1


class Handler:
  def process(self, req):
    raise NotImplementedError, "handler process function must be overridden"
